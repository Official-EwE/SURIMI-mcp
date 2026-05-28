"""Pytest fixtures shared across surimi-mcp tests."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr


@pytest.fixture
def tiny_nc(tmp_path: Path) -> str:
    """A tiny CF-compliant 3D netcdf file (time, lat, lon).

    4 timesteps, 3x4 grid (lat x lon).
    Variable `biomass` with known values so tests can assert exact aggregates.
    """
    ntime, nlat, nlon = 4, 3, 4
    lat = np.linspace(-30.0, 30.0, nlat).astype("float32")
    lon = np.linspace(-180.0, 180.0, nlon, endpoint=False).astype("float32")
    # Days since epoch for 4 monthly steps in 2010
    time_idx = np.array([0, 31, 59, 90], dtype="float64")

    # Make biomass[t, lat, lon] = t*100 + lat_idx*10 + lon_idx
    biomass = np.zeros((ntime, nlat, nlon), dtype="float32")
    for t in range(ntime):
        for i in range(nlat):
            for j in range(nlon):
                biomass[t, i, j] = t * 100 + i * 10 + j

    ds = xr.Dataset(
        data_vars={
            "biomass": (("time", "lat", "lon"), biomass, {
                "units": "kg m-2",
                "long_name": "Biomass density",
            }),
        },
        coords={
            "time": ("time", time_idx, {"units": "days since 2010-01-01"}),
            "lat": ("lat", lat, {"units": "degrees_north"}),
            "lon": ("lon", lon, {"units": "degrees_east"}),
        },
        attrs={
            "Conventions": "CF-1.8",
            "title": "Synthetic test dataset",
        },
    )

    path = tmp_path / "tiny.nc"
    ds.to_netcdf(path, format="NETCDF4")
    return str(path)


@pytest.fixture
def tiny_nc_no_cf(tmp_path: Path) -> str:
    """Variant with no Conventions attribute, to test CF-compliance fallback."""
    arr = np.arange(2 * 2 * 2, dtype="float32").reshape(2, 2, 2)
    ds = xr.Dataset(
        data_vars={"x": (("time", "lat", "lon"), arr)},
        coords={"time": [0, 1], "lat": [-10.0, 10.0], "lon": [0.0, 90.0]},
    )
    path = tmp_path / "nocf.nc"
    ds.to_netcdf(path)
    return str(path)


@pytest.fixture
def tiny_nc_multiyear(tmp_path: Path) -> str:
    """6 monthly steps spanning 2009-2010 so year-filtering is observable.

    biomass[t, lat, lon] = (t+1) * 100  (uniform per timestep)
    timesteps: 3 in 2009 (Jan/Feb/Mar) then 3 in 2010 (Jan/Feb/Mar).
    So year=2009 mean = mean(100,200,300)=200; year=2010 = mean(400,500,600)=500.
    """
    nlat, nlon = 3, 4
    lat = np.linspace(-30.0, 30.0, nlat).astype("float32")
    lon = np.linspace(-180.0, 180.0, nlon, endpoint=False).astype("float32")
    # days since 2009-01-01 : 2009 Jan/Feb/Mar then 2010 Jan/Feb/Mar
    time_idx = np.array([0, 31, 59, 365, 396, 424], dtype="float64")
    biomass = np.zeros((6, nlat, nlon), dtype="float32")
    for t in range(6):
        biomass[t, :, :] = (t + 1) * 100.0

    ds = xr.Dataset(
        data_vars={"biomass": (("time", "lat", "lon"), biomass, {"units": "kg"})},
        coords={
            "time": ("time", time_idx, {"units": "days since 2009-01-01"}),
            "lat": ("lat", lat), "lon": ("lon", lon),
        },
        attrs={"Conventions": "CF-1.8"},
    )
    path = tmp_path / "multiyear.nc"
    ds.to_netcdf(path, format="NETCDF4")
    return str(path)


@pytest.fixture
def tiny_region_mask(tmp_path: Path) -> str:
    """A region mask matching the tiny_nc grid: 2 regions splitting the longitude.

    Region 1: lon < 0 (i.e. lon indices 0, 1)
    Region 2: lon >= 0 (lon indices 2, 3)
    Mask is a netcdf file with a `region` variable: (n_regions, lat, lon) of weights.
    """
    nlat, nlon = 3, 4
    lat = np.linspace(-30.0, 30.0, nlat).astype("float32")
    lon = np.linspace(-180.0, 180.0, nlon, endpoint=False).astype("float32")

    # Region 1: West (lon < 0), Region 2: East (lon >= 0)
    mask = np.zeros((2, nlat, nlon), dtype="float32")
    for j, lon_val in enumerate(lon):
        if lon_val < 0:
            mask[0, :, j] = 1.0
        else:
            mask[1, :, j] = 1.0

    ds = xr.Dataset(
        data_vars={
            "region": (("region_id", "lat", "lon"), mask),
        },
        coords={
            "region_id": ("region_id", [1, 2]),
            "region_name": ("region_id", np.array(["West", "East"], dtype="<U16")),
            "lat": ("lat", lat),
            "lon": ("lon", lon),
        },
    )
    path = tmp_path / "mask.nc"
    ds.to_netcdf(path)
    return str(path)
