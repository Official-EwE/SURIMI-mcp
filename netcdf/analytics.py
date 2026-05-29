"""Deterministic analytical primitives for netcdf data.

Each primitive is a single tool that:
1. Opens the file deterministically
2. Applies the region mask
3. Aggregates server-side (LLM never iterates)
4. Returns the result with provenance + coverage

Provenance is wrapped by the receipts module at the MCP tool layer.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import xarray as xr

from netcdf import io as ncio
from netcdf.regions import RegionMaskError, load_region_mask

_log = logging.getLogger(__name__)


class AnalyticsError(Exception):
    """Raised on primitive execution failure."""


_VALID_AGGS = {"mean", "sum", "max", "min"}


def _file_sha256(path: str) -> str:
    try:
        return ncio.resource_sha256(path)
    except ncio.NetCDFIOError as exc:
        raise AnalyticsError(str(exc)) from exc


def _open(path: str) -> xr.Dataset:
    try:
        return ncio.open_dataset(path, decode_times=False)
    except ncio.NetCDFIOError as exc:
        raise AnalyticsError(str(exc)) from exc


def _calendar_years(decoded: np.ndarray) -> np.ndarray:
    """Calendar year per timestep, robust to non-standard calendars.

    decode_cf_datetime returns datetime64[ns] for standard/proleptic_gregorian
    calendars (and dates within the ~1678-2262 range), but an object array of
    cftime objects for noleap/365_day/360_day/etc. The old
    `.astype("datetime64[Y]")` path silently produced WRONG years for cftime
    arrays (e.g. a 360_day axis read as 2014-2015 instead of 2009-2010), which
    made year filtering select the wrong/empty slice. cftime objects expose a
    correct `.year`, so use that for object arrays.
    """
    decoded = np.asarray(decoded)
    if decoded.dtype == object:
        try:
            return np.array(
                [d.year for d in decoded.ravel()]
            ).reshape(decoded.shape)
        except AttributeError as exc:
            raise AnalyticsError(
                f"could not extract calendar year from decoded time axis: {exc}"
            ) from exc
    return decoded.astype("datetime64[Y]").astype(int) + 1970


def _find_time_name(ds: xr.Dataset) -> str | None:
    """Name of the dataset's time coordinate/dimension, or None if absent."""
    for cand in ("time", "t", "T"):
        if cand in ds.coords or cand in ds.dims:
            return cand
    return None


def _decode_years(ds: xr.Dataset) -> np.ndarray | None:
    """Calendar year per timestep for the dataset's time axis.

    Returns None if there is no time coordinate or it lacks CF `units` (so the
    caller falls back to no rollup). Reuses the same CF decoding as the year
    filter so noleap/360_day calendars resolve to correct years.
    """
    tname = _find_time_name(ds)
    if tname is None:
        return None
    t = ds[tname]
    units = t.attrs.get("units")
    if not units:
        return None
    calendar = t.attrs.get("calendar", "standard")
    try:
        decoded = xr.coding.times.decode_cf_datetime(t.values, units, calendar)
    except Exception as exc:
        # Graceful fallback to no rollup, but make the cause observable.
        _log.warning("could not decode time axis for year rollup: %s", exc)
        return None
    return _calendar_years(decoded)


def _time_indices_for_year(ds: xr.Dataset, year: int) -> np.ndarray:
    """Indices along the time axis whose decoded calendar year == year.

    Dataset is opened with decode_times=False, so we decode the raw time
    coordinate via CF units here (lazy enough; the time axis is small).
    """
    tname = _find_time_name(ds)
    if tname is None:
        raise AnalyticsError("no time coordinate to filter by year")
    t = ds[tname]
    units = t.attrs.get("units")
    if not units:
        raise AnalyticsError(f"time coord '{tname}' has no units; cannot filter by year")
    calendar = t.attrs.get("calendar", "standard")
    try:
        decoded = xr.coding.times.decode_cf_datetime(t.values, units, calendar)
    except Exception as exc:
        raise AnalyticsError(f"could not decode time axis: {exc}") from exc
    years = _calendar_years(decoded)
    idx = np.where(years == year)[0]
    if idx.size == 0:
        raise AnalyticsError(
            f"year {year} not present in time axis (range "
            f"{int(years.min())}-{int(years.max())})"
        )
    return idx


