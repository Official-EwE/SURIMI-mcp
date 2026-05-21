"""Dataset catalog for SURIMI fisheries/OECD data in Trino.

Ported from mcp-superset/src/config/datasets.ts. Static catalog — no
Superset dependency. Lookup functions accept kebab-case IDs, Trino FQNs,
table names, or partial matches.
"""
from __future__ import annotations

import re
from typing import Any, Optional


DATASETS: list[dict[str, Any]] = [
    {
        "id": "eu-dcf-economic-aegean",
        "name": "EU DCF — Fisheries Economic Performance, Aegean Sea",
        "domain": "eu_dcf",
        "table": "hive.eu_dcf.eu_dcf_fisheries_economic_performance_aegean_sea",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "int"},
            {"name": "gear_code", "type": "string"},
            {"name": "country_code", "type": "string"},
            {"name": "gross_revenue_meur", "type": "float"},
            {"name": "operating_cost_meur", "type": "float"},
            {"name": "gross_value_added_meur", "type": "float"},
            {"name": "profit_margin", "type": "float"},
            {"name": "employment_fte", "type": "int"},
        ],
    },
    {
        "id": "eu-dcf-employment-wmed",
        "name": "EU DCF — Fisheries Employment, Western Mediterranean",
        "domain": "eu_dcf",
        "table": "hive.eu_dcf.eu_dcf_fisheries_employment_western_mediterranean",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "int"},
            {"name": "gear_code", "type": "string"},
            {"name": "country_code", "type": "string"},
            {"name": "employment_fte", "type": "int"},
            {"name": "gender_balance_ratio", "type": "float"},
        ],
    },
    {
        "id": "oecd-fisheries-support-eu",
        "name": "OECD — Fisheries Support Estimates, EU Coastal States",
        "domain": "oecd",
        "table": "hive.oecd.oecd_fisheries_support_estimates_eu_coastal_states",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "int"},
            {"name": "country_code", "type": "string"},
            {"name": "direct_transfers_meur", "type": "float"},
            {"name": "cost_reducing_transfers_meur", "type": "float"},
            {"name": "general_services_meur", "type": "float"},
        ],
    },
    {
        "id": "surimi-biomass-wmed-empirical",
        "name": "SURIMI — Empirical Biomass Surveys, Western Mediterranean",
        "domain": "surimi",
        "table": "hive.surimi.surimi_empirical_biomass_surveys_western_mediterranean",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "int"},
            {"name": "species_code", "type": "string"},
            {"name": "biomass_kt", "type": "float"},
            {"name": "cv_uncertainty", "type": "float"},
        ],
    },
    {
        "id": "surimi-sales-aegean-simulated",
        "name": "SURIMI — Simulated Sales Output, Aegean Sea",
        "domain": "surimi",
        "table": "hive.surimi.surimi_simulated_sales_output_aegean_sea",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "int"},
            {"name": "market_code", "type": "string"},
            {"name": "species_code", "type": "string"},
            {"name": "quantity_kt", "type": "float"},
            {"name": "price_eur_per_kg", "type": "float"},
            {"name": "value_meur", "type": "float"},
        ],
    },
    {
        "id": "aer-economic-national-level",
        "name": "EU DCF — AER Economic Performance, National Level",
        "domain": "eu_dcf",
        "table": "hive.eu_dcf.aer_economic_national_level",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "string"},
            {"name": "country_code", "type": "string"},
            {"name": "country_name", "type": "string"},
            {"name": "variable_group", "type": "string"},
            {"name": "variable_name", "type": "string"},
            {"name": "variable_code", "type": "string"},
            {"name": "value", "type": "string"},
            {"name": "unit", "type": "string"},
        ],
    },
    {
        "id": "aer-social-data",
        "name": "EU DCF — AER Social Data (2017–2020)",
        "domain": "eu_dcf",
        "table": "hive.eu_dcf.aer_social_data_2017_2020",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "string"},
            {"name": "country_code", "type": "string"},
            {"name": "country_name", "type": "string"},
            {"name": "fishing_tech", "type": "string"},
            {"name": "vessel_length", "type": "string"},
            {"name": "gender", "type": "string"},
            {"name": "employment_status", "type": "string"},
            {"name": "variable_code", "type": "string"},
            {"name": "variable_value", "type": "string"},
        ],
    },
    {
        "id": "aer-capacity",
        "name": "EU DCF — AER Fleet Capacity",
        "domain": "eu_dcf",
        "table": "hive.eu_dcf.aer_capacity",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "string"},
            {"name": "country_code", "type": "string"},
            {"name": "country_name", "type": "string"},
            {"name": "fishing_tech", "type": "string"},
            {"name": "vessel_length", "type": "string"},
            {"name": "number_of_vessels", "type": "string"},
            {"name": "total_vessel_power", "type": "string"},
            {"name": "total_vessel_tonnage", "type": "string"},
            {"name": "mean_age_of_vessels", "type": "string"},
        ],
    },
    {
        "id": "aer-economic-2013-2023",
        "name": "EU DCF — AER Economic Performance (2013–2023)",
        "domain": "eu_dcf",
        "table": "hive.eu_dcf.aer_economic_2013_2023",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "string"},
            {"name": "country_code", "type": "string"},
            {"name": "country_name", "type": "string"},
            {"name": "fishing_tech", "type": "string"},
            {"name": "vessel_length", "type": "string"},
            {"name": "variable_group", "type": "string"},
            {"name": "variable_name", "type": "string"},
            {"name": "variable_code", "type": "string"},
            {"name": "value", "type": "string"},
            {"name": "unit", "type": "string"},
            {"name": "gear", "type": "string"},
            {"name": "fishery", "type": "string"},
        ],
    },
    {
        "id": "fdi-capacity-by-country",
        "name": "EU DCF — FDI Fleet Capacity by Country",
        "domain": "eu_dcf",
        "table": "hive.eu_dcf.fdi_capacity_by_country",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "string"},
            {"name": "country", "type": "string"},
            {"name": "vessel_length_category", "type": "string"},
            {"name": "fishing_tech", "type": "string"},
            {"name": "total_vessels", "type": "string"},
            {"name": "total_kw", "type": "string"},
            {"name": "total_gt", "type": "string"},
            {"name": "total_trips", "type": "string"},
            {"name": "average_age", "type": "string"},
            {"name": "maximum_sea_days", "type": "string"},
        ],
    },
    {
        "id": "oecd-fsedata",
        "name": "OECD — Fisheries Support Estimates (FSE), Wide Format",
        "domain": "oecd",
        "table": "hive.oecd.fsedata",
        "time_column": "2022",
        "columns": [
            {"name": "country_code", "type": "string"},
            {"name": "country_name", "type": "string"},
            {"name": "fse_category_code", "type": "string"},
            {"name": "fse_category_name", "type": "string"},
            {"name": "country_policy_description", "type": "string"},
            {"name": "support_mechanism", "type": "string"},
            {"name": "unit_of_measure_name", "type": "string"},
        ],
    },
    {
        "id": "eu-dcf-fuel",
        "name": "EU DCF — Fuel Costs and Efficiency",
        "domain": "eu_dcf",
        "table": "hive.eu_dcf.fuel",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "string"},
            {"name": "country_code", "type": "string"},
            {"name": "country_name", "type": "string"},
            {"name": "fishing_tech", "type": "string"},
            {"name": "sum_revenue", "type": "string"},
            {"name": "sum_ecost", "type": "string"},
            {"name": "fuel_efficiency", "type": "string"},
        ],
    },
    {
        "id": "eu-dcf-rev-grp",
        "name": "EU DCF — Revenue and Gross Profit",
        "domain": "eu_dcf",
        "table": "hive.eu_dcf.rev_grp",
        "time_column": "year",
        "columns": [
            {"name": "year", "type": "string"},
            {"name": "country_code", "type": "string"},
            {"name": "country_name", "type": "string"},
            {"name": "fishing_tech", "type": "string"},
            {"name": "vessel_length", "type": "string"},
            {"name": "revenue", "type": "string"},
            {"name": "grp", "type": "string"},
        ],
    },
]

