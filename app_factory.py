"""ASGI app factory serving both MCP transports from one process.

open-webui's native MCP support is Streamable HTTP only; we serve it at /mcp
so open-webui connects directly (no mcpo SSE bridge, which crashes on a known
mcp-python-sdk anyio teardown bug). We also keep SSE at /sse + /messages for
legacy clients. Both run under one Starlette app with a combined lifespan so
both FastMCP session managers start/stop correctly.
"""
from __future__ import annotations

import contextlib

from starlette.applications import Starlette


def build_asgi_app(mcp, *, http_path: str = "/mcp", sse_path: str = "/sse") -> Starlette:
    """Build a Starlette app exposing `mcp` over streamable-http (http_path)
    and SSE (sse_path + /messages), with a combined lifespan."""
    http_app = mcp.http_app(path=http_path, transport="http")
    sse_app = mcp.http_app(path=sse_path, transport="sse")

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with http_app.router.lifespan_context(app):
            async with sse_app.router.lifespan_context(app):
                yield

    return Starlette(
        routes=[*http_app.routes, *sse_app.routes],
        lifespan=lifespan,
    )
