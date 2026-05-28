FROM python:3.12-slim

LABEL org.opencontainers.image.title="SURIMI-mcp"
LABEL org.opencontainers.image.description="SURIMI fisheries-data MCP server. Exposes 22 tools across tabular SQL (10), gridded netcdf (11), and signed SQL (1) over SSE for any MCP-compatible LLM client. Analytical outputs carry HMAC-signed receipts (arxiv 2603.10060) so any number can be re-verified. CSV data bundle is fetched from EDITO MinIO at build time (not baked into source)."
LABEL org.opencontainers.image.source="https://github.com/Official-EwE/SURIMI-mcp"
LABEL org.opencontainers.image.url="https://www.surimi-project.eu/"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.vendor="SURIMI Project"
LABEL org.opencontainers.image.documentation="https://www.surimi-project.eu/"

WORKDIR /app

# Unbuffered stdout/stderr so kubectl logs shows progress in real time
# (the post-install load-data Job is the main place this matters).
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Runtime deps. curl is needed for the data fetch below; kept because chart's load-data Job re-fetches.
# h5py + netCDF4 manylinux wheels bundle their own HDF5/netcdf shared libs,
# so no apt hdf5/netcdf packages are needed.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        fastmcp trino psycopg2-binary \
        xarray netcdf4 h5py h5netcdf numpy s3fs

# Code: server, tools, loader, schemas, debug helper
COPY capabilities.py catalog.py trino_client.py search.py recipes.py server.py ./
COPY receipts.py signed_tool.py citation_gate.py nc_tools.py sql_tools.py ./
COPY netcdf/ ./netcdf/
COPY data/load_csv.py data/load_csv.py
COPY data/init/ data/init/
COPY scripts/ /app/scripts/

# Data: CSVs come from MinIO, not from this repo (per Rik's "data != image" rule).
# Override at build time:  docker build --build-arg DATA_TARBALL_URL=... --build-arg DATA_TARBALL_SHA256=...
ARG DATA_TARBALL_URL=https://minio.dive.edito.eu/project-surimi/surimi-data-dummy/data.tar.gz
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
