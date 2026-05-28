"""Tests for the netcdf IO layer that abstracts local-vs-S3 access.

The deployed MCP must read netcdf from MinIO (s3://project-surimi/NetCDF/...),
not just local disk. netcdf.io centralizes open + hashing + existence so the
inspect/analytics/regions modules do not each reimplement S3 handling.
"""
from __future__ import annotations

import hashlib

import pytest
import xarray as xr

from netcdf import io as ncio


# ---------- local path handling (regression) ----------

def test_open_dataset_opens_local_path(tiny_nc):
    with ncio.open_dataset(tiny_nc) as ds:
        assert "biomass" in ds.data_vars


def test_open_dataset_accepts_file_uri(tiny_nc):
    with ncio.open_dataset("file://" + tiny_nc) as ds:
        assert "biomass" in ds.data_vars


def test_resource_sha256_matches_local_file(tiny_nc):
    expected = hashlib.sha256(open(tiny_nc, "rb").read()).hexdigest()
    assert ncio.resource_sha256(tiny_nc) == expected


def test_resource_sha256_stable_across_calls(tiny_nc):
    assert ncio.resource_sha256(tiny_nc) == ncio.resource_sha256(tiny_nc)


def test_exists_true_for_local(tiny_nc):
    assert ncio.exists(tiny_nc) is True


def test_exists_false_for_missing_local(tmp_path):
    assert ncio.exists(str(tmp_path / "nope.nc")) is False


def test_open_dataset_raises_on_missing_local(tmp_path):
    with pytest.raises(ncio.NetCDFIOError):
        ncio.open_dataset(str(tmp_path / "nope.nc"))


# ---------- S3 dispatch ----------

def test_is_s3_uri():
    assert ncio.is_s3_uri("s3://bucket/key.nc") is True
    assert ncio.is_s3_uri("/tmp/local.nc") is False
    assert ncio.is_s3_uri("file:///tmp/local.nc") is False


def _fake_s3fs(monkeypatch, tiny_nc, captured, cache_dir):
    """Install a fake s3fs whose get_file copies the local fixture, and point
    the cache at a tmp dir so downloads land there."""
    import shutil
    import types

    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://minio.test")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    monkeypatch.setattr(ncio, "_CACHE_DIR", str(cache_dir))

    class _FakeFS:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def get_file(self, uri, local):
            captured["downloaded"] = uri
            shutil.copy(tiny_nc, local)

        def exists(self, uri):
            return True

    monkeypatch.setitem(
        __import__("sys").modules, "s3fs",
        types.SimpleNamespace(S3FileSystem=_FakeFS),
    )


def test_open_dataset_s3_downloads_then_opens(monkeypatch, tiny_nc, tmp_path):
    """s3:// should download via s3fs.get_file to the local cache, then open."""
    captured = {}
    _fake_s3fs(monkeypatch, tiny_nc, captured, tmp_path / "cache")

    with ncio.open_dataset("s3://project-surimi/NetCDF/x.nc") as ds:
        assert "biomass" in ds.data_vars
    assert captured["downloaded"] == "s3://project-surimi/NetCDF/x.nc"
    assert captured["kwargs"]["client_kwargs"]["endpoint_url"] == "https://minio.test"


def test_open_dataset_s3_caches_second_call(monkeypatch, tiny_nc, tmp_path):
    """Second open of the same URI must NOT re-download (cache hit)."""
    captured = {}
    _fake_s3fs(monkeypatch, tiny_nc, captured, tmp_path / "cache")
    with ncio.open_dataset("s3://b/k.nc"):
        pass
    captured["downloaded"] = None  # reset
    with ncio.open_dataset("s3://b/k.nc"):
        pass
    assert captured["downloaded"] is None  # no second download


def test_open_dataset_s3_raises_without_endpoint(monkeypatch):
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with pytest.raises(ncio.NetCDFIOError):
        ncio.open_dataset("s3://bucket/key.nc")


def test_resource_sha256_s3(monkeypatch, tiny_nc, tmp_path):
    captured = {}
    _fake_s3fs(monkeypatch, tiny_nc, captured, tmp_path / "cache")
    expected = hashlib.sha256(open(tiny_nc, "rb").read()).hexdigest()
    assert ncio.resource_sha256("s3://b/k.nc") == expected
