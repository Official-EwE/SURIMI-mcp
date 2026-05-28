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
_CACHE_DIR = os.environ.get("SURIMI_NC_CACHE", "/tmp/surimi-s3cache")


def is_s3_uri(uri: str) -> bool:
    return uri.startswith(_S3_PREFIX)


def _localize(uri: str) -> str:
    """Return a local filesystem path for `uri`.

    For s3:// the object is downloaded once to a content-addressed cache file
    (streamed to disk by s3fs, so RAM stays bounded) and reused. HDF5/netcdf
    need efficient random seeks, which only work well on a local file, NOT on
    a streamed S3 handle (that buffers the whole object in memory and OOMs).
    """
    if not is_s3_uri(uri):
        return _strip_file_scheme(uri)

    import hashlib

    os.makedirs(_CACHE_DIR, exist_ok=True)
    key = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:16]
    local = os.path.join(_CACHE_DIR, f"{key}.nc")
    if not os.path.exists(local):
        fs = _s3_filesystem()
        tmp = local + ".part"
        try:
            fs.get_file(uri, tmp)        # streams to disk in chunks, bounded RAM
            os.replace(tmp, local)       # atomic; avoids half-downloaded cache hits
        except Exception as exc:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise NetCDFIOError(f"could not download {uri}: {exc}") from exc
    return local


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

    s3:// is downloaded to a local cache file first (see _localize), then
    opened locally so HDF5 random access is efficient and memory bounded.
    """
    path = Path(_localize(uri))
    if not path.exists():
        raise NetCDFIOError(f"file not found: {uri}")
    if not path.is_file():
        raise NetCDFIOError(f"not a file: {uri}")
    try:
        return xr.open_dataset(path, **kwargs)
    except Exception as exc:
        raise NetCDFIOError(f"could not open {uri}: {exc}") from exc


def resource_sha256(uri: str) -> str:
    """SHA-256 of the resource bytes (used as provenance in receipts).

    Streams from the local (or localized-from-S3) file in chunks so a large
    object is never fully held in RAM.
    """
    path = Path(_localize(uri))
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


def list_objects(prefix: str) -> list[dict[str, Any]]:
    """List files directly under `prefix` (an s3:// prefix or a local dir).

    Returns [{uri, size}], files only (directories excluded). Used by the
    discovery layer so the LLM can find catalog data without being told paths.
    """
    if is_s3_uri(prefix):
        fs = _s3_filesystem()
        path = prefix[len(_S3_PREFIX):].rstrip("/")
        try:
            entries = fs.ls(path, detail=True)
        except Exception as exc:
            raise NetCDFIOError(f"could not list {prefix}: {exc}") from exc
        out: list[dict[str, Any]] = []
        for e in entries:
            name = e.get("name") or e.get("Key")
            if not name:
                continue
            if e.get("type") == "directory":
                continue
            size = int(e.get("size") or e.get("Size") or 0)
            out.append({"uri": _S3_PREFIX + name, "size": size})
        return out

    p = Path(_strip_file_scheme(prefix))
    if not p.is_dir():
        raise NetCDFIOError(f"not a directory: {prefix}")
    return [
        {"uri": str(f), "size": f.stat().st_size}
        for f in sorted(p.iterdir())
        if f.is_file()
    ]
