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
    title="Self-description and receipt verification",
    domain="meta",
    description="Capability introspection for client discovery, and receipt verification.",
    tools=("describe_capabilities", "verify"),
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

# NOTE: there is no unsigned query_data tool. The only SQL path is the signed
# query_data below (registered near the netcdf tools), so every numeric result
# the LLM can surface carries an HMAC receipt. Trust is not optional.


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


# ── Receipt verify ──
# NetCDF/gridded ocean-data tools moved to the separate surimi-netcdf-mcp
# server (DB-free, S3-only). This server is tabular fisheries data only;
# both share SURIMI_RECEIPT_SECRET so receipts verify identically.

from receipts import verify_receipt as _verify_receipt


@mcp.tool(name="verify")
def verify(receipt: dict) -> dict:
    """Verify a signed receipt against this server's secret.

    Returns {verified: bool, reason: str}. Never raises on signature mismatch.
    Works on any SURIMI receipt (this server's query_data, or the
    surimi-netcdf-mcp tools) since both share SURIMI_RECEIPT_SECRET.
    """
    import os
    raw = os.environ.get("SURIMI_RECEIPT_SECRET", "")
    if not raw:
        return {"verified": False, "reason": "secret_not_configured"}
    return _verify_receipt(receipt, secret=raw.encode("utf-8"))


# ── Signed SQL tool ──

from sql_tools import make_query_data_signed

_query_data_signed = make_query_data_signed(
    client_factory=_get_trino,
    backend_id="trino://hive@127.0.0.1:8081",
)


@mcp.tool(name="query_data")
def query_data(sql: str, limit: int = 500) -> dict:
    """Execute a SQL query against Trino. Returns {value, receipt}.

    value holds rows/columns (and available_columns on a column error, for
    self-correction). receipt is an HMAC signature over the inputs+output so
    any number can be re-verified with the `verify` tool. Use SHOW COLUMNS FROM
    <table> to discover names; double-quote dot-notation columns.
    """
    _log(f"[fetcher signed] query_data sql={sql[:80]}...")
    return _query_data_signed(sql=sql, limit=limit)


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

    import uvicorn
    from app_factory import build_asgi_app

    _log(f"starting MCP server on {HOST}:{PORT} (streamable-http at /mcp, sse at /sse)")
    app = build_asgi_app(mcp, http_path="/mcp", sse_path="/sse")
    uvicorn.run(app, host=HOST, port=PORT)
