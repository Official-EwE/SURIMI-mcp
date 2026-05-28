"""Tests for the regional mask module."""
from __future__ import annotations

import numpy as np
import pytest

from netcdf.regions import (
    RegionMaskError,
    load_region_mask,
    validate_alignment,
)


def test_load_region_mask_returns_mask_and_names(tiny_region_mask):
    mask = load_region_mask(tiny_region_mask)
    assert mask["n_regions"] == 2
    assert set(mask["region_names"]) == {"West", "East"}
    assert mask["mask"].shape == (2, 3, 4)  # (region, lat, lon)


def test_load_region_mask_includes_sha256(tiny_region_mask):
    mask = load_region_mask(tiny_region_mask)
    assert len(mask["mask_sha256"]) == 64


def test_load_region_mask_raises_on_missing_file(tmp_path):
    with pytest.raises(RegionMaskError):
        load_region_mask(str(tmp_path / "nope.nc"))


def test_validate_alignment_passes_when_grids_match(tiny_nc, tiny_region_mask):
    """When data and mask share the lat/lon grid, alignment passes."""
    out = validate_alignment(tiny_nc, tiny_region_mask)
    assert out["aligned"] is True


def test_validate_alignment_fails_when_grids_differ(tiny_nc, tmp_path):
    """A mask with different lat/lon should fail alignment."""
    import xarray as xr
    arr = np.zeros((1, 5, 5), dtype="float32")
    ds = xr.Dataset(
        data_vars={"region": (("region_id", "lat", "lon"), arr)},
        coords={"region_id": [1], "lat": np.linspace(0, 10, 5),
                "lon": np.linspace(0, 10, 5)},
    )
    p = tmp_path / "wrongmask.nc"
    ds.to_netcdf(p)
    out = validate_alignment(tiny_nc, str(p))
    assert out["aligned"] is False
    assert "lat" in out["mismatches"] or "lon" in out["mismatches"]
