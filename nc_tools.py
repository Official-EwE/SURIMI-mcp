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

from netcdf import analytics, inspect as nc_inspect
from receipts import verify_receipt
from signed_tool import with_receipt


# ---------- Inspection (unsigned) ----------

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

nc_top_regions = with_receipt("nc_top_regions")(analytics.top_regions)
nc_time_series = with_receipt("nc_time_series")(analytics.time_series)
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
