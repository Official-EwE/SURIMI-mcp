FROM python:3.12-slim

LABEL org.opencontainers.image.title="SURIMI-mcp"
LABEL org.opencontainers.image.description="SURIMI fisheries-data MCP server. Exposes 10 tools (list_datasets, list_columns, query_data, describe_table, explain_indicator, search_documents, analyze_trend, compare_countries, generate_report, describe_capabilities) over SSE for any MCP-compatible LLM client. Backs against PostgreSQL or Trino. CSV data bundle is fetched from EDITO MinIO at build time (not baked into source)."
LABEL org.opencontainers.image.source="https://github.com/Official-EwE/SURIMI-mcp"
LABEL org.opencontainers.image.url="https://www.surimi-project.eu/"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.vendor="SURIMI Project"
LABEL org.opencontainers.image.documentation="https://www.surimi-project.eu/"

WORKDIR /app

# Runtime deps. curl is needed for the data fetch below; kept because chart's load-data Job re-fetches.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir fastmcp trino psycopg2-binary

# Code: server, tools, loader, schemas
COPY capabilities.py catalog.py trino_client.py search.py recipes.py server.py ./
COPY data/load_csv.py data/load_csv.py
COPY data/init/ data/init/

# Data: CSVs come from MinIO, not from this repo (per Rik's "data != image" rule).
# Override at build time:  docker build --build-arg DATA_TARBALL_URL=... --build-arg DATA_TARBALL_SHA256=...
ARG DATA_TARBALL_URL=https://minio.dive.edito.eu/project-surimi/surimi-data/data.tar.gz
ARG DATA_TARBALL_SHA256=5a44dc6c05a65a6ee342b5f7387f1b4a50f4b801b5cd9394f52552baf086f39c
RUN mkdir -p data/exports \
    && curl -fsSL "$DATA_TARBALL_URL" -o /tmp/data.tar.gz \
    && echo "$DATA_TARBALL_SHA256  /tmp/data.tar.gz" | sha256sum -c - \
    && tar xzf /tmp/data.tar.gz -C /tmp/ \
    && mv /tmp/data/exports/*.csv data/exports/ \
    && rm -rf /tmp/data /tmp/data.tar.gz \
    && ls -la data/exports/ | head

EXPOSE 26610

CMD ["python", "server.py"]
