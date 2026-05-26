"""Tests for the netcdf inspection layer.

These tools mirror dogukanteber/netcdf-mcp's metadata tools but stay scoped to
what surimi-mcp's LLM workflow actually needs: file structure, variable
inventory, time/space bounds, CF-compliance check, NaN/coverage summary.
"""
from __future__ import annotations

import pytest

from netcdf.inspect import (
    NetCDFInspectError,
    check_cf_compliance,
    describe_file,
    get_coverage_summary,
    get_spatial_bounds,
    get_time_range,
    list_variables,
)


# ---------- describe_file ----------

def test_describe_file_returns_structure_dict(tiny_nc):
    out = describe_file(tiny_nc)
    assert "dimensions" in out
    assert "variables" in out
    assert "global_attributes" in out
    assert "file_path" in out
    assert "file_sha256" in out


def test_describe_file_has_correct_dimension_sizes(tiny_nc):
    out = describe_file(tiny_nc)
    assert out["dimensions"]["time"] == 4
    assert out["dimensions"]["lat"] == 3
    assert out["dimensions"]["lon"] == 4


def test_describe_file_lists_data_variables(tiny_nc):
    out = describe_file(tiny_nc)
    var_names = [v["name"] for v in out["variables"]]
    assert "biomass" in var_names


def test_describe_file_includes_global_attributes(tiny_nc):
    out = describe_file(tiny_nc)
    assert out["global_attributes"].get("Conventions") == "CF-1.8"


def test_describe_file_sha256_is_64_hex_chars(tiny_nc):
    out = describe_file(tiny_nc)
    assert len(out["file_sha256"]) == 64
    assert all(c in "0123456789abcdef" for c in out["file_sha256"])


def test_describe_file_raises_on_missing_file(tmp_path):
    with pytest.raises(NetCDFInspectError):
        describe_file(str(tmp_path / "nope.nc"))


# ---------- list_variables ----------

def test_list_variables_returns_name_shape_dtype_units(tiny_nc):
    vars_ = list_variables(tiny_nc)
    biomass = next(v for v in vars_ if v["name"] == "biomass")
    assert biomass["shape"] == [4, 3, 4]
    assert biomass["dtype"].startswith("float32")
    assert biomass["units"] == "kg m-2"
    assert biomass["long_name"] == "Biomass density"


def test_list_variables_excludes_coordinate_dims(tiny_nc):
    """Coordinates (time, lat, lon) should NOT be listed as data variables."""
    vars_ = list_variables(tiny_nc)
    names = {v["name"] for v in vars_}
    assert "biomass" in names
    assert "time" not in names
    assert "lat" not in names
    assert "lon" not in names


# ---------- get_time_range ----------

def test_get_time_range_returns_start_and_end_iso(tiny_nc):
    out = get_time_range(tiny_nc)
    assert "start" in out
    assert "end" in out
    assert out["n_steps"] == 4


def test_get_time_range_includes_units(tiny_nc):
    out = get_time_range(tiny_nc)
    assert "days since 2010" in out["units"]


# ---------- get_spatial_bounds ----------

def test_get_spatial_bounds_returns_lat_lon_extents(tiny_nc):
    out = get_spatial_bounds(tiny_nc)
    assert out["lat_min"] == pytest.approx(-30.0)
    assert out["lat_max"] == pytest.approx(30.0)
    assert out["lon_min"] == pytest.approx(-180.0)
    assert out["lon_max"] < 180.0  # endpoint=False
    assert out["lat_n"] == 3
    assert out["lon_n"] == 4


# ---------- check_cf_compliance ----------

def test_check_cf_compliance_passes_on_cf_file(tiny_nc):
    out = check_cf_compliance(tiny_nc)
    assert out["compliant"] is True
    assert out["convention"] == "CF-1.8"


def test_check_cf_compliance_flags_missing_conventions(tiny_nc_no_cf):
    out = check_cf_compliance(tiny_nc_no_cf)
    assert out["compliant"] is False
    assert "convention" in out["missing"]


def test_check_cf_compliance_reports_missing_units(tiny_nc_no_cf):
    out = check_cf_compliance(tiny_nc_no_cf)
    # tiny_nc_no_cf has no units on its variable
    assert any("units" in m for m in out["warnings"])


# ---------- get_coverage_summary ----------

def test_get_coverage_summary_returns_nan_fraction_per_variable(tiny_nc):
    out = get_coverage_summary(tiny_nc)
    biomass = next(v for v in out["variables"] if v["name"] == "biomass")
    assert biomass["nan_fraction"] == 0.0
    assert biomass["n_total"] == 4 * 3 * 4


def test_get_coverage_summary_detects_actual_nans(tmp_path):
    """Synthesize a file with explicit NaNs and check fraction."""
    import numpy as np
    import xarray as xr

    arr = np.array([[1.0, 2.0], [np.nan, 4.0]], dtype="float32")
    ds = xr.Dataset(
        data_vars={"v": (("y", "x"), arr)},
        coords={"y": [0, 1], "x": [0, 1]},
    )
    p = tmp_path / "nans.nc"
    ds.to_netcdf(p)
    out = get_coverage_summary(str(p))
    v = next(x for x in out["variables"] if x["name"] == "v")
    assert v["nan_fraction"] == pytest.approx(0.25)
    assert v["n_nan"] == 1


def test_get_coverage_summary_handles_non_float_dtypes(tmp_path):
    """Integer and object dtype variables should not raise; n_nan must be 0."""
    import numpy as np
    import xarray as xr

    int_arr = np.array([[1, 2], [3, 4]], dtype="int32")
    str_arr = np.array(["a", "b", "c"], dtype="<U4")
    ds = xr.Dataset(
        data_vars={
            "counts": (("y", "x"), int_arr),
            "labels": (("k",), str_arr),
        },
        coords={"y": [0, 1], "x": [0, 1], "k": [0, 1, 2]},
    )
    p = tmp_path / "mixed.nc"
    ds.to_netcdf(p)
    out = get_coverage_summary(str(p))
    counts = next(v for v in out["variables"] if v["name"] == "counts")
    labels = next(v for v in out["variables"] if v["name"] == "labels")
    assert counts["n_nan"] == 0
    assert labels["n_nan"] == 0
