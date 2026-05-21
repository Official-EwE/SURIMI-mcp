"""SURIMI MCP server. Exposes fisheries/OECD data from Trino via FastMCP.

Architecture follows the reiselivet innsikt-ssb pattern: tiered tools
(meta → lookups → fetchers → search → recipes), capability registry with
drift-check, grounding rules in every recipe response.
"""
import json
from typing import Optional

from fastmcp import FastMCP

import capabilities
import catalog
import recipes
import search
try:
    from rag import search as rag_search
except ImportError:
    rag_search = None
from trino_client import TrinoClient, default_client

PORT = 26610
HOST = "0.0.0.0"
PATH = "/sse"
mcp = FastMCP("SURIMI Fisheries & OECD Data")

_trino: TrinoClient | None = None


def _get_trino() -> TrinoClient:
    global _trino
    if _trino is None:
        _trino = default_client()
    return _trino


def _log(msg: str) -> None:
    print(f"[surimi-mcp] {msg}", flush=True)


# ── Capability registry ──

capabilities.register(capabilities.DataSourceCapability(
    source_id="eu-dcf",
    title="EU Data Collection Framework — fisheries economics, employment, capacity, fuel",
    domain="fisheries",
    description="Multiple EU DCF tables covering economic performance, employment, fleet capacity, and fuel efficiency across Mediterranean and EU coastal states.",
    coverage={"temporal": "2013–2023", "tables": 8},
    tools=("list_datasets", "list_columns", "query_data", "describe_table"),
))

capabilities.register(capabilities.DataSourceCapability(
    source_id="oecd-fse",
    title="OECD Fisheries Support Estimates",
    domain="policy",
    description="Government support to fisheries — direct transfers, cost-reducing transfers, and general services. Long-format (per-country, per-year) and wide-format (FSE category breakdown).",
    coverage={"temporal": "2000–2022", "tables": 2},
    tools=("query_data", "describe_table"),
))

capabilities.register(capabilities.DataSourceCapability(
    source_id="surimi-model",
    title="SURIMI simulation outputs",
    domain="modelling",
    description="Empirical biomass surveys and simulated sales from the SURIMI ecological model.",
    coverage={"temporal": "varies", "tables": 2},
    tools=("query_data", "describe_table"),
))

capabilities.register(capabilities.DataSourceCapability(
    source_id="indicators",
    title="Indicator definitions and metadata",
    domain="reference",
    description="Definitions, units, and sources for fisheries indicators.",
    tools=("explain_indicator",),
    coverage={},
))

capabilities.register(capabilities.DataSourceCapability(
    source_id="documents",
    title="SURIMI project documents",
    domain="reference",
    description=(
        "Hybrid search (dense + BM25 + reranker) over SURIMI project documents: "
        "grant agreement, protocol specs, Ecopath model docs, data lake docs, project wiki."
    ),
    tools=("search_documents",),
    coverage={"documents": "~80 files from references/"},
))

capabilities.register(capabilities.DataSourceCapability(
    source_id="recipes",
    title="Guided analysis recipes",
    domain="analysis",
    description="Multi-step analysis workflows that name exact tools to call.",
    tools=("analyze_trend", "compare_countries", "generate_report"),
    coverage={},
))

capabilities.register(capabilities.DataSourceCapability(
    source_id="meta",
    title="Self-description",
    domain="meta",
    description="Capability introspection for client discovery.",
    tools=("describe_capabilities",),
    coverage={},
))


# ── Meta tools ──

@mcp.tool()
async def describe_capabilities() -> dict:
    """List all data sources, tools, and usage hints for this MCP server."""
    _log("[meta] describe_capabilities")
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    return capabilities.describe(tool_names)


# ── Lookup tools ──

@mcp.tool()
def list_datasets(domain: Optional[str] = None) -> dict:
    """List available datasets. Optionally filter by domain (e.g. 'oecd', 'eu_dcf', 'surimi', 'fisheries')."""
    _log(f"[lookup] list_datasets domain={domain}")
    return catalog.list_datasets(domain=domain)


@mcp.tool()
def list_columns(dataset_id: str) -> dict:
    """Show columns and types for a dataset. Accepts kebab-case ID, table name, or Trino FQN."""
    _log(f"[lookup] list_columns dataset_id={dataset_id}")
    return catalog.list_columns(dataset_id=dataset_id)


