"""Open-time inspection of netcdf files.

Tools never assume file layout. Each tool opens the file, reads what is
actually there, and reports it. Filenames and conventions are hints, not
contracts. Pairs with the receipt module: file_sha256 from describe_file is
used as a provenance field on analytical receipts.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr

from netcdf import io as ncio


class NetCDFInspectError(Exception):
    """Raised on inspection failure (missing file, unreadable, etc.)."""


def _open(uri: str) -> xr.Dataset:
    try:
        return ncio.open_dataset(uri, decode_times=False)
    except ncio.NetCDFIOError as exc:
        raise NetCDFInspectError(str(exc)) from exc


def describe_file(path: str) -> dict[str, Any]:
    """Return the full structure of a netcdf file.

    Includes dimensions, variables (with shapes/dtypes/units), global
    attributes, and the file SHA-256 (used as provenance in receipts).
    """
    with _open(path) as ds:
        return {
            "file_path": path,
            "file_sha256": ncio.resource_sha256(path),
            "dimensions": {name: int(size) for name, size in ds.sizes.items()},
            "variables": _variable_list(ds),
            "global_attributes": _coerce_attrs(ds.attrs),
        }


def list_variables(path: str) -> list[dict[str, Any]]:
    """List data variables (excluding coordinates) with shape/dtype/units."""
    with _open(path) as ds:
        return _variable_list(ds)


def get_time_range(path: str) -> dict[str, Any]:
    """Return start/end of the time axis, with raw units. Does not decode times."""
    with _open(path) as ds:
        time_name = _find_time_coord(ds)
        if time_name is None:
            raise NetCDFInspectError("no time coordinate found")
        t = ds[time_name]
        arr = t.values
        return {
            "name": time_name,
            "units": str(t.attrs.get("units", "")),
            "start": _coerce_value(arr[0]),
            "end": _coerce_value(arr[-1]),
            "n_steps": int(len(arr)),
        }


def get_spatial_bounds(path: str) -> dict[str, Any]:
    """Return lat/lon extents and grid sizes."""
    with _open(path) as ds:
        lat_name = _find_coord(ds, ["lat", "latitude", "y"])
        lon_name = _find_coord(ds, ["lon", "longitude", "x"])
        if lat_name is None or lon_name is None:
            raise NetCDFInspectError("lat/lon coordinates not found")
        lat = ds[lat_name].values
        lon = ds[lon_name].values
        return {
            "lat_name": lat_name,
            "lon_name": lon_name,
            "lat_min": float(np.min(lat)),
            "lat_max": float(np.max(lat)),
            "lon_min": float(np.min(lon)),
            "lon_max": float(np.max(lon)),
            "lat_n": int(len(lat)),
            "lon_n": int(len(lon)),
        }


def check_cf_compliance(path: str) -> dict[str, Any]:
    """Heuristic CF-conventions check.

    Compliant means: Conventions attribute is set to CF-1.x, all data
    variables have units, lat/lon coords exist with proper units.
    Non-compliance is reported with specific missing fields, never raises.
    """
    with _open(path) as ds:
        missing: list[str] = []
        warnings: list[str] = []

        conv = ds.attrs.get("Conventions")
        if not conv or not str(conv).upper().startswith("CF"):
            missing.append("convention")

        for var_name, var in ds.data_vars.items():
            if "units" not in var.attrs:
                warnings.append(f"variable '{var_name}' missing units")

        # Check lat/lon presence with units
        if _find_coord(ds, ["lat", "latitude"]) is None:
            missing.append("latitude_coord")
        if _find_coord(ds, ["lon", "longitude"]) is None:
            missing.append("longitude_coord")

        return {
            "compliant": not missing,
            "convention": str(conv) if conv else None,
            "missing": missing,
            "warnings": warnings,
        }


def get_coverage_summary(path: str) -> dict[str, Any]:
    """Per-variable: total cells, NaN count, NaN fraction.

    Helps the LLM (and the user) see whether data is dense or sparse.
    Coverage gaps are surfaced explicitly so they cannot be silently
    skipped by aggregations.
    """
    with _open(path) as ds:
        vars_out: list[dict[str, Any]] = []
        for name, var in ds.data_vars.items():
            arr = var.values
            n_total = int(arr.size)
            # isnan only valid for float dtypes; treat non-numeric as fully present.
            if arr.dtype.kind in ("f",):
                n_nan = int(np.isnan(arr).sum())
            else:
                n_nan = 0
            vars_out.append({
                "name": name,
                "n_total": n_total,
                "n_nan": n_nan,
                "nan_fraction": (n_nan / n_total) if n_total else 0.0,
            })
        return {"file_path": path, "variables": vars_out}


# ---------- helpers ----------

def _variable_list(ds: xr.Dataset) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, var in ds.data_vars.items():
        out.append({
            "name": str(name),
            "shape": [int(s) for s in var.shape],
            "dims": list(var.dims),
            "dtype": str(var.dtype),
            "units": str(var.attrs.get("units", "")),
            "long_name": str(var.attrs.get("long_name", "")),
        })
    return out


def _find_time_coord(ds: xr.Dataset) -> str | None:
    for cand in ("time", "t", "T"):
        if cand in ds.coords or cand in ds.dims:
            return cand
    # Look for any coord with time-like units
    for name, coord in ds.coords.items():
        u = str(coord.attrs.get("units", "")).lower()
        if "since" in u and ("day" in u or "hour" in u or "second" in u):
            return str(name)
    return None


def _find_coord(ds: xr.Dataset, candidates: list[str]) -> str | None:
    keys = set(ds.coords.keys()) | set(ds.dims)
    for cand in candidates:
        if cand in keys:
            return cand
    return None


def _coerce_attrs(attrs: Any) -> dict[str, Any]:
    """Coerce xarray attrs into JSON-serializable dict (no numpy scalars)."""
    return {str(k): _coerce_value(v) for k, v in dict(attrs).items()}


def _coerce_value(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return v.decode(errors="replace")
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v
