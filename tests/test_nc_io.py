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


def test_open_dataset_s3_uses_s3fs(monkeypatch, tiny_nc):
    """s3:// dispatch should build an S3 filesystem from env creds and
    open the object as a file handle. We fake s3fs to return the local
    fixture's bytes so we can assert the dispatch path without a real bucket."""
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://minio.test")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")

    captured = {}

    class _FakeFS:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def open(self, uri, mode="rb"):
            captured["opened"] = uri
            return open(tiny_nc, "rb")

        def exists(self, uri):
            return True

        def cat_file(self, uri):
            return open(tiny_nc, "rb").read()

    import types
    fake_s3fs = types.SimpleNamespace(S3FileSystem=_FakeFS)
    monkeypatch.setitem(__import__("sys").modules, "s3fs", fake_s3fs)

    with ncio.open_dataset("s3://project-surimi/NetCDF/x.nc") as ds:
        assert "biomass" in ds.data_vars
    assert captured["opened"] == "s3://project-surimi/NetCDF/x.nc"
    # endpoint_url must be passed through to the S3 client
    assert captured["kwargs"]["client_kwargs"]["endpoint_url"] == "https://minio.test"


def test_open_dataset_s3_raises_without_endpoint(monkeypatch):
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with pytest.raises(ncio.NetCDFIOError):
        ncio.open_dataset("s3://bucket/key.nc")


def test_resource_sha256_s3(monkeypatch, tiny_nc):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://minio.test")
    expected = hashlib.sha256(open(tiny_nc, "rb").read()).hexdigest()

    class _FakeFS:
        def __init__(self, **kwargs):
            pass

        def cat_file(self, uri):
            return open(tiny_nc, "rb").read()

        def exists(self, uri):
            return True

    import types
    monkeypatch.setitem(
        __import__("sys").modules, "s3fs",
        types.SimpleNamespace(S3FileSystem=_FakeFS),
    )
    assert ncio.resource_sha256("s3://b/k.nc") == expected
