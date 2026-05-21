# Building surimi-mcp with GitHub Copilot (VS Code Agent Mode)

Reproducing the full MCP server development using GitHub Copilot in VS Code.
This is the development story for NORCE stakeholders.

## Setup

- VS Code with GitHub Copilot extension (Chat panel)
- Python 3.12+ available in terminal
- Docker installed for containerization
- `helm` + `kubectl` for EDITO deployment

## Prompt sequence (copy-paste into Copilot Chat)

### Phase 1: Project scaffold

**Prompt 1:**
```
@workspace Create a new Python MCP server project in surimi-mcp/ using FastMCP.
The server exposes fisheries and OECD statistical data from a PostgreSQL database.

Create:
- pyproject.toml with deps: fastmcp, trino, psycopg2-binary, pytest
- server.py scaffold with FastMCP on port 26610, SSE transport
- catalog.py with a dataset registry (13 EU fisheries/OECD datasets)
- trino_client.py with a query executor that supports both Trino and PostgreSQL backends
- capabilities.py with a drift-check registry (same pattern as reiselivet innsikt-ssb)

The datasets are:
- hive.oecd.fsedata (wide-format FSE)
- hive.oecd.oecd_fisheries_support_estimates_eu_coastal_states (long-format, year/country_code/direct_transfers_meur/cost_reducing_transfers_meur/general_services_meur)
- hive.eu_dcf.eu_dcf_fisheries_economic_performance_aegean_sea
- hive.eu_dcf.eu_dcf_fisheries_employment_western_mediterranean
- hive.eu_dcf.aer_economic_national_level
- hive.eu_dcf.aer_social_data_2017_2020
- hive.eu_dcf.aer_capacity
- hive.eu_dcf.aer_economic_2013_2023
- hive.eu_dcf.fdi_capacity_by_country
- hive.eu_dcf.fuel
- hive.eu_dcf.rev_grp
- hive.surimi.surimi_empirical_biomass_surveys_western_mediterranean
- hive.surimi.surimi_simulated_sales_output_aegean_sea

Use DB_BACKEND env var to switch between "trino" and "postgres". For postgres, auto-translate hive.schema.table to schema.table.
```

### Phase 2: TDD — Write tests first

**Prompt 2:**
```
@workspace Write pytest tests FIRST (TDD red phase) for the surimi-mcp server:

tests/test_lookups.py:
- test_list_datasets_returns_catalog (at least 5 datasets, each has id/name/table)
- test_list_datasets_filter_by_domain (filter "oecd" returns only OECD datasets)
- test_list_columns_returns_schema (known dataset returns columns with name/type)
- test_list_columns_unknown_dataset_returns_error
- test_find_dataset_by_kebab, by_table_name, by_fqn, partial_match

tests/test_capabilities.py:
- test_capability_registry_not_empty
- test_describe_returns_tool_inventory
- test_drift_check_no_unclaimed, detects_unclaimed, detects_missing

tests/test_fetchers.py (integration, needs live DB):
- test_query_data_with_sql (SELECT from OECD table)
- test_query_data_bad_column_returns_error
- test_describe_table
- test_query_with_self_correction_hint (bad column returns available_columns)

tests/test_recipes.py:
- test_analyze_trend_returns_recipe (has steps, mentions query_data)
- test_compare_countries_returns_recipe
- test_generate_report_returns_recipe
- test_recipe_grounding_rule_present
```

### Phase 3: Implement to pass tests

**Prompt 3:**
```
@workspace The tests are failing (red). Implement catalog.py, capabilities.py, trino_client.py to make them pass. Follow the test expectations exactly. The trino_client.py PostgresClient should translate "hive.schema.table" references to "schema.table" using regex substitution.
```

### Phase 4: Recipe and search tools

