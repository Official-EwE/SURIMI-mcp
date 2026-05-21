"""Recipe tools for guided multi-step analysis.

Recipes return structured instructions that name exact tools for the LLM to
call. The LLM follows the recipe step-by-step, calling tools and building
the narrative from their results. Same pattern as reiselivet's insight recipes.
"""
from __future__ import annotations

from typing import Any, Optional

from catalog import find_dataset

GROUNDING_RULE = """GROUNDING RULE — strict. You are a data tool, not an oracle.
- Only state facts that came from a tool response in THIS conversation.
- If a tool returned an error, null, zero, or empty result, say so explicitly.
- Never invent numbers. Never extrapolate beyond the data returned.
- Cite the tool call that produced each number.
- If the user asks about a topic not covered by any tool, say "This is outside the data I have access to."
- Separate clearly what is DATA (from tools) and what is your INTERPRETATION."""


def analyze_trend(
    dataset_id: str,
    metric: str,
    group_by: Optional[str] = None,
    period: Optional[str] = None,
) -> dict[str, Any]:
    ds = find_dataset(dataset_id)
    if ds is None:
        return {"error": f"Dataset '{dataset_id}' not found.", "steps": [], "grounding": GROUNDING_RULE}

    table = ds["table"]
    time_col = ds["time_column"]
    group_clause = f", {group_by}" if group_by else ""
    where_clause = f"WHERE {time_col} >= '{period}'" if period else ""

    steps = [
        f"Step 1: Call query_data with SQL: SELECT {time_col}{group_clause}, {metric} FROM {table} {where_clause} ORDER BY {time_col}",
        f"Step 2: Examine the returned rows. Identify the overall direction (increasing, decreasing, stable).",
        f"Step 3: Note any outliers or inflection points — years where {metric} changed sharply.",
        f"Step 4: If group_by is set, compare groups. Which group has the highest/lowest {metric}?",
        f"Step 5: Write a 2-3 sentence summary. State the trend, the range of values, and any notable changes. Cite the data.",
    ]

    return {
        "dataset": ds["id"],
        "table": table,
        "metric": metric,
        "steps": steps,
        "grounding": GROUNDING_RULE,
    }


def compare_countries(
    dataset_id: str,
    metric: str,
    countries: list[str],
    period: Optional[str] = None,
) -> dict[str, Any]:
    ds = find_dataset(dataset_id)
    if ds is None:
        return {"error": f"Dataset '{dataset_id}' not found.", "steps": [], "grounding": GROUNDING_RULE}

    table = ds["table"]
    time_col = ds["time_column"]
    country_list = ", ".join(f"'{c}'" for c in countries)
    where_clause = f"WHERE country_code IN ({country_list})"
    if period:
        where_clause += f" AND {time_col} = '{period}'"

    steps = [
        f"Step 1: Call query_data with SQL: SELECT country_code, {time_col}, {metric} FROM {table} {where_clause} ORDER BY {metric} DESC",
        f"Step 2: Rank the countries by {metric}. State the highest and lowest.",
        f"Step 3: Calculate the ratio between highest and lowest — how large is the gap?",
        f"Step 4: If multiple years are returned, note whether the ranking changed over time.",
        f"Step 5: Write a 2-3 sentence comparative summary. Cite exact numbers from the query.",
    ]

    return {
        "dataset": ds["id"],
        "table": table,
        "metric": metric,
        "countries": countries,
        "steps": steps,
        "grounding": GROUNDING_RULE,
    }


def generate_report(
    dataset_id: str,
    focus: str,
    period: Optional[str] = None,
) -> dict[str, Any]:
    ds = find_dataset(dataset_id)
    if ds is None:
        return {"error": f"Dataset '{dataset_id}' not found.", "steps": [], "grounding": GROUNDING_RULE}

    table = ds["table"]
    numeric_cols = [c["name"] for c in ds["columns"] if c["type"] in ("float", "int", "double")]
    col_list = ", ".join(numeric_cols[:3]) if numeric_cols else "*"

    steps = [
        f"Step 1: Call list_columns for dataset '{ds['id']}' to confirm the available columns.",
        f"Step 2: Call query_data with SQL: SELECT * FROM {table} LIMIT 5 — inspect the data shape.",
        f"Step 3: Call query_data to fetch key metrics: SELECT country_code, {col_list} FROM {table} ORDER BY {numeric_cols[0] if numeric_cols else 'year'} DESC LIMIT 20",
        f"Step 4: Call explain_indicator for each metric column to understand definitions and units.",
        f"Step 5: Write the report with sections: Overview, Key Findings (with numbers), Comparison, Limitations.",
        f"Step 6: Every number must cite the query_data call that produced it. Mark any interpretation clearly.",
    ]

    return {
        "dataset": ds["id"],
        "table": table,
        "focus": focus,
        "steps": steps,
        "grounding": GROUNDING_RULE,
    }