def _series_summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact descriptive summary of a time series.

    A raw 240-point series fed back to the LLM frequently produced NO final
    answer (the model never reduced it). This pre-reduces the series so the
    model can always state start/end/min/max/mean + a descriptive slope without
    iterating points. NaN steps (real data gaps) are excluded; if every step is
    missing, only the counts are returned (no value_* fields, never raises).
    """
    n_points = len(points)
    vals = np.array([p["value"] for p in points], dtype=float)
    finite = np.isfinite(vals)
    n_valid = int(finite.sum())
    summary: dict[str, Any] = {"n_points": n_points, "n_valid": n_valid}
    if n_valid == 0:
        summary["note"] = "all timesteps are missing (NaN)"
        return summary

    v = vals[finite]
    if n_valid >= 2:
        slope = float(np.polyfit(np.arange(n_valid, dtype=float), v, 1)[0])
    else:
        slope = 0.0
    direction = "increasing" if slope > 0 else "decreasing" if slope < 0 else "flat"
    summary.update(
        {
            "value_start": float(v[0]),
            "value_end": float(v[-1]),
            "value_min": float(v.min()),
            "value_max": float(v.max()),
            "value_mean": float(v.mean()),
            "slope_per_step": slope,
            "direction": direction,
        }
    )
    return summary


def _rollup_by_year(
    values: np.ndarray | Sequence[float],
    years: np.ndarray | Sequence[int],
    agg: str,
) -> list[dict[str, Any]]:
    """Roll a per-timestep series up into per-year aggregates (a cube slice).

    Groups `values` by calendar `year` (the cube dimension) and applies `agg`
    over the finite values in each year, producing a measure per year. NaN steps
    (real data gaps) are excluded from the aggregate but still counted in
    n_steps. A year with no finite step reports value=None (not NaN, never
    raises). Rows are returned year-ascending so a multi-decade monthly file
    collapses to a few dozen summarisable rows instead of hundreds of raw points
    -- the model can pivot/slice these without hallucinating.
    """
    vals = np.asarray(values, dtype=float)
    yrs = np.asarray(years)
    rows: list[dict[str, Any]] = []
    for y in sorted(np.unique(yrs).tolist()):
        sel = yrs == y
        subset = vals[sel]
        finite = subset[np.isfinite(subset)]
        value = _apply_agg(finite, agg) if finite.size else None
        rows.append({"year": int(y), "value": value, "n_steps": int(sel.sum())})
    return rows


def _region_index(mask: dict[str, Any], region: str) -> int:
    try:
        return mask["region_names"].index(region)
    except ValueError as exc:
        raise AnalyticsError(
            f"region '{region}' not in mask; valid: {mask['region_names']}"
        ) from exc


def _apply_agg(values: np.ndarray, agg: str) -> float:
    """Apply a named aggregation. Treats NaN as missing."""
    if agg not in _VALID_AGGS:
        raise AnalyticsError(f"unknown agg '{agg}', valid: {sorted(_VALID_AGGS)}")
    if agg == "mean":
        return float(np.nanmean(values))
    if agg == "sum":
        return float(np.nansum(values))
    if agg == "max":
        return float(np.nanmax(values))
    if agg == "min":
        return float(np.nanmin(values))
    raise AnalyticsError(f"unreachable: {agg}")


def _aggregate_per_region(
    data: np.ndarray, mask: np.ndarray, agg: str
) -> tuple[list[float], list[int]]:
    """For each region, aggregate `data` over cells where mask > 0.

    Returns (values, n_cells_per_region).
    `data` has shape (..., lat, lon); mask has shape (region, lat, lon).
    """
    n_regions = mask.shape[0]
    values: list[float] = []
    n_cells: list[int] = []
    for r in range(n_regions):
        weights = mask[r]
        # Broadcast mask over leading dims of data
        weighted = np.where(weights > 0, data, np.nan)
        values.append(_apply_agg(weighted, agg))
        n_cells.append(int(np.sum(weights > 0)))
    return values, n_cells


def top_regions(
    file: str,
    var: str,
    n: int,
    agg: str,
    mask_file: str,
    year: int | None = None,
) -> dict[str, Any]:
    """Top N regions by aggregated value of `var`, optionally within one year.

    When `year` is given, only that calendar year's timesteps are loaded
    (lazy .isel before .values), so global multi-decade files do not blow
    memory. Returns rank-ordered list with values, provenance, coverage.
    """
    if agg not in _VALID_AGGS:
        raise AnalyticsError(f"unknown agg '{agg}', valid: {sorted(_VALID_AGGS)}")

    try:
        mask_info = load_region_mask(mask_file)
    except RegionMaskError as exc:
        raise AnalyticsError(str(exc)) from exc

    ds = _open(file)
    with ds:
        if var not in ds.data_vars:
            raise AnalyticsError(
                f"variable '{var}' not found; available: {list(ds.data_vars)}"
            )
        var_da = ds[var]
        units = str(var_da.attrs.get("units", ""))

        n_timesteps = None
        if year is not None:
            idx = _time_indices_for_year(ds, year)
            tdim = var_da.dims[0]  # time is the leading dim by convention
            var_da = var_da.isel({tdim: idx})  # lazy
            n_timesteps = int(idx.size)

        data = var_da.values  # materialize only the (optionally subset) slice

    values, _ = _aggregate_per_region(data, mask_info["mask"], agg)
    nan_frac = float(np.isnan(data).sum() / max(1, data.size))

    pairs = list(zip(mask_info["region_names"], values))
    pairs.sort(key=lambda p: (np.nan if np.isnan(p[1]) else -p[1]))
    top = pairs[: max(0, n)]

    coverage: dict[str, Any] = {
        "nan_fraction": nan_frac,
        "n_regions_evaluated": mask_info["n_regions"],
    }
    if n_timesteps is not None:
        coverage["n_timesteps"] = n_timesteps

    return {
        "result": [
            {"region": name, "value": value, "unit": units}
            for name, value in top
        ],
        "provenance": {
            "file_sha256": _file_sha256(file),
            "mask_sha256": mask_info["mask_sha256"],
            "var": var,
            "agg": agg,
            "n_requested": n,
            "year": year,
        },
        "coverage": coverage,
    }


def time_series(
    file: str,
    var: str,
    region: str,
    agg_per_step: str,
    mask_file: str,
) -> dict[str, Any]:
    """Time series of `var` aggregated per timestep within one region.

    Returns a compact `summary` (n_points, n_valid, value_start/end/min/max/mean,
    slope_per_step, direction) AND the raw `points`. Answer from `summary` -- do
    NOT enumerate the points. For "is it increasing/decreasing", "what is the
    trend", or "how has it changed over time" questions, prefer `nc_trend`
    (adds a significance test); use this tool when the caller wants the actual
    series or explicit start-vs-end values.
    """
    mask_info = load_region_mask(mask_file)
    r_idx = _region_index(mask_info, region)

    ds = _open(file)
    with ds:
        if var not in ds.data_vars:
            raise AnalyticsError(f"variable '{var}' not found")
        var_da = ds[var]
        if var_da.ndim < 3:
            raise AnalyticsError(
                f"variable '{var}' must have at least 3 dims (time, lat, lon); "
                f"got {var_da.ndim}"
            )
        tdim = var_da.dims[0]
        n_steps = var_da.sizes[tdim]
        time_values = ds["time"].values if "time" in ds else None
        years = _decode_years(ds)
        # The time coord may belong to a different-length dimension than the
        # variable's leading dim on a non-standard file; a mismatch would make
        # the year mask misalign with the points. Fall back to no rollup.
        if years is not None and len(years) != n_steps:
            _log.warning(
                "time axis length %d != variable steps %d; skipping year rollup",
                len(years), n_steps,
            )
            years = None

        region_mask = mask_info["mask"][r_idx]
        points: list[dict[str, Any]] = []
        # Load one timestep at a time (a few MB each) instead of the whole
        # variable, so global multi-decade files do not OOM.
        for t in range(n_steps):
            slab = var_da.isel({tdim: t}).values
            weighted = np.where(region_mask > 0, slab, np.nan)
            val = _apply_agg(weighted, agg_per_step)
            ts = float(time_values[t]) if time_values is not None else float(t)
            points.append({"t": ts, "value": val})

    by_year = (
        _rollup_by_year(
            np.array([p["value"] for p in points], dtype=float),
            years,
            agg_per_step,
        )
        if years is not None
        else []
    )

    return {
        "summary": _series_summary(points),
        "by_year": by_year,
        "points": points,
        "provenance": {
            "file_sha256": _file_sha256(file),
            "mask_sha256": mask_info["mask_sha256"],
            "var": var,
            "region": region,
            "agg_per_step": agg_per_step,
        },
    }


def compare_periods(
    file: str,
    var: str,
    period_a: tuple[int, int],
    period_b: tuple[int, int],
    mask_file: str,
    op: str = "diff",
) -> dict[str, Any]:
    """Compare two time-index ranges per region.

    period_a and period_b are (start_step, end_step_inclusive) indices.
    op is 'diff' (B - A) or 'ratio' (B / A).
    """
    if op not in ("diff", "ratio"):
        raise AnalyticsError(f"op must be 'diff' or 'ratio', got '{op}'")

    mask_info = load_region_mask(mask_file)

    a0, a1 = period_a
    b0, b1 = period_b

    ds = _open(file)
    with ds:
        if var not in ds.data_vars:
            raise AnalyticsError(f"variable '{var}' not found")
        var_da = ds[var]
        tdim = var_da.dims[0]
        # Load only the two period slabs, time-averaged, not the whole var.
        slab_a = var_da.isel({tdim: slice(a0, a1 + 1)}).mean(dim=tdim).values
        slab_b = var_da.isel({tdim: slice(b0, b1 + 1)}).mean(dim=tdim).values

    a_vals, _ = _aggregate_per_region(slab_a, mask_info["mask"], "mean")
    b_vals, _ = _aggregate_per_region(slab_b, mask_info["mask"], "mean")

    out: list[dict[str, Any]] = []
    for name, a, b in zip(mask_info["region_names"], a_vals, b_vals):
        if op == "diff":
            v = b - a
        else:  # ratio
            v = (b / a) if a != 0 else float("nan")
        out.append({"region": name, "value": v, "a": a, "b": b})

    return {
        "result": out,
        "provenance": {
            "file_sha256": _file_sha256(file),
            "mask_sha256": mask_info["mask_sha256"],
            "var": var,
            "period_a": list(period_a),
            "period_b": list(period_b),
            "op": op,
        },
    }


def _mann_kendall_trend(values: np.ndarray) -> dict[str, Any]:
    """Mann-Kendall trend + linear slope over `values`, ignoring NaN gaps.

    Real series have missing months (NaN); the previous `int(np.sign(...))` on a
    NaN difference raised "cannot convert float NaN to integer" and crashed the
    whole tool. Non-finite values are dropped first. The slope regresses on the
    ORIGINAL index positions (gaps preserved) so a missing month still counts as
    elapsed time. Returns {slope, p_value, direction, n} where n is the number
    of valid (finite) points actually used.
    """
    arr = np.asarray(values, dtype=float)
    positions = np.arange(arr.size, dtype=float)
    finite = np.isfinite(arr)
    v = arr[finite]
    x = positions[finite]
    n = int(v.size)
    if n < 3:
        raise AnalyticsError("need at least 3 valid (non-NaN) timesteps for trend")

    slope = float(np.polyfit(x, v, 1)[0])

    s_stat = 0
    for i in range(n):
        for j in range(i + 1, n):
            s_stat += int(np.sign(v[j] - v[i]))
    var_s = n * (n - 1) * (2 * n + 5) / 18.0
    if s_stat > 0:
        z = (s_stat - 1) / math.sqrt(var_s)
    elif s_stat < 0:
        z = (s_stat + 1) / math.sqrt(var_s)
    else:
        z = 0.0
    # two-sided p-value via normal CDF
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))

    if p_value < 0.1:
        direction = "increasing" if slope > 0 else "decreasing"
    else:
        direction = "no_trend"

    return {"slope": slope, "p_value": p_value, "direction": direction, "n": n}


def nc_trend(
    file: str,
    var: str,
    region: str,
    mask_file: str,
) -> dict[str, Any]:
    """Estimate a monotonic trend with Mann-Kendall + linear slope.

    PREFERRED for "is X increasing/decreasing", "what is the trend", or "how has
    X changed over time" questions. Returns a compact result: slope (linear
    regression on time index), Mann-Kendall p_value, a categorical direction
    (increasing/decreasing/no_trend), n (valid points), and n_missing (NaN gaps
    skipped). Answer directly from these fields.
    """
    ts = time_series(
        file=file, var=var, region=region,
        agg_per_step="mean", mask_file=mask_file,
    )
    all_values = [p["value"] for p in ts["points"]]
    n_total = len(all_values)
    result = _mann_kendall_trend(np.array(all_values, dtype=float))

    return {
        **result,
        "n_total": n_total,
        "n_missing": n_total - result["n"],
        "provenance": {
            **ts["provenance"],
            "method": "mann_kendall",
        },
    }
