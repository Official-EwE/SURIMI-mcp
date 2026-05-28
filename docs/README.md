# Using surimi-mcp

A live MCP server that exposes EU fisheries datasets and SURIMI project documents to any MCP-compatible LLM client. After you connect, you can ask plain-English questions and the model picks the right tool, runs the query, and replies with cited data.

This doc covers: getting the URL, connecting from each supported client, what the 10 tools do, the cold-start window, and what to do when things break.

## At a glance

| | |
|---|---|
| Server (SSE) | `https://<your-host>/sse` |
| Status (JSON) | `https://<your-host>/status` |
| Web terminal | `https://<your-host>/` |
| Tools | 10 (1 meta, 2 lookup, 2 fetcher, 2 search, 3 recipe) |
| Data | 13 tables, ~770K rows, EU DCF + OECD + SURIMI |
| Cold start | ~30 s server up, ~15 min full data load |

Your host comes from the EDITO Onyxia launch (e.g. `user-yourname-123456-0.lab.dive.edito.eu`). Look at the NOTES output of the running service for the exact value.

## 1. Connect from your LLM client

Replace `YOUR-HOST` in every snippet below with the host from your launch.

### Claude Desktop

Edit `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "surimi": {
      "transport": {
        "type": "sse",
        "url": "https://YOUR-HOST/sse"
      }
    }
  }
}
```

Restart Claude Desktop. The 10 SURIMI tools appear under the tools icon in the chat input.

### Cursor

Settings → Cursor Settings → MCP → "Add new MCP server".

```json
{
  "mcpServers": {
    "surimi": {
      "url": "https://YOUR-HOST/sse"
    }
  }
}
```

### Continue.dev (VS Code / JetBrains)

`~/.continue/config.json`:

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "sse",
          "url": "https://YOUR-HOST/sse"
        }
      }
    ]
  }
}
```

### Cline (VS Code)

Open the Cline panel, click the MCP icon, "Add Server", select SSE, paste `https://YOUR-HOST/sse`.

### opencode (CLI)

`~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "remote": [
      { "name": "surimi", "url": "https://YOUR-HOST/sse" }
    ]
  }
}
```

Proven working with vLLM + Qwen3-Coder-30B-A3B on EDITO (see Official-EwE/SURIMI-vllm chart).

### GitHub Copilot (VS Code, MCP preview)

Add to repo or user settings (`.vscode/mcp.json`):

```json
{
  "servers": {
    "surimi": {
      "type": "sse",
      "url": "https://YOUR-HOST/sse"
    }
  }
}
```

### ChatGPT Plus

Direct MCP is not supported by ChatGPT Plus. Two options:

1. Build a Custom GPT with an Action that targets a REST gateway in front of surimi-mcp.
2. Use one of the clients above (Claude Desktop is the easiest swap).

### Codex CLI

Not working today. Codex uses OpenAI's Responses API, which does not speak the MCP tool-calling protocol. Use opencode CLI instead, which is a drop-in replacement.

## 2. The tools

Tools are auto-discovered as soon as the SSE handshake completes (~30 s after launch). You do not need to know the names; just ask questions.

### Tabular SQL tools (10)

| Tool | Purpose | Try saying |
|---|---|---|
| `describe_capabilities` | What this server can do | "What can the SURIMI server help me with?" |
| `list_datasets` | List 13 datasets (filter by domain) | "What fisheries datasets are available?" |
| `list_columns` | Show columns of one dataset | "Show me columns of fdi_capacity_by_country" |
| `query_data` | Run SQL, returns rows | "How many fishing vessels does Greece have?" |
| `describe_table` | Schema by Trino FQN | "Describe hive.eu_dcf.aer_capacity" |
| `explain_indicator` | Definition of a metric | "What does f_fmsy mean?" |
| `search_documents` | RAG over SURIMI documents | "What are the SURIMI grant objectives?" |
| `analyze_trend` | Recipe for trend analysis | "Trend of employment in Western Med" |
| `compare_countries` | Recipe for country comparison | "Compare fuel cost Spain vs Italy" |
| `generate_report` | Recipe for full insight report | "Generate a report on Aegean economics" |

Recipe tools return a step-by-step plan that names other tools to call. The LLM follows the recipe automatically.

### NetCDF tools (11)

Open-time introspection (unsigned) and analytical primitives (signed with HMAC receipts).

| Tool | Purpose | Try saying |
|---|---|---|
| `nc_describe_file` | Full structure (dims, vars, sha256) | "Describe the EcoOcean file" |
| `nc_list_variables` | Variables with shapes and units | "What variables are in this file?" |
| `nc_get_time_range` | Start/end of the time axis | "How long does this dataset cover?" |
| `nc_get_spatial_bounds` | Lat/lon extents and grid size | "What region is in this file?" |
| `nc_check_cf_compliance` | CF-conventions check | "Is this file CF-compliant?" |
| `nc_get_coverage_summary` | NaN counts per variable | "How much data is missing?" |
| `nc_top_regions` | Top-N regions by aggregated value (signed) | "Top 3 regions by mean biomass in 2010" |
| `nc_time_series` | Aggregated value per timestep in one region (signed) | "Show the biomass trend in the Humboldt LME" |
| `nc_compare_periods` | Diff/ratio between two time ranges per region (signed) | "Compare 1990-2000 vs 2000-2010" |
| `nc_trend` | Mann-Kendall trend slope + p-value (signed) | "Is biomass declining in the Aegean?" |
| `nc_verify` | Re-check an HMAC receipt | (called automatically when you click a number) |

