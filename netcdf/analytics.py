"""Deterministic analytical primitives for netcdf data.

Each primitive is a single tool that:
1. Opens the file deterministically
2. Applies the region mask
3. Aggregates server-side (LLM never iterates)
4. Returns the result with provenance + coverage

Provenance is wrapped by the receipts module at the MCP tool layer.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import xarray as xr

from netcdf import io as ncio
from netcdf.regions import RegionMaskError, load_region_mask


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


def _time_indices_for_year(ds: xr.Dataset, year: int) -> np.ndarray:
    """Indices along the time axis whose decoded calendar year == year.

    Dataset is opened with decode_times=False, so we decode the raw time
    coordinate via CF units here (lazy enough; the time axis is small).
    """
    tname = None
    for cand in ("time", "t", "T"):
        if cand in ds.coords or cand in ds.dims:
            tname = cand
            break
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
    """Time series of `var` aggregated per timestep within one region."""
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

    return {
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


def nc_trend(
    file: str,
    var: str,
    region: str,
    mask_file: str,
) -> dict[str, Any]:
    """Estimate a monotonic trend with Mann-Kendall + linear slope.

    Returns slope (linear regression on time index) + Mann-Kendall p-value
    + a categorical direction.
    """
    ts = time_series(
        file=file, var=var, region=region,
        agg_per_step="mean", mask_file=mask_file,
    )
    values = np.array([p["value"] for p in ts["points"]])
    n = len(values)
    if n < 3:
        raise AnalyticsError("need at least 3 timesteps for trend")

    # Linear slope
    x = np.arange(n, dtype=float)
    slope = float(np.polyfit(x, values, 1)[0])

    # Mann-Kendall statistic S
    s_stat = 0
    for i in range(n):
        for j in range(i + 1, n):
            s_stat += int(np.sign(values[j] - values[i]))
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

    return {
        "slope": slope,
        "p_value": p_value,
        "direction": direction,
        "n": n,
        "provenance": {
            **ts["provenance"],
            "method": "mann_kendall",
        },
    }
