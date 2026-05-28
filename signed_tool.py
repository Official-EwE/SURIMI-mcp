"""Decorator that wraps any tool function so it emits an HMAC-signed
receipt alongside its return value.

Usage:
    @with_receipt("nc_top_regions")
    def top_regions(file, var, n, agg, mask_file):
        return {... "provenance": {...}}

    # call:
    out = top_regions(...)
    # out == {"value": {...}, "receipt": {...signed...}}

Reads the HMAC secret from $SURIMI_RECEIPT_SECRET at call time so unit
tests can monkeypatch the env without affecting other tests.
"""
from __future__ import annotations

import functools
import inspect
import os
from typing import Any, Callable

from receipts import issue_receipt


class ToolError(RuntimeError):
    """Raised on tool wrapping infrastructure failures (e.g. missing secret)."""


def _get_secret() -> bytes:
    raw = os.environ.get("SURIMI_RECEIPT_SECRET", "")
    if not raw:
        raise ToolError(
            "SURIMI_RECEIPT_SECRET env var not set; cannot sign receipts"
        )
    return raw.encode("utf-8")


def _bind_args(fn: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    """Use the function's signature to produce a {name: value} dict."""
    sig = inspect.signature(fn)
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def with_receipt(tool_id: str) -> Callable:
    """Decorator factory: every call returns {value, receipt}."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            secret = _get_secret()
            params = _bind_args(fn, args, kwargs)
            value = fn(*args, **kwargs)

            provenance: dict[str, Any] | None = None
            if isinstance(value, dict) and "provenance" in value:
                provenance = value["provenance"]

            receipt = issue_receipt(
                tool_id=tool_id,
                input_params=params,
                output_value=value,
                secret=secret,
                provenance=provenance,
            )
            return {"value": value, "receipt": receipt}

        return wrapper

    return deco