Every analytical tool returns `{value, receipt}`. The receipt contains a cryptographic signature over `{tool_id, input_params, output_value, provenance, timestamp}`. Verify with `nc_verify(receipt)` to confirm the answer came from a real tool call and was not tampered with.

## 3. Trust: signed receipts and the verify pattern

Analytical tools produce numbers. Numbers can be hallucinated, paraphrased, or silently corrupted. To make the assistant auditable, every numeric output carries an HMAC-SHA256 signed receipt.

**The receipt envelope:**

```json
{
  "version": 1,
  "tool_id": "nc_top_regions",
  "input_params": { "file": "s3://...", "var": "bd30cm", "n": 3, "agg": "mean" },
  "output_value": [{"region": "Humboldt", "value": 18.4}],
  "provenance": {
    "file_sha256": "8291...",
    "mask_sha256": "70a9...",
    "var": "bd30cm",
    "agg": "mean"
  },
  "timestamp": "2026-05-26T13:42:00Z",
  "signature": "acc21658f4059fba..."
}
```

**To verify a receipt** from any client:

```python
import requests
r = requests.post(
    "https://YOUR-HOST/sse",
    json={"method": "tools/call",
          "params": {"name": "nc_verify", "arguments": {"receipt": ...}}},
)
# returns {"verified": true, "reason": "ok"} or {..., "reason": "signature_mismatch"}
```

Tampering with any field, including provenance hashes, invalidates the signature. The server holds the secret; the LLM cannot forge.

Pattern reference: [Tool Receipts, Not Zero-Knowledge Proofs](https://arxiv.org/pdf/2603.10060).

## 4. Cold-start timeline

Knowing this avoids spending 10 minutes assuming the server is broken when it is just warming up.

| Time | What works |
|---|---|
| 0 to 30 s | Pod starting. `/sse` returns 503 or refuses connection. |
| 30 s to 1 min | Server live. Tools appear in your client. Metadata-only tools work: `list_datasets`, `describe_capabilities`, `list_columns`, `explain_indicator`, `search_documents`. |
| 1 to 15 min | Data load Job runs. `query_data` returns partial results that grow as tables finish. Poll `/status` every minute to see the count. |
| 15 min onwards | All 13 tables loaded. Full functionality. |

`/status` returns JSON like:

```json
{
  "ready": false,
  "tables": { "loaded": 8, "total": 13, "missing": ["aer_capacity", "rev_grp", ...] },
  "rows": 367241,
  "details": [ { "table": "fuel", "rows": 12451 }, ... ]
}
```

When `"ready": true` and `tables.missing` is empty, you are good to go.

## 5. First five prompts to try

Once `/status` shows ready, paste any of these into your client:

1. "List the SURIMI datasets you have, grouped by domain."
2. "Show the fishing vessel capacity trend in Greece since 2013."
3. "Compare fuel cost between Spain, Italy, and Greece, latest year."
4. "What does the f_fmsy indicator mean and which dataset has it?"
5. "Search the SURIMI documents for climate scenario assumptions."

## 6. Datasets in the catalog

Three schemas, 13 tables, ~770K rows total.

**OECD (2):** fisheries support estimates EU coastal states; FSE data (wide format).

**EU DCF (9):** AER economic 2013-2023, AER economic national level, AER social data 2017-2020, AER capacity, FDI capacity by country, fuel, revenue groups, fisheries economic performance Aegean, fisheries employment Western Med.

**SURIMI (2):** simulated sales output Aegean, empirical biomass surveys Western Med.

Ask `list_datasets` for the full registry with descriptions.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| 404 on `/sse` | Pod still starting, or wrong path | Wait 30 s, verify `/status` returns JSON |
| Client shows no tools | SSE handshake failed | `curl -N https://YOUR-HOST/sse` should keep streaming; if it 404s, check the ingress |
| `query_data` returns "table missing" | Data load still running | Check `/status`, wait for table to appear in `details` |
| Wrong column name error | LLM hallucinated a name | `query_data` returns `available_columns`; the LLM uses it to self-correct on next call |
| Stuck deploy | Image pull / quota | Open the web terminal sidebar, run `bash /app/scripts/debug-mcp.sh <release-name>` |
| `describe_capabilities` returns generic text | RAG index not yet built into image | Non-fatal; data tools still work |

## 8. Privacy and quotas

This MCP server reads from a public bundled PostgreSQL inside your namespace. Nothing you query is logged off-cluster. The data itself is open (OECD, EU DCF, SURIMI public outputs).

The chart consumes ~2 vCPU, ~3 Gi RAM, ~3 Gi disk in your namespace. Stop the service when you are done to free quota.

## 9. Source

- Image: https://github.com/Official-EwE/SURIMI-mcp
- Chart: https://gitlab.mercator-ocean.fr/pub/edito-infra/service-playground/-/tree/feat/surimi-mcp/surimi-mcp
- Companion vLLM chart: https://github.com/Official-EwE/SURIMI-vllm
- Companion terminal sidecar: https://github.com/Official-EwE/SURIMI-terminal

For the development walkthrough (how this MCP was built with GitHub Copilot), see [copilot-development-walkthrough.md](copilot-development-walkthrough.md).

For a 1-page printable cheatsheet for workshop attendees, see [workshop-cheatsheet.md](workshop-cheatsheet.md).
