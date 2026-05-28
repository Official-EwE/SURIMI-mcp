"""NetCDF IO: open + hash + existence for local paths and S3/MinIO URIs.

Centralizes the local-vs-S3 distinction so inspect/analytics/regions do not
each reimplement it. S3 access uses s3fs against the EDITO MinIO endpoint,
reading credentials from the standard AWS_* env vars (the chart mounts STS
creds; locally you export them).

Reads happen as file handles where possible; for the SHA-256 provenance we
stream the whole object (netcdf files here are <1 GB).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import xarray as xr


class NetCDFIOError(Exception):
    """Raised on IO failure (missing file, missing S3 config, open error)."""


_S3_PREFIX = "s3://"
_FILE_PREFIX = "file://"


def is_s3_uri(uri: str) -> bool:
    return uri.startswith(_S3_PREFIX)


def _strip_file_scheme(uri: str) -> str:
    if uri.startswith(_FILE_PREFIX):
        return uri[len(_FILE_PREFIX):]
    return uri


def _s3_filesystem():
    """Build an s3fs filesystem from AWS_* env vars + EDITO MinIO endpoint."""
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint:
        raise NetCDFIOError(
            "AWS_ENDPOINT_URL not set; cannot reach S3/MinIO for an s3:// URI"
        )
    try:
        import s3fs
    except ImportError as exc:  # pragma: no cover - import guard
        raise NetCDFIOError("s3fs not installed; cannot read s3:// URIs") from exc

    return s3fs.S3FileSystem(
        key=os.environ.get("AWS_ACCESS_KEY_ID"),
        secret=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        token=os.environ.get("AWS_SESSION_TOKEN"),
        client_kwargs={"endpoint_url": endpoint},
    )


def open_dataset(uri: str, **kwargs: Any) -> xr.Dataset:
    """Open a netcdf dataset from a local path or s3:// URI.

    For S3 the object is opened as a streaming file handle and read with the
    h5netcdf engine (works on NETCDF4/HDF5 files without a local copy).
    """
    if is_s3_uri(uri):
        fs = _s3_filesystem()
        try:
            handle = fs.open(uri, "rb")
            return xr.open_dataset(handle, engine="h5netcdf", **kwargs)
        except Exception as exc:
            raise NetCDFIOError(f"could not open {uri}: {exc}") from exc

    path = Path(_strip_file_scheme(uri))
    if not path.exists():
        raise NetCDFIOError(f"file not found: {uri}")
    if not path.is_file():
        raise NetCDFIOError(f"not a file: {uri}")
    try:
        return xr.open_dataset(path, **kwargs)
    except Exception as exc:
        raise NetCDFIOError(f"could not open {uri}: {exc}") from exc


def resource_sha256(uri: str) -> str:
    """SHA-256 of the resource bytes (used as provenance in receipts)."""
    if is_s3_uri(uri):
        fs = _s3_filesystem()
        try:
            data = fs.cat_file(uri)
        except Exception as exc:
            raise NetCDFIOError(f"could not read {uri}: {exc}") from exc
        return hashlib.sha256(data).hexdigest()

    path = Path(_strip_file_scheme(uri))
    if not path.exists():
        raise NetCDFIOError(f"file not found: {uri}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def exists(uri: str) -> bool:
    if is_s3_uri(uri):
        try:
            return bool(_s3_filesystem().exists(uri))
        except NetCDFIOError:
            return False
    return Path(_strip_file_scheme(uri)).exists()
