"""MCP-exposed netcdf tools.

Inspection tools are unsigned (they describe state, do not produce numeric
answers). Analytical primitives are wrapped with @with_receipt so every
numeric output carries an HMAC-signed receipt. The nc_verify tool replays
a receipt's signature check.

server.py imports TOOLS and registers each name via @mcp.tool().
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np

from netcdf import analytics, discovery, inspect as nc_inspect, regions as nc_regions
from receipts import verify_receipt
from signed_tool import with_receipt


# Default catalog prefix the discovery tool lists. Override with env so a
# fresh deploy points at its own MinIO bucket without code changes.
DEFAULT_NETCDF_PREFIX = os.environ.get(
    "SURIMI_NETCDF_PREFIX", "s3://project-surimi/NetCDF/"
)


# ---------- Discovery (unsigned) ----------

def nc_list_files(prefix: str | None = None) -> dict[str, Any]:
    """List the netcdf catalog so you can find a file from a plain question.

    Returns {prefix, count, files:[{uri, size, kind}]} where kind is
    'data', 'mask', or 'other'. Call this FIRST when asked about ocean/
    biomass/gridded data, then nc_describe_file on a chosen 'data' file to
    see its variables, then an analytical tool (e.g. nc_top_regions) with a
    matching 'mask' file. Defaults to the SURIMI NetCDF bucket.
    """
    return discovery.list_netcdf_files(prefix or DEFAULT_NETCDF_PREFIX)


# ---------- Inspection (unsigned) ----------

def nc_list_regions(mask_file: str) -> dict[str, Any]:
    """List the named regions in a mask file so you can pick a region by name.

    Returns {mask_file, n_regions, regions:[{name, n_cells}]}. Call this BEFORE
    nc_time_series or nc_trend (which take a region NAME), and to know which
    regions nc_top_regions will rank. Do NOT guess region names or call
    nc_top_regions on the mask itself to discover them.
    """
    mask = nc_regions.load_region_mask(mask_file)
    regions = [
        {"name": name, "n_cells": int(np.sum(mask["mask"][i] > 0))}
        for i, name in enumerate(mask["region_names"])
    ]
    return {
        "mask_file": mask_file,
        "n_regions": mask["n_regions"],
        "regions": regions,
    }


def nc_describe_file(path: str) -> dict[str, Any]:
    """Return the full structure of a netcdf file (dims, vars, attrs, sha256)."""
    return nc_inspect.describe_file(path)


def nc_list_variables(path: str) -> list[dict[str, Any]]:
    """List data variables in a netcdf file with shapes, dtypes, units."""
    return nc_inspect.list_variables(path)


def nc_get_time_range(path: str) -> dict[str, Any]:
    """Return start/end of the time axis (raw values, plus raw units)."""
    return nc_inspect.get_time_range(path)


def nc_get_spatial_bounds(path: str) -> dict[str, Any]:
    """Return lat/lon extents and grid sizes."""
    return nc_inspect.get_spatial_bounds(path)


def nc_check_cf_compliance(path: str) -> dict[str, Any]:
    """Check CF-conventions compliance: Conventions attr, units, lat/lon."""
    return nc_inspect.check_cf_compliance(path)


def nc_get_coverage_summary(path: str) -> dict[str, Any]:
    """Per-variable NaN counts and fraction."""
    return nc_inspect.get_coverage_summary(path)


# ---------- Analytical (signed) ----------

def _nc_time_series_cube(
    file: str,
    var: str,
    region: str,
    agg_per_step: str,
    mask_file: str,
) -> dict[str, Any]:
    """Time series of `var` within one region, returned as a compact cube slice.

    Returns a `summary` (n_points, n_valid, value_start/end/min/max/mean,
    slope_per_step, direction) and `by_year` (one pivotable row per calendar
    year: {year, value, n_steps}) plus provenance. Present the summary and the
    by_year rows (a small table or chart); cite the single receipt for the whole
    block. The raw per-step series is intentionally NOT returned -- a global file
    has hundreds of monthly steps and enumerating them floods the reply. For
    "is it increasing/decreasing" or "what is the trend" use nc_trend (it adds a
    significance test and reads the full series internally).
    """
    result = analytics.time_series(
        file=file, var=var, region=region,
        agg_per_step=agg_per_step, mask_file=mask_file,
    )
    return {k: v for k, v in result.items() if k != "points"}


nc_top_regions = with_receipt("nc_top_regions")(analytics.top_regions)
nc_time_series = with_receipt("nc_time_series")(_nc_time_series_cube)
nc_compare_periods = with_receipt("nc_compare_periods")(analytics.compare_periods)
nc_trend = with_receipt("nc_trend")(analytics.nc_trend)


# ---------- Verify ----------

def nc_verify(receipt: dict[str, Any]) -> dict[str, Any]:
    """Verify a signed receipt against the server secret.

    Returns {verified: bool, reason: str}. Never raises on signature
    mismatch.
    """
    raw = os.environ.get("SURIMI_RECEIPT_SECRET", "")
    if not raw:
        return {"verified": False, "reason": "secret_not_configured"}
    return verify_receipt(receipt, secret=raw.encode("utf-8"))


# ---------- Registry ----------

TOOLS = [
    "nc_list_files",
    "nc_list_regions",
    "nc_describe_file",
    "nc_list_variables",
    "nc_get_time_range",
    "nc_get_spatial_bounds",
    "nc_check_cf_compliance",
    "nc_get_coverage_summary",
    "nc_top_regions",
    "nc_time_series",
    "nc_compare_periods",
    "nc_trend",
    "nc_verify",
]
