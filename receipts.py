"""HMAC-signed tool execution receipts.

Pattern follows arxiv 2603.10060 ("Tool Receipts, Not Zero-Knowledge Proofs").
Each analytical tool issues a receipt containing the inputs, outputs, and
provenance, signed with an HMAC keyed by a server-side secret. Downstream
verifiers re-sign the same payload and compare in constant time.

The LLM cannot forge a valid signature without the secret.

Usage:
    r = issue_receipt(
        tool_id="nc_top_regions",
        input_params={"file": "s3://b/x.nc", "year": 2010, "n": 3},
        output_value=[{"region": "Humboldt", "value": 18.4}],
        secret=os.environ["SURIMI_RECEIPT_SECRET"].encode(),
        provenance={"file_sha256": "...", "mask_sha256": "..."},
    )
    # r is JSON-serializable, returned alongside tool output.

    res = verify_receipt(r, secret=...)
    if res["verified"]: ...
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any


SCHEMA_VERSION = 1


class ReceiptError(ValueError):
    """Raised on invalid receipt construction or verification inputs."""


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce(obj: Any) -> Any:
    """Recursively convert DB-native types into JSON-native, deterministic forms.

    Decimal -> str (exact, avoids float rounding drift across runs)
    datetime / date -> ISO 8601 string
    dict / list / tuple -> recursed
    str / int / float / bool / None -> unchanged
    Anything else raises ReceiptError (truly opaque values must fail loudly).

    Run at issue time so the STORED receipt is JSON-serializable too, not just
    the bytes we sign. Otherwise the MCP layer chokes returning the receipt.
    """
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _coerce(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_coerce(v) for v in obj]
    raise ReceiptError(
        f"value of type {type(obj).__name__} is not serializable for a receipt"
    )


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON serialization for signing.

    Sorted keys, separators with no whitespace, ensure_ascii=False. The
    payload is already _coerce-d, so json.dumps never hits an opaque type.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sign(payload: dict[str, Any], secret: bytes) -> str:
    canonical = _canonical_bytes(payload)
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()


def issue_receipt(
    tool_id: str,
    input_params: dict[str, Any],
    output_value: Any,
    secret: bytes,
    *,
    timestamp: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a signed receipt for a tool execution."""
    if not secret:
        raise ReceiptError("secret must be non-empty bytes")

    body: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "tool_id": tool_id,
        "input_params": _coerce(input_params),
        "output_value": _coerce(output_value),
        "timestamp": timestamp or _now_iso(),
    }
    if provenance is not None:
        body["provenance"] = _coerce(provenance)

    body["signature"] = _sign(body, secret)
    return body


def verify_receipt(receipt: dict[str, Any], secret: bytes) -> dict[str, Any]:
    """Verify a receipt against the secret.

    Returns {verified: bool, reason: str}. Never raises on signature
    mismatch; raises ReceiptError only on usage errors (empty secret).
    """
    if not secret:
        raise ReceiptError("secret must be non-empty bytes")

    required = {"version", "tool_id", "input_params", "output_value", "timestamp", "signature"}
    missing = required - set(receipt.keys())
    if missing:
        return {"verified": False, "reason": "missing_field", "missing": sorted(missing)}

    if receipt["version"] != SCHEMA_VERSION:
        return {
            "verified": False,
            "reason": "unsupported_version",
            "got": receipt["version"],
            "supported": SCHEMA_VERSION,
        }

    claimed = receipt["signature"]
    body = {k: v for k, v in receipt.items() if k != "signature"}
    expected = _sign(body, secret)

    if not hmac.compare_digest(claimed, expected):
        return {"verified": False, "reason": "signature_mismatch"}

    return {"verified": True, "reason": "ok"}