_NORM_RE = re.compile(r"[._\-]")


def _norm(s: str) -> str:
    return _NORM_RE.sub("", s.lower())


def find_dataset(dataset_id: str) -> Optional[dict[str, Any]]:
    needle = _norm(dataset_id)
    for d in DATASETS:
        if _norm(d["id"]) == needle:
            return d
        if _norm(d["table"]) == needle:
            return d
        parts = d["table"].split(".")
        if len(parts) == 3 and _norm(parts[2]) == needle:
            return d
        if len(parts) == 3 and _norm(f"{parts[1]}.{parts[2]}") == needle:
            return d
    for d in DATASETS:
        if len(needle) > 4 and needle in _norm(d["id"]):
            return d
        if len(needle) > 4 and needle in _norm(d["table"]):
            return d
    return None


def list_datasets(domain: Optional[str] = None) -> dict[str, Any]:
    filtered = DATASETS
    if domain:
        domain_lower = domain.lower()
        filtered = [
            d for d in DATASETS
            if domain_lower in d["domain"].lower()
            or domain_lower in d["table"].lower()
            or domain_lower in d["name"].lower()
        ]
    return {
        "datasets": [
            {"id": d["id"], "name": d["name"], "table": d["table"], "domain": d["domain"]}
            for d in filtered
        ]
    }


def list_columns(dataset_id: str) -> dict[str, Any]:
    ds = find_dataset(dataset_id)
    if ds is None:
        return {"columns": [], "error": f"Dataset '{dataset_id}' not found. Use list_datasets to see available datasets."}
    return {
        "dataset_id": ds["id"],
        "table": ds["table"],
        "columns": ds["columns"],
        "time_column": ds["time_column"],
        "error": None,
    }
