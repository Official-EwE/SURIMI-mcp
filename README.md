# SURIMI-mcp

MCP server exposing SURIMI fisheries data — EU DCF, OECD, and SURIMI-project tables — over SSE
for any MCP-compatible LLM client (ChatGPT Connectors, Claude.ai, Mistral Chat, opencode, etc.).

Backs against PostgreSQL (default for catalog deploy) or Trino (for partner-DB integration).

## Image

Published to `ghcr.io/official-ewe/surimimcp` by GitHub Actions on every push to `master` and on
version tags (`v*`).

```
docker pull ghcr.io/official-ewe/surimimcp:latest
docker run -p 26610:26610 ghcr.io/official-ewe/surimimcp:latest
```

The image is **public** — no authentication needed to pull.

## Architecture

- `server.py` — FastMCP SSE entry point
- `catalog.py` — dataset registry + lookups
- `trino_client.py` — Trino SQL connector (mode-switchable to PostgreSQL via env)
- `search.py` — `search_documents` tool implementation
- `recipes.py` — `analyze_trend`, `compare_countries`, `generate_report` recipe handlers
- `rag/` — embedding + retrieval over SURIMI project documents
- `data/load_csv.py` — bulk loader, run as a post-install Job in the Helm chart
- `data/init/01-schemas.sql` — schema DDL for the bundled PostgreSQL

## Data

The 13 CSV exports (~86 MB raw, ~5 MB compressed) are **not** stored in this repo. They live on
EDITO MinIO under the shared SURIMI-project bucket. The prefix `surimi-data-dummy` reflects that
the current snapshot is for demo/integration purposes only — not the canonical SURIMI dataset.
Anonymous-pullable:

```
https://minio.dive.edito.eu/project-surimi/surimi-data-dummy/data.tar.gz
```

The Dockerfile fetches + verifies them at build time. To rebuild with a different bundle:

```
docker build \
  --build-arg DATA_TARBALL_URL=https://your-host/data.tar.gz \
  --build-arg DATA_TARBALL_SHA256=<sha256> \
  -t surimimcp .
```

## Deployment

Helm chart lives in the EDITO Onyxia catalog:
`https://datalab.dive.edito.eu/catalog/service-playground`

Source: `gitlab.mercator-ocean.fr/pub/edito-infra/service-playground/charts/surimi-mcp`

## Debugging a stuck or failed deploy

The chart ships a diagnostic script at `/app/scripts/debug-mcp.sh` inside the image.
It dumps helm status, pod descriptions, server logs, load-data Job logs, postgres
logs, and recent namespace events in one shot. Run it from the terminal sidecar
(or any pod with kubectl + helm access to the namespace):

```
kubectl exec -it <surimi-terminal-pod> -- bash /app/scripts/debug-mcp.sh
```

Or copy it out and run from a debugging pod:

```
kubectl cp <surimi-mcp-pod>:/app/scripts/debug-mcp.sh /tmp/debug-mcp.sh
bash /tmp/debug-mcp.sh <release-name>
```

Quick manual checks:

```
helm status <release>                                          # release-level state
kubectl get pod -l app.kubernetes.io/instance=<release>        # pod state
kubectl describe pod <pod>                                     # why pending/crashed
kubectl logs job/<release>-load-data -c load-csv --tail=200 -f # live data-load
kubectl logs -l app.kubernetes.io/instance=<release> -c surimi-mcp --tail=80
kubectl get events --sort-by=.lastTimestamp | tail -20
```

The image sets `PYTHONUNBUFFERED=1` so all `print()` output streams to logs in
real time. No need to wait for the container to finish to see progress.

## Local dev

```
docker compose up -d
# Server on http://localhost:26610/sse
```

Or without Docker:

```
pip install -e .
DATABASE_URL=postgresql://surimi:surimi_mcp_2026@localhost:26613/surimi python server.py
```

## License

Apache-2.0