**Prompt 4:**
```
@workspace Add two more modules:

recipes.py — three recipe tools that return step-by-step instructions (not data):
- analyze_trend(dataset_id, metric, group_by, period) → steps naming query_data
- compare_countries(dataset_id, metric, countries, period) → steps with SQL
- generate_report(dataset_id, focus, period) → multi-step workflow

Each recipe must include a GROUNDING_RULE string that says:
"Only state facts from tool responses. Never invent numbers. Cite the tool call."

search.py — indicator explanation:
- explain_indicator(indicator, dataset_id) → definition, unit, source
- Static lookup table for key indicators (direct_transfers_meur, employment_fte, biomass_kt, etc.)
- Falls back to checking if the indicator exists as a column in any dataset

Run pytest to verify all tests pass.
```

### Phase 5: Wire tools into server.py

**Prompt 5:**
```
@workspace Wire all modules into server.py as FastMCP tools:

Meta: describe_capabilities
Lookups: list_datasets, list_columns
Fetchers: query_data (accepts SQL string), describe_table
Search: explain_indicator, search_documents (returns empty gracefully if RAG unavailable)
Recipes: analyze_trend, compare_countries, generate_report

Register capabilities for each data source with drift-check at startup.
Add grounding rule to the tool descriptions.
Total should be 10 tools.
```

### Phase 6: Docker + data export

**Prompt 6:**
```
@workspace Create:
1. Dockerfile — python:3.12-slim, install fastmcp+trino+psycopg2-binary, copy source + data/
2. docker-compose.yml — postgres:16-alpine on port 26613 + surimi-mcp on port 26610
3. data/load_csv.py — script that auto-creates tables from CSV headers and bulk-loads rows
4. .dockerignore — exclude .venv, tests, __pycache__

The CSVs are exported from Trino and live in data/exports/. The loader should:
- Create schemas (oecd, eu_dcf, surimi)
- DROP TABLE IF EXISTS, CREATE TABLE with all TEXT columns (from CSV headers)
- INSERT in batches of 10000
- Print per-table row counts
```

### Phase 7: Helm chart for EDITO

**Prompt 7:**
```
@workspace Create a Helm chart at deploy/helm/surimi-mcp/ for deploying to EDITO Kubernetes:
- Chart.yaml (name: surimi-mcp, version 0.1.0)
- values.yaml (image from registry.norce.dev, port 26610, ingress enabled at surimi-mcp.lab.dive.edito.eu)
- templates/deployment.yaml, service.yaml, ingress.yaml, _helpers.tpl

The deployment needs env vars: DB_BACKEND, DATABASE_URL (passed via --set)
Support imagePullSecrets for private registry.
Liveness probe on /sse endpoint.
```

### Phase 8: Deploy and verify

**Terminal commands (not Copilot — manual):**
```bash
# Build and push
docker build -t surimi-mcp:latest .
docker tag surimi-mcp:latest registry.norce.dev/hasv/surimi-edito/surimi-mcp:0.3.0
docker push registry.norce.dev/hasv/surimi-edito/surimi-mcp:0.3.0

# On EDITO pod:
helm upgrade --install surimi-db bitnami/postgresql ...
helm upgrade --install surimi-mcp ./deploy/helm/surimi-mcp ...
kubectl exec deploy/surimi-mcp -- python /app/data/load_csv.py

# Verify:
curl https://surimi-mcp.lab.dive.edito.eu/sse
```

## Timeline for demo

| Phase | What Copilot does | Time |
|-------|-------------------|------|
| 1 | Scaffolds project structure | 2 min |
| 2 | Generates test suite (TDD red) | 3 min |
| 3 | Implements modules to pass tests | 5 min |
| 4 | Adds recipes + search | 3 min |
| 5 | Wires into FastMCP server | 2 min |
| 6 | Docker + data pipeline | 3 min |
| 7 | Helm chart | 2 min |
| 8 | Deploy (terminal) | 5 min |
| **Total** | | **~25 min** |

## Key talking points

1. **TDD workflow** — tests written first, implementation follows. Copilot does both.
2. **Vendor-neutral** — MCP server works with any client (Copilot, ChatGPT, Claude, custom).
3. **Self-contained** — PostgreSQL + CSV data, no external dependencies except the database.
4. **Production-ready patterns** — capability drift-check, grounding rules, error handling with schema hints.
5. **Fast iteration** — from zero to deployed MCP server in under 30 minutes with AI assistance.
