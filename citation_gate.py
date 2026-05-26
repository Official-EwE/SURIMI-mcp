"""Citation gate: enforce that every numeric quantity in LLM text carries
an adjacent `[receipt:<id>]` tag.

Designed to be middleware on the chat UI side. Scans the LLM's draft
response, returns:
    {accepted: bool, unsigned: [{value, position, ...}], n_quantities,
     n_signed, n_unsigned}

If accepted is False, the chat loop should rewind the response and ask
the LLM to re-emit using tool calls for the flagged numbers.

Receipts are paired greedy-by-proximity: each receipt covers the closest
preceding unsigned number within the window. Receipts are not shared,
so two adjacent numbers need two receipts.

Heuristic policy (v1):
- Decimals and scientific notation: always require receipt.
- Integers >= 100: require receipt.
- Integers <= 99: exempt (treated as descriptive counts).
- 4-digit integers in 1800-2100: exempt by default (treated as years).
"""
from __future__ import annotations

import re
from typing import Any


# A number is: optional sign, digits, optional decimal, optional sci notation.
# Boundary: not preceded by word char (so "a1" does not match as "1"), and
# not followed by a digit/word char (so "1.5.3" tokenizes as "1.5" and "3").
NUMBER_RE = re.compile(
    r"(?<![\w.])"
    r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"(?![\w])"
)

RECEIPT_RE = re.compile(r"\[receipt:[A-Za-z0-9_.:-]+\]")

DEFAULT_WINDOW = 50  # chars between the number's end and the receipt tag's start


def _is_exempt_integer(value_str: str, *, years_exempt: bool) -> bool:
    """True if the number doesn't need a receipt."""
    if "." in value_str or "e" in value_str.lower():
        return False
    try:
        n = int(value_str)
    except ValueError:
        return False
    if -99 <= n <= 99:
        return True
    if years_exempt and 1800 <= n <= 2100:
        return True
    return False


def check_citations(
    text: str,
    *,
    window: int = DEFAULT_WINDOW,
    years_exempt: bool = True,
) -> dict[str, Any]:
    """Scan `text` for numeric quantities and confirm each has a receipt nearby."""
    numbers: list[dict[str, Any]] = []
    for m in NUMBER_RE.finditer(text):
        value_str = m.group(1)
        if _is_exempt_integer(value_str, years_exempt=years_exempt):
            continue
        numbers.append({
            "value": value_str,
            "position": m.start(),
            "end": m.end(),
        })

    receipt_positions = [m.start() for m in RECEIPT_RE.finditer(text)]

    signed_idx: set[int] = set()
    for r_pos in receipt_positions:
        best_idx: int | None = None
        best_dist = window + 1
        for i, num in enumerate(numbers):
            if i in signed_idx:
                continue
            dist = r_pos - num["end"]
            if 0 <= dist < best_dist:
                best_idx = i
                best_dist = dist
        if best_idx is not None:
            signed_idx.add(best_idx)

    unsigned: list[dict[str, Any]] = []
    for i, num in enumerate(numbers):
        if i not in signed_idx:
            unsigned.append({
                "value": num["value"],
                "position": num["position"],
            })

    return {
        "accepted": not unsigned,
        "unsigned": unsigned,
        "n_quantities": len(numbers),
        "n_signed": len(signed_idx),
        "n_unsigned": len(unsigned),
    }
