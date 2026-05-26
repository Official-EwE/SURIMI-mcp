"""Tests for the signed SQL tool wrapper that pairs with the existing
query_data implementation in trino_client.

Uses a fake TrinoClient so we do not need a running Trino on localhost.
The wrapper itself is what we test: did the receipt sign the actual
SQL + limit + result?
"""
from __future__ import annotations

from typing import Any

import pytest

from receipts import verify_receipt


SECRET = b"sql-test-secret"


class _FakeClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self.rows = rows or [{"country": "ESP", "n": 1234}]
        self.calls: list[tuple[str, int]] = []

    def execute(self, sql: str, limit: int = 500) -> dict[str, Any]:
        self.calls.append((sql, limit))
        return {
            "rows": self.rows,
            "columns": ["country", "n"],
            "row_count": len(self.rows),
            "error": None,
        }


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("SURIMI_RECEIPT_SECRET", SECRET.decode())


def test_query_data_signed_returns_value_and_receipt():
    from sql_tools import make_query_data_signed

    fake = _FakeClient()
    fn = make_query_data_signed(client_factory=lambda: fake)
    out = fn(sql="SELECT 1", limit=10)
    assert "value" in out
    assert "receipt" in out
    assert out["value"]["row_count"] == 1


def test_query_data_signed_records_sql_and_limit_in_receipt():
    from sql_tools import make_query_data_signed

    fn = make_query_data_signed(client_factory=_FakeClient)
    out = fn(sql="SELECT country FROM x", limit=42)
    params = out["receipt"]["input_params"]
    assert params["sql"] == "SELECT country FROM x"
    assert params["limit"] == 42


def test_query_data_signed_receipt_verifies():
    from sql_tools import make_query_data_signed

    fn = make_query_data_signed(client_factory=_FakeClient)
    out = fn(sql="SELECT 1", limit=1)
    v = verify_receipt(out["receipt"], secret=SECRET)
    assert v["verified"] is True


def test_query_data_signed_receipt_tool_id():
    from sql_tools import make_query_data_signed

    fn = make_query_data_signed(client_factory=_FakeClient)
    out = fn(sql="SELECT 1", limit=1)
    assert out["receipt"]["tool_id"] == "query_data_signed"


def test_query_data_signed_rejects_tampered_rows():
    from sql_tools import make_query_data_signed

    fn = make_query_data_signed(client_factory=_FakeClient)
    out = fn(sql="SELECT 1", limit=1)
    out["receipt"]["output_value"]["rows"][0]["n"] = 999999  # tamper
    v = verify_receipt(out["receipt"], secret=SECRET)
    assert v["verified"] is False
    assert v["reason"] == "signature_mismatch"


def test_query_data_signed_propagates_executor_errors():
    from sql_tools import make_query_data_signed

    class _Broken(_FakeClient):
        def execute(self, sql: str, limit: int = 500) -> dict[str, Any]:
            raise RuntimeError("trino down")

    fn = make_query_data_signed(client_factory=_Broken)
    with pytest.raises(RuntimeError, match="trino down"):
        fn(sql="SELECT 1", limit=1)


def test_query_data_signed_returns_query_provenance():
    """Provenance should include the trino backend so the verifier can
    distinguish results from different sources."""
    from sql_tools import make_query_data_signed

    fn = make_query_data_signed(
        client_factory=_FakeClient,
        backend_id="trino://hive@127.0.0.1:8081",
    )
    out = fn(sql="SELECT 1", limit=1)
    assert out["receipt"]["provenance"]["backend"] == "trino://hive@127.0.0.1:8081"
