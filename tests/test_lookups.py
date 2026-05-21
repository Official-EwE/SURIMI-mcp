"""Phase 1 RED tests — lookup tools + capability registry."""
import pytest


def test_list_datasets_returns_catalog():
    from catalog import list_datasets
    result = list_datasets()
    assert len(result["datasets"]) >= 5
    assert all("id" in d and "name" in d and "table" in d for d in result["datasets"])


def test_list_datasets_filter_by_domain():
    from catalog import list_datasets
    result = list_datasets(domain="oecd")
    assert len(result["datasets"]) >= 1
    assert all("oecd" in d["table"].lower() or "fse" in d["table"].lower() for d in result["datasets"])


def test_list_datasets_filter_unknown_domain_empty():
    from catalog import list_datasets
    result = list_datasets(domain="nonexistent_domain_xyz")
    assert len(result["datasets"]) == 0


def test_list_columns_returns_schema():
    from catalog import list_columns
    result = list_columns(dataset_id="oecd-fisheries-support-eu")
    assert result["error"] is None
    assert len(result["columns"]) > 0
    assert all("name" in c and "type" in c for c in result["columns"])


def test_list_columns_unknown_dataset_returns_error():
    from catalog import list_columns
    result = list_columns(dataset_id="nonexistent")
    assert result["error"] is not None


def test_list_columns_fuzzy_match():
    from catalog import list_columns
    result = list_columns(dataset_id="oecd_fisheries_support_estimates_eu_coastal_states")
    assert result["error"] is None
    assert len(result["columns"]) > 0


def test_find_dataset_by_kebab():
    from catalog import find_dataset
    ds = find_dataset("eu-dcf-economic-aegean")
    assert ds is not None
    assert ds["id"] == "eu-dcf-economic-aegean"


def test_find_dataset_by_table_name():
    from catalog import find_dataset
    ds = find_dataset("fsedata")
    assert ds is not None
    assert ds["id"] == "oecd-fsedata"


def test_find_dataset_by_fqn():
    from catalog import find_dataset
    ds = find_dataset("hive.oecd.fsedata")
    assert ds is not None


def test_find_dataset_partial_match():
    from catalog import find_dataset
    ds = find_dataset("biomass")
    assert ds is not None
    assert "biomass" in ds["id"]
