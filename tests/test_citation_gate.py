"""Tests for the citation-gate middleware.

The gate scans LLM response text for numerical quantities and ensures
each one is adjacent to a `[receipt:<id>]` tag. Quantities without a
receipt tag are flagged as 'unsigned' and reported back to the LLM
loop so it can re-emit with a tool call.

Heuristics (v1):
- Decimal numbers (e.g. `18.4`, `1.5e-3`) MUST have a receipt nearby.
- Integers >= 100 MUST have a receipt (avoid flagging small counts).
- Years 1800-2100 are EXEMPT (treated as time references, not data).
- Integers <= 99 are EXEMPT (treated as descriptive counts).
"""
from __future__ import annotations

import pytest

from citation_gate import check_citations


# ---------- accept cases ----------

def test_accepts_when_every_quantity_has_receipt():
    text = "Biomass is 18.4 [receipt:abc123] kg/m² in 2025 [receipt:abc124]."
    out = check_citations(text)
    assert out["accepted"] is True
    assert out["unsigned"] == []


def test_accepts_text_with_no_numbers():
    text = "The dataset contains several regions and species."
    out = check_citations(text)
    assert out["accepted"] is True


def test_accepts_small_integer_counts_without_receipt():
    text = "Top 3 regions are reported."
    out = check_citations(text)
    assert out["accepted"] is True


def test_accepts_year_without_receipt():
    text = "In 2025 the model output was generated."
    out = check_citations(text)
    assert out["accepted"] is True


def test_accepts_year_range_without_receipt():
    text = "Between 1990 and 2010 biomass declined."
    out = check_citations(text)
    # Decline statement still needs a receipt if we cite a number,
    # but pure year range without a quantity is OK.
    assert out["accepted"] is True


def test_accepts_receipt_within_window_after_number():
    """Allow a small gap (e.g. unit) between number and receipt."""
    text = "Value is 18.4 g/m^2 [receipt:abc]."
    out = check_citations(text)
    assert out["accepted"] is True


def test_accepts_negative_number_with_receipt():
    text = "Slope is -0.45 [receipt:abc] per year."
    out = check_citations(text)
    assert out["accepted"] is True


def test_accepts_scientific_notation_with_receipt():
    text = "p-value is 1.5e-3 [receipt:abc]."
    out = check_citations(text)
    assert out["accepted"] is True


# ---------- reject cases ----------

def test_rejects_unsigned_decimal():
    text = "Biomass is 18.4 kg/m²."
    out = check_citations(text)
    assert out["accepted"] is False
    quoted = [u["value"] for u in out["unsigned"]]
    assert "18.4" in quoted


def test_rejects_large_unsigned_integer():
    text = "There are 1500 species in the catalog."
    out = check_citations(text)
    assert out["accepted"] is False


def test_rejects_when_only_some_numbers_have_receipts():
    text = "Humboldt 18.4 [receipt:a1], Benguela 17.1, California 15.2 [receipt:a3]."
    out = check_citations(text)
    assert out["accepted"] is False
    quoted = [u["value"] for u in out["unsigned"]]
    assert "17.1" in quoted
    assert "18.4" not in quoted
    assert "15.2" not in quoted


def test_rejects_decimal_with_far_away_receipt():
    """A receipt 200 chars away should not protect the number."""
    text = "Biomass is 18.4 kg/m²." + " filler " * 30 + "[receipt:abc]"
    out = check_citations(text)
    assert out["accepted"] is False


def test_reports_position_of_each_unsigned_number():
    text = "Biomass is 18.4 kg/m²."
    out = check_citations(text)
    assert out["unsigned"][0]["value"] == "18.4"
    assert out["unsigned"][0]["position"] == text.index("18.4")


def test_returns_summary_counts():
    text = "Humboldt 18.4 [receipt:a1], Benguela 17.1."
    out = check_citations(text)
    assert out["n_quantities"] == 2
    assert out["n_signed"] == 1
    assert out["n_unsigned"] == 1


# ---------- configuration ----------

def test_window_is_configurable():
    """Allow callers to tighten or loosen the proximity window."""
    text = "Value is 18.4" + " " * 60 + "[receipt:abc]."
    # Default window (~50): receipt too far
    assert check_citations(text)["accepted"] is False
    # Larger window: receipt accepted
    assert check_citations(text, window=80)["accepted"] is True


def test_year_range_can_be_overridden():
    """Allow callers to disable the year exemption."""
    text = "In 2025 we measured 18.4 [receipt:abc]."
    # Default: 2025 exempt
    assert check_citations(text)["accepted"] is True
    # With years_exempt=False: 2025 is flagged
    assert check_citations(text, years_exempt=False)["accepted"] is False
