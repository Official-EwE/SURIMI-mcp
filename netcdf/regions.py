"""Regional mask handling.

A region mask is a netcdf file with a 3D `region` variable of shape
(region, lat, lon) containing per-cell weights (0/1 for hard masks; or
area-weighted fractions). Each region has a numeric id and optionally a
name. Masks must align exactly with the target data file's lat/lon grid.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr

from netcdf import io as ncio


class RegionMaskError(Exception):
    """Raised on mask load / alignment failure."""


def load_region_mask(path: str) -> dict[str, Any]:
    """Load a region mask netcdf (local path or s3:// URI).

    Expects a variable `region` with shape (region_id, lat, lon) and a
    coordinate `region_name` or per-region attribute mapping ids -> names.
    """
    try:
        ds = ncio.open_dataset(path)
    except ncio.NetCDFIOError as exc:
        raise RegionMaskError(str(exc)) from exc

    with ds:
        if "region" not in ds:
            raise RegionMaskError("mask file must contain a 'region' variable")
        mask = ds["region"].values
        if mask.ndim != 3:
            raise RegionMaskError(
                f"region mask must be 3D (region, lat, lon), got shape {mask.shape}"
            )
        n_regions = mask.shape[0]

        # Resolve region names: prefer coord `region_name`, else use ids
        if "region_name" in ds.coords:
            names = [_decode(v) for v in ds["region_name"].values]
        elif "region_name" in ds:
            names = [_decode(v) for v in ds["region_name"].values]
        else:
            ids = ds["region_id"].values if "region_id" in ds else range(n_regions)
            names = [f"region_{i}" for i in ids]

        lat = ds["lat"].values if "lat" in ds else None
        lon = ds["lon"].values if "lon" in ds else None

        return {
            "n_regions": int(n_regions),
            "region_names": names,
            "mask": mask,  # ndarray (region, lat, lon)
            "lat": lat,
            "lon": lon,
            "mask_sha256": ncio.resource_sha256(path),
        }


def validate_alignment(data_file: str, mask_file: str) -> dict[str, Any]:
    """Check that the data file's lat/lon grid matches the mask's grid."""
    try:
        d = ncio.open_dataset(data_file)
        m = ncio.open_dataset(mask_file)
    except ncio.NetCDFIOError as exc:
        raise RegionMaskError(str(exc)) from exc

    with d, m:
        mismatches: list[str] = []
        if "lat" in d and "lat" in m:
            if d["lat"].shape != m["lat"].shape or not np.allclose(
                d["lat"].values, m["lat"].values, atol=1e-3
            ):
                mismatches.append("lat")
        else:
            mismatches.append("lat_missing")
        if "lon" in d and "lon" in m:
            if d["lon"].shape != m["lon"].shape or not np.allclose(
                d["lon"].values, m["lon"].values, atol=1e-3
            ):
                mismatches.append("lon")
        else:
            mismatches.append("lon_missing")

        return {"aligned": not mismatches, "mismatches": mismatches}


def _decode(v: Any) -> str:
    if isinstance(v, (bytes, bytearray)):
        return v.decode(errors="replace")
    return str(v)
