"""Tests for the nc_tools module that bundles the MCP-exposed functions
with receipt-wrapping baked in. server.py imports from here and registers
each as @mcp.tool()."""
from __future__ import annotations

import pytest

import nc_tools
from receipts import verify_receipt


SECRET = b"unit-test-secret"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("SURIMI_RECEIPT_SECRET", SECRET.decode())


# ---------- inspection tools (no receipts) ----------

def test_nc_describe_file_exposed_and_works(tiny_nc):
    out = nc_tools.nc_describe_file(tiny_nc)
    assert "dimensions" in out
    assert out["dimensions"]["time"] == 4


def test_nc_list_variables_exposed(tiny_nc):
    out = nc_tools.nc_list_variables(tiny_nc)
    assert any(v["name"] == "biomass" for v in out)


def test_nc_get_time_range_exposed(tiny_nc):
    out = nc_tools.nc_get_time_range(tiny_nc)
    assert out["n_steps"] == 4


def test_nc_get_spatial_bounds_exposed(tiny_nc):
    out = nc_tools.nc_get_spatial_bounds(tiny_nc)
    assert out["lat_n"] == 3


def test_nc_check_cf_compliance_exposed(tiny_nc):
    out = nc_tools.nc_check_cf_compliance(tiny_nc)
    assert out["compliant"] is True


def test_nc_get_coverage_summary_exposed(tiny_nc):
    out = nc_tools.nc_get_coverage_summary(tiny_nc)
    assert any(v["name"] == "biomass" for v in out["variables"])


# ---------- analytical tools (with receipts) ----------

def test_nc_top_regions_returns_value_and_receipt(tiny_nc, tiny_region_mask):
    out = nc_tools.nc_top_regions(
        file=tiny_nc, var="biomass", n=2, agg="mean", mask_file=tiny_region_mask,
    )
    assert "value" in out
    assert "receipt" in out
    assert out["receipt"]["tool_id"] == "nc_top_regions"


def test_nc_top_regions_receipt_verifies(tiny_nc, tiny_region_mask):
    out = nc_tools.nc_top_regions(
        file=tiny_nc, var="biomass", n=2, agg="mean", mask_file=tiny_region_mask,
    )
    v = verify_receipt(out["receipt"], secret=SECRET)
    assert v["verified"] is True


def test_nc_time_series_signed(tiny_nc, tiny_region_mask):
    out = nc_tools.nc_time_series(
        file=tiny_nc, var="biomass", region="East",
        agg_per_step="mean", mask_file=tiny_region_mask,
    )
    assert out["receipt"]["tool_id"] == "nc_time_series"
    v = verify_receipt(out["receipt"], secret=SECRET)
    assert v["verified"] is True


def test_nc_compare_periods_signed(tiny_nc, tiny_region_mask):
    out = nc_tools.nc_compare_periods(
        file=tiny_nc, var="biomass",
        period_a=(0, 1), period_b=(2, 3),
        mask_file=tiny_region_mask, op="diff",
    )
    assert out["receipt"]["tool_id"] == "nc_compare_periods"


def test_nc_trend_signed(tiny_nc, tiny_region_mask):
    out = nc_tools.nc_trend(
        file=tiny_nc, var="biomass", region="East",
        mask_file=tiny_region_mask,
    )
    assert out["receipt"]["tool_id"] == "nc_trend"


# ---------- verify tool ----------

def test_nc_verify_accepts_good_receipt(tiny_nc, tiny_region_mask):
    out = nc_tools.nc_top_regions(
        file=tiny_nc, var="biomass", n=2, agg="mean", mask_file=tiny_region_mask,
    )
    v = nc_tools.nc_verify(out["receipt"])
    assert v["verified"] is True


def test_nc_verify_rejects_tampered_receipt(tiny_nc, tiny_region_mask):
    out = nc_tools.nc_top_regions(
        file=tiny_nc, var="biomass", n=2, agg="mean", mask_file=tiny_region_mask,
    )
    out["receipt"]["output_value"] = "TAMPERED"
    v = nc_tools.nc_verify(out["receipt"])
    assert v["verified"] is False


# ---------- registry ----------

def test_all_tools_listed_in_registry():
    """nc_tools should expose a TOOLS list naming every callable for server.py
    to register via @mcp.tool()."""
    expected = {
        "nc_describe_file", "nc_list_variables", "nc_get_time_range",
        "nc_get_spatial_bounds", "nc_check_cf_compliance",
        "nc_get_coverage_summary",
        "nc_top_regions", "nc_time_series", "nc_compare_periods", "nc_trend",
        "nc_verify",
    }
    assert set(nc_tools.TOOLS) == expected
