"""Phase 3 RED tests — search + explain tools."""
import pytest


def test_explain_indicator_known():
    from search import explain_indicator
    result = explain_indicator("direct_transfers_meur")
    assert result["found"] is True
    assert result["definition"] is not None


def test_explain_indicator_by_dataset():
    from search import explain_indicator
    result = explain_indicator("employment_fte", dataset_id="eu-dcf-economic-aegean")
    assert result["found"] is True


def test_explain_indicator_unknown():
    from search import explain_indicator
    result = explain_indicator("completely_made_up_xyz")
    assert result["found"] is False


def test_explain_indicator_returns_dataset_context():
    from search import explain_indicator
    result = explain_indicator("biomass_kt")
    assert result["found"] is True
    assert "dataset_id" in result
