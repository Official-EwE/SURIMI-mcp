"""Capability registry with drift-check. Ported from reiselivet innsikt-ssb."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DataSourceCapability:
    source_id: str
    title: str
    domain: str
    description: str
    coverage: dict[str, Any]
    tools: tuple[str, ...]


_REGISTRY: list[DataSourceCapability] = []


def register(spec: DataSourceCapability) -> None:
    global _REGISTRY
    _REGISTRY = [c for c in _REGISTRY if c.source_id != spec.source_id]
    _REGISTRY.append(spec)


def all_capabilities() -> list[DataSourceCapability]:
    return list(_REGISTRY)


def claimed_tools() -> set[str]:
    return {t for cap in _REGISTRY for t in cap.tools}


def describe(tool_names: list[str]) -> dict[str, Any]:
    return {
        "data_sources": [asdict(c) for c in _REGISTRY],
        "tool_inventory": {
            "total": len(tool_names),
            "layers": _bucket_by_layer(tool_names),
            "by_domain": _bucket_by_domain(tool_names),
        },
        "usage_hint": (
            "Call list_datasets to discover available data. "
            "Call list_columns to see a dataset's schema. "
            "Call query_data for direct SQL or column-based queries. "
            "Call recipe tools (analyze_trend, compare_countries, generate_report) "
            "for guided multi-step analysis."
        ),
    }


def drift_check(registered_tool_names: set[str]) -> dict[str, list[str]]:
    claimed = claimed_tools()
    return {
        "missing_from_registry": sorted(registered_tool_names - claimed),
        "missing_from_fastmcp": sorted(claimed - registered_tool_names),
    }


def _classify(name: str) -> str:
    if name == "describe_capabilities":
        return "meta"
    if name.startswith("list_"):
        return "lookup"
    if name.startswith("query_") or name.startswith("describe_"):
        return "fetcher"
    if name.startswith("search_") or name == "explain_indicator":
        return "search"
    return "recipe"


def _bucket_by_layer(tool_names: list[str]) -> dict[str, list[str]]:
    layers: dict[str, list[str]] = {
        "meta": [], "lookup": [], "fetcher": [], "search": [], "recipe": [],
    }
    for name in tool_names:
        layers.setdefault(_classify(name), []).append(name)
    return layers


def _bucket_by_domain(tool_names: list[str]) -> dict[str, list[str]]:
    by_domain: dict[str, list[str]] = {}
    for cap in _REGISTRY:
        for t in cap.tools:
            by_domain.setdefault(cap.domain, []).append(t)
    unclaimed = [t for t in tool_names if t not in claimed_tools()]
    if unclaimed:
        by_domain["_unclaimed"] = unclaimed
    return by_domain
