"""Tests for analytical primitives.

The fixture `tiny_nc` produces deterministic biomass values:
biomass[t, lat_idx, lon_idx] = t*100 + lat_idx*10 + lon_idx

For t=0 only:
  biomass[0, :, :] =
    [[ 0,  1,  2,  3],
     [10, 11, 12, 13],
     [20, 21, 22, 23]]

`tiny_region_mask` splits the lon axis:
  Region "West" (region_id=1): lon indices 0, 1
  Region "East" (region_id=2): lon indices 2, 3

At t=0, unweighted mean per region:
  West = mean([0,1, 10,11, 20,21]) = 63/6  = 10.5
  East = mean([2,3, 12,13, 22,23]) = 75/6  = 12.5

Averaged across 4 timesteps the means grow by 150 each (each step adds 100
per cell, so mean adds 100 too; t=0..3 mean offset = 150).
Expected over all 4 timesteps:
  West mean = 10.5 + 150 = 160.5
  East mean = 12.5 + 150 = 162.5
"""
from __future__ import annotations

import pytest

from netcdf.analytics import (
    AnalyticsError,
    compare_periods,
    nc_trend,
    time_series,
    top_regions,
)


# ---------- top_regions ----------

def test_top_regions_returns_correct_order_unweighted(tiny_nc, tiny_region_mask):
    out = top_regions(
        file=tiny_nc,
        var="biomass",
        n=2,
        agg="mean",
        mask_file=tiny_region_mask,
    )
    assert len(out["result"]) == 2
    # East has slightly higher mean (lon indices 2,3 vs 0,1)
    assert out["result"][0]["region"] == "East"
    assert out["result"][0]["value"] == pytest.approx(162.5, rel=1e-3)
    assert out["result"][1]["region"] == "West"
    assert out["result"][1]["value"] == pytest.approx(160.5, rel=1e-3)


def test_top_regions_respects_n(tiny_nc, tiny_region_mask):
    out = top_regions(
        file=tiny_nc, var="biomass", n=1, agg="mean", mask_file=tiny_region_mask,
    )
    assert len(out["result"]) == 1
    assert out["result"][0]["region"] == "East"


def test_top_regions_provenance_includes_file_and_mask_sha(tiny_nc, tiny_region_mask):
    out = top_regions(
        file=tiny_nc, var="biomass", n=2, agg="mean", mask_file=tiny_region_mask,
    )
    p = out["provenance"]
    assert len(p["file_sha256"]) == 64
    assert len(p["mask_sha256"]) == 64
    assert p["var"] == "biomass"
    assert p["agg"] == "mean"


def test_top_regions_includes_coverage(tiny_nc, tiny_region_mask):
    out = top_regions(
        file=tiny_nc, var="biomass", n=2, agg="mean", mask_file=tiny_region_mask,
    )
    cov = out["coverage"]
    assert cov["nan_fraction"] == pytest.approx(0.0)
    assert cov["n_regions_evaluated"] == 2


def test_top_regions_raises_on_unknown_variable(tiny_nc, tiny_region_mask):
    with pytest.raises(AnalyticsError):
        top_regions(
            file=tiny_nc, var="nonexistent", n=2,
            agg="mean", mask_file=tiny_region_mask,
        )


def test_top_regions_raises_on_unknown_agg(tiny_nc, tiny_region_mask):
    with pytest.raises(AnalyticsError):
        top_regions(
            file=tiny_nc, var="biomass", n=2,
            agg="bogus", mask_file=tiny_region_mask,
        )


def test_top_regions_supports_sum_aggregation(tiny_nc, tiny_region_mask):
    """sum should add all cells * timesteps in each region."""
    out = top_regions(
        file=tiny_nc, var="biomass", n=2, agg="sum", mask_file=tiny_region_mask,
    )
    # Per t, West sum = 0+1 +10+11 +20+21 = 63; East = 2+3+12+13+22+23 = 75
    # Over 4 timesteps: West adds (per step) 600 cells*increment, but
    # simpler: sum over t of sum over region = sum_region_t = 4 * region_sum
    # plus the t-offset contribution: per region 6 cells, offset (0+100+200+300)*6 = 3600
    # West: 4*63 + 3600 = 252 + 3600 = 3852
    # East: 4*75 + 3600 = 300 + 3600 = 3900
    res = {r["region"]: r["value"] for r in out["result"]}
    assert res["East"] == pytest.approx(3900.0, rel=1e-3)
    assert res["West"] == pytest.approx(3852.0, rel=1e-3)


# ---------- time_series ----------

def test_time_series_returns_one_point_per_step(tiny_nc, tiny_region_mask):
    out = time_series(
        file=tiny_nc, var="biomass", region="East",
        agg_per_step="mean", mask_file=tiny_region_mask,
    )
    assert len(out["points"]) == 4
    # East at t=0: mean of [2,3,12,13,22,23] = 12.5
    # Each subsequent step adds 100
    expected = [12.5, 112.5, 212.5, 312.5]
    for got, exp in zip(out["points"], expected):
        assert got["value"] == pytest.approx(exp, rel=1e-3)


def test_time_series_provenance_records_region(tiny_nc, tiny_region_mask):
    out = time_series(
        file=tiny_nc, var="biomass", region="East",
        agg_per_step="mean", mask_file=tiny_region_mask,
    )
    assert out["provenance"]["region"] == "East"


def test_time_series_raises_on_unknown_region(tiny_nc, tiny_region_mask):
    with pytest.raises(AnalyticsError):
        time_series(
            file=tiny_nc, var="biomass", region="Atlantis",
            agg_per_step="mean", mask_file=tiny_region_mask,
        )


# ---------- compare_periods ----------

def test_compare_periods_returns_diff_per_region(tiny_nc, tiny_region_mask):
    """Period A: steps 0..1, Period B: steps 2..3."""
    out = compare_periods(
        file=tiny_nc, var="biomass",
        period_a=(0, 1), period_b=(2, 3),
        mask_file=tiny_region_mask, op="diff",
    )
    # Period A mean per region: (region_offset + 50)
    # Period B mean per region: (region_offset + 250)
    # diff = 200 for both
    diffs = {r["region"]: r["value"] for r in out["result"]}
    assert diffs["West"] == pytest.approx(200.0, rel=1e-3)
    assert diffs["East"] == pytest.approx(200.0, rel=1e-3)


def test_compare_periods_supports_ratio(tiny_nc, tiny_region_mask):
    out = compare_periods(
        file=tiny_nc, var="biomass",
        period_a=(0, 1), period_b=(2, 3),
        mask_file=tiny_region_mask, op="ratio",
    )
    for r in out["result"]:
        assert r["value"] > 1.0  # period_b > period_a


# ---------- nc_trend (Mann-Kendall) ----------

def test_trend_returns_slope_and_pvalue(tiny_nc, tiny_region_mask):
    out = nc_trend(
        file=tiny_nc, var="biomass", region="East",
        mask_file=tiny_region_mask,
    )
    # Monotonically increasing, so slope > 0, p-value low
    assert out["slope"] > 0
    assert out["p_value"] < 0.5
    assert "direction" in out
    assert out["direction"] in ("increasing", "decreasing", "no_trend")


def test_trend_provenance_includes_method(tiny_nc, tiny_region_mask):
    out = nc_trend(
        file=tiny_nc, var="biomass", region="East",
        mask_file=tiny_region_mask,
    )
    assert out["provenance"]["method"] == "mann_kendall"