# ── Fetcher tools ──

@mcp.tool()
def query_data(
    sql: str,
    limit: int = 500,
) -> dict:
    """Execute a SQL query against Trino. Returns rows as JSON.

    Use SHOW COLUMNS FROM <table> to discover column names first.
    Dot-notation columns (e.g. "country.code") must be double-quoted in SQL.
    On column errors, returns available_columns for self-correction.
    """
    _log(f"[fetcher] query_data sql={sql[:80]}...")
    client = _get_trino()
    return client.execute(sql, limit=limit)


@mcp.tool()
def describe_table(table: str) -> dict:
    """Show columns and types for a Trino table (e.g. 'hive.oecd.fsedata')."""
    _log(f"[fetcher] describe_table table={table}")
    client = _get_trino()
    return client.describe_table(table)


# ── Search tools ──

@mcp.tool()
def explain_indicator(
    indicator: str,
    dataset_id: Optional[str] = None,
) -> dict:
    """Explain what a data indicator/column means — definition, unit, source."""
    _log(f"[search] explain_indicator indicator={indicator}")
    return search.explain_indicator(indicator, dataset_id=dataset_id)


@mcp.tool()
def search_documents(
    query: str,
    top_k: int = 5,
) -> dict:
    """Search SURIMI project documents (grant agreement, protocols, wiki, model docs).

    Returns ranked passages with source attribution. Use for policy context,
    methodology definitions, or background that the data tables don't contain.
    """
    _log(f"[search] search_documents query={query[:60]}...")
    if rag_search is None:
        return {"query": query, "results": [], "count": 0, "rag_available": False}
    results = rag_search.search(query, top_k=top_k)
    return {
        "query": query,
        "results": results,
        "count": len(results),
        "rag_available": rag_search.is_available(),
    }


# ── Recipe tools ──

@mcp.tool()
def analyze_trend(
    dataset_id: str,
    metric: str,
    group_by: Optional[str] = None,
    period: Optional[str] = None,
) -> dict:
    """Get a step-by-step recipe for analyzing a metric's trend over time.

    Returns instructions naming exact tools to call. Follow the steps in order.
    """
    _log(f"[recipe] analyze_trend dataset={dataset_id} metric={metric}")
    return recipes.analyze_trend(dataset_id, metric, group_by=group_by, period=period)


@mcp.tool()
def compare_countries(
    dataset_id: str,
    metric: str,
    countries: list[str],
    period: Optional[str] = None,
) -> dict:
    """Get a step-by-step recipe for comparing a metric across countries.

    Returns instructions naming exact tools to call. Follow the steps in order.
    """
    _log(f"[recipe] compare_countries dataset={dataset_id} metric={metric} countries={countries}")
    return recipes.compare_countries(dataset_id, metric, countries=countries, period=period)


@mcp.tool()
def generate_report(
    dataset_id: str,
    focus: str,
    period: Optional[str] = None,
) -> dict:
    """Get a step-by-step recipe for generating an insight report on a dataset.

    Returns instructions naming exact tools to call. Follow the steps in order.
    """
    _log(f"[recipe] generate_report dataset={dataset_id} focus={focus}")
    return recipes.generate_report(dataset_id, focus, period=period)


# ── Startup ──

if __name__ == "__main__":
    import asyncio

    if rag_search is not None:
        _log("warming RAG search...")
        rag_search.warmup()
    else:
        _log("RAG not available (sentence-transformers not installed)")

    _log("running capabilities drift check...")
    _tools = asyncio.run(mcp.list_tools())
    _drift = capabilities.drift_check({t.name for t in _tools})
    if _drift["missing_from_registry"]:
        _log(f"WARN drift: tools not claimed by any source: {_drift['missing_from_registry']}")
    if _drift["missing_from_fastmcp"]:
        _log(f"WARN drift: claimed tools missing from FastMCP: {_drift['missing_from_fastmcp']}")
    if not _drift["missing_from_registry"] and not _drift["missing_from_fastmcp"]:
        _log(f"drift check OK ({len(_tools)} tools, {len(capabilities.all_capabilities())} sources)")

    _log(f"starting MCP server on {HOST}:{PORT}{PATH}")
    mcp.run(transport="sse", host=HOST, port=PORT, path=PATH)
