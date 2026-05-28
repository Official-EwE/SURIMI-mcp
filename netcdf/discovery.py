"""NetCDF catalog discovery.

Lets the LLM answer "what data do you have?" and pick a file from a plain
question, instead of the user supplying s3:// paths. Pairs with nc_describe_file
(drill into a chosen file's variables) and the analytical primitives.
"""
from __future__ import annotations

from typing import Any

from netcdf import io as ncio


def classify(uri: str) -> str:
    """Classify a catalog object: 'data' netcdf, 'mask' netcdf, or 'other'."""
    name = uri.rsplit("/", 1)[-1].lower()
    if not name.endswith(".nc"):
        return "other"
    if "mask" in name:
        return "mask"
    return "data"


def list_netcdf_files(prefix: str) -> dict[str, Any]:
    """List the netcdf catalog under `prefix`, each tagged data/mask/other."""
    objs = ncio.list_objects(prefix)
    files = [
        {"uri": o["uri"], "size": o["size"], "kind": classify(o["uri"])}
        for o in objs
    ]
    return {"prefix": prefix, "count": len(files), "files": files}
