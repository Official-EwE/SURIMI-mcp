"""Tests for netcdf discovery: list the catalog so the LLM can find data
from a plain-English question instead of being handed s3:// paths."""
from __future__ import annotations

import pytest

from netcdf import io as ncio
from netcdf.discovery import classify, list_netcdf_files


# ---------- classify ----------

def test_classify_data_file():
    assert classify("s3://b/NetCDF/ecoocean_..._bd30cm_global_monthly_1961_2015.nc") == "data"


def test_classify_mask_file():
    assert classify("s3://b/NetCDF/ar6_ocean_mask_0.25deg.nc") == "mask"


def test_classify_non_netcdf_is_other():
    assert classify("s3://b/NetCDF/.keep") == "other"
    assert classify("s3://b/NetCDF/readme.txt") == "other"


# ---------- io.list_objects (local) ----------

def test_list_objects_local_dir(tmp_path):
    (tmp_path / "a.nc").write_bytes(b"x")
    (tmp_path / "b_mask.nc").write_bytes(b"yy")
    (tmp_path / "ignore.txt").write_bytes(b"z")
    objs = ncio.list_objects(str(tmp_path))
    uris = sorted(o["uri"].rsplit("/", 1)[-1] for o in objs)
    assert uris == ["a.nc", "b_mask.nc", "ignore.txt"]
    a = next(o for o in objs if o["uri"].endswith("a.nc"))
    assert a["size"] == 1


def test_list_objects_local_missing_dir(tmp_path):
    with pytest.raises(ncio.NetCDFIOError):
        ncio.list_objects(str(tmp_path / "nope"))


# ---------- io.list_objects (s3, mocked) ----------

def test_list_objects_s3(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://minio.test")
    import types

    class _FakeFS:
        def __init__(self, **kw):
            pass

        def ls(self, path, detail=True):
            assert path == "project-surimi/NetCDF"
            return [
                {"name": "project-surimi/NetCDF/eco_bd30cm.nc", "size": 500, "type": "file"},
                {"name": "project-surimi/NetCDF/ar6_ocean_mask.nc", "size": 60, "type": "file"},
                {"name": "project-surimi/NetCDF/sub", "size": 0, "type": "directory"},
            ]

    monkeypatch.setitem(__import__("sys").modules, "s3fs",
                        types.SimpleNamespace(S3FileSystem=_FakeFS))
    objs = ncio.list_objects("s3://project-surimi/NetCDF/")
    uris = sorted(o["uri"] for o in objs)
    assert uris == [
        "s3://project-surimi/NetCDF/ar6_ocean_mask.nc",
        "s3://project-surimi/NetCDF/eco_bd30cm.nc",
    ]  # the directory entry is excluded


# ---------- list_netcdf_files ----------

def test_list_netcdf_files_classifies(tmp_path):
    (tmp_path / "eco_bd30cm.nc").write_bytes(b"x")
    (tmp_path / "ar6_ocean_mask.nc").write_bytes(b"y")
    (tmp_path / ".keep").write_bytes(b"")
    out = list_netcdf_files(str(tmp_path))
    assert out["count"] == 3
    kinds = {f["uri"].rsplit("/", 1)[-1]: f["kind"] for f in out["files"]}
    assert kinds["eco_bd30cm.nc"] == "data"
    assert kinds["ar6_ocean_mask.nc"] == "mask"
    assert kinds[".keep"] == "other"


def test_list_netcdf_files_records_prefix(tmp_path):
    out = list_netcdf_files(str(tmp_path))
    assert out["prefix"] == str(tmp_path)
    assert out["files"] == []
    assert out["count"] == 0


# ---------- nc_tools.nc_list_files ----------

def test_nc_list_files_tool_default_prefix(monkeypatch, tmp_path):
    # point the default prefix at a local dir via env
    (tmp_path / "eco_bd30cm.nc").write_bytes(b"x")
    monkeypatch.setenv("SURIMI_NETCDF_PREFIX", str(tmp_path))
    import importlib
    import nc_tools
    importlib.reload(nc_tools)
    out = nc_tools.nc_list_files()
    assert out["count"] == 1
    assert out["files"][0]["kind"] == "data"


def test_nc_list_files_registered():
    import nc_tools
    assert "nc_list_files" in nc_tools.TOOLS
