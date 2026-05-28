"""Tests for the ASGI app factory that serves BOTH transports:
streamable-http at /mcp (for open-webui native MCP + modern clients) and
SSE at /sse (legacy clients). open-webui's native MCP is streamable-http
only; mcpo's SSE bridge crashes on a known anyio teardown bug, so we serve
/mcp natively and keep /sse for backward compat."""
from __future__ import annotations

import pytest
from fastmcp import FastMCP

from app_factory import build_asgi_app


def _mcp() -> FastMCP:
    m = FastMCP("test-app")

    @m.tool()
    def ping() -> str:
        return "pong"

    return m


def test_app_exposes_both_transports():
    app = build_asgi_app(_mcp())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/mcp" in paths
    assert "/sse" in paths


def test_app_includes_sse_messages_endpoint():
    app = build_asgi_app(_mcp())
    paths = {getattr(r, "path", None) for r in app.routes}
    # SSE transport needs its POST /messages companion endpoint
    assert "/messages" in paths


def test_mcp_streamable_http_initialize_works():
    from starlette.testclient import TestClient

    app = build_asgi_app(_mcp())
    with TestClient(app) as c:
        r = c.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "method": "initialize", "id": 1,
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert r.status_code == 200
        assert "protocolVersion" in r.text


def test_custom_paths():
    app = build_asgi_app(_mcp(), http_path="/api/mcp", sse_path="/api/sse")
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/mcp" in paths
    assert "/api/sse" in paths
