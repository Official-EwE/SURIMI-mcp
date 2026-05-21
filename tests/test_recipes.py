"""Phase 4 RED tests — recipe tools."""
import pytest


def test_analyze_trend_returns_recipe():
    from recipes import analyze_trend
    result = analyze_trend(dataset_id="oecd-fisheries-support-eu", metric="direct_transfers_meur")
    assert "steps" in result
    assert any("query_data" in step for step in result["steps"])
    assert "GROUNDING RULE" in result["grounding"]


def test_compare_countries_returns_recipe():
    from recipes import compare_countries
    result = compare_countries(
        dataset_id="oecd-fisheries-support-eu",
        metric="direct_transfers_meur",
        countries=["NOR", "FRA", "ESP"],
    )
    assert "steps" in result
    assert any("query_data" in step for step in result["steps"])


def test_generate_report_returns_recipe():
    from recipes import generate_report
    result = generate_report(dataset_id="oecd-fisheries-support-eu", focus="subsidies")
    assert "steps" in result
    assert len(result["steps"]) >= 3


def test_recipe_grounding_rule_present():
    from recipes import GROUNDING_RULE
    assert "tool response" in GROUNDING_RULE.lower()
    assert "never invent" in GROUNDING_RULE.lower() or "never extrapolate" in GROUNDING_RULE.lower()
