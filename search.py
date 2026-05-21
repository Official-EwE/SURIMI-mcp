"""Indicator explanation and document search for SURIMI MCP."""
from __future__ import annotations

from typing import Any, Optional

from catalog import DATASETS


_INDICATOR_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "direct_transfers_meur": {
        "definition": "Direct government transfers to the fisheries sector, measured in millions of EUR.",
        "unit": "million EUR",
        "source": "OECD Fisheries Support Estimates",
    },
    "cost_reducing_transfers_meur": {
        "definition": "Government transfers that reduce the cost of fisheries inputs (fuel, gear, etc.), in millions of EUR.",
        "unit": "million EUR",
        "source": "OECD Fisheries Support Estimates",
    },
    "general_services_meur": {
        "definition": "Government expenditure on general services benefiting the fisheries sector (research, management, enforcement), in millions of EUR.",
        "unit": "million EUR",
        "source": "OECD Fisheries Support Estimates",
    },
    "employment_fte": {
        "definition": "Employment in the fisheries sector measured in full-time equivalents.",
        "unit": "FTE",
        "source": "EU Data Collection Framework (DCF)",
    },
    "gross_revenue_meur": {
        "definition": "Total gross revenue from fisheries operations, in millions of EUR.",
        "unit": "million EUR",
        "source": "EU DCF Economic Performance",
    },
    "operating_cost_meur": {
        "definition": "Total operating costs of fisheries operations, in millions of EUR.",
        "unit": "million EUR",
        "source": "EU DCF Economic Performance",
    },
    "gross_value_added_meur": {
        "definition": "Gross value added by the fisheries sector (revenue minus intermediate consumption), in millions of EUR.",
        "unit": "million EUR",
        "source": "EU DCF Economic Performance",
    },
    "profit_margin": {
        "definition": "Net profit as a percentage of revenue for fisheries operations.",
        "unit": "ratio (0-1)",
        "source": "EU DCF Economic Performance",
    },
    "gender_balance_ratio": {
        "definition": "Ratio of female to total employment in the fisheries sector.",
        "unit": "ratio (0-1)",
        "source": "EU DCF Employment Data",
    },
    "biomass_kt": {
        "definition": "Estimated fish stock biomass from survey data, in thousands of tonnes.",
        "unit": "kilotonnes (kt)",
        "source": "SURIMI Empirical Biomass Surveys",
    },
    "cv_uncertainty": {
        "definition": "Coefficient of variation measuring uncertainty in the biomass estimate.",
        "unit": "ratio",
        "source": "SURIMI Empirical Biomass Surveys",
    },
    "quantity_kt": {
        "definition": "Quantity of fish sold, in thousands of tonnes.",
        "unit": "kilotonnes (kt)",
        "source": "SURIMI Simulated Sales",
    },
    "price_eur_per_kg": {
        "definition": "Average fish sale price in EUR per kilogram.",
        "unit": "EUR/kg",
        "source": "SURIMI Simulated Sales",
    },
    "value_meur": {
        "definition": "Total sales value in millions of EUR.",
        "unit": "million EUR",
        "source": "SURIMI Simulated Sales",
    },
    "fuel_efficiency": {
        "definition": "Ratio of fuel cost to total revenue, indicating fuel dependency.",
        "unit": "ratio",
        "source": "EU DCF Fuel Costs",
    },
}


def explain_indicator(
    indicator: str,
    dataset_id: Optional[str] = None,
) -> dict[str, Any]:
    indicator_lower = indicator.lower().strip()

    if indicator_lower in _INDICATOR_DESCRIPTIONS:
        info = _INDICATOR_DESCRIPTIONS[indicator_lower]
        ds_id = _find_dataset_for_indicator(indicator_lower, dataset_id)
        return {
            "indicator": indicator,
            "found": True,
            "definition": info["definition"],
            "unit": info["unit"],
            "source": info["source"],
            "dataset_id": ds_id,
        }

    ds_id = _find_dataset_for_indicator(indicator_lower, dataset_id)
    if ds_id:
        return {
            "indicator": indicator,
            "found": True,
            "definition": f"Column '{indicator}' exists in dataset '{ds_id}'. No detailed description available.",
            "unit": "unknown",
            "source": "Dataset catalog",
            "dataset_id": ds_id,
        }

    return {
        "indicator": indicator,
        "found": False,
        "definition": None,
        "unit": None,
        "source": None,
        "dataset_id": None,
    }


def _find_dataset_for_indicator(
    indicator: str,
    preferred_dataset_id: Optional[str] = None,
) -> Optional[str]:
    if preferred_dataset_id:
        for ds in DATASETS:
            if ds["id"] == preferred_dataset_id:
                if any(c["name"] == indicator for c in ds["columns"]):
                    return ds["id"]

    for ds in DATASETS:
        if any(c["name"] == indicator for c in ds["columns"]):
            return ds["id"]

    return None
