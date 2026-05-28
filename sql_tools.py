"""Signed SQL tool wrapper.

`make_query_data_signed(client_factory)` builds a function that:
1. Executes the SQL against the Trino client.
2. Wraps the result in an HMAC-signed receipt.

The client_factory exists so the production code can pass `default_client`
from trino_client, and tests can pass a fake. This keeps unit tests fast
(no Trino connection needed) while the integration tests in test_fetchers.py
still cover the live path.
"""
from __future__ import annotations

from typing import Any, Callable

from signed_tool import with_receipt


def make_query_data_signed(
    client_factory: Callable[[], Any],
    backend_id: str = "trino://default",
) -> Callable[..., dict[str, Any]]:
    """Build a signed query_data function bound to a client factory.

    The factory is invoked per call so the connection can be lazily
    established (useful when the Trino server is not yet available at
    import time).
    """

    @with_receipt("query_data")
    def query_data_signed(sql: str, limit: int = 500) -> dict[str, Any]:
        client = client_factory()
        result = client.execute(sql, limit=limit)
        # Embed backend in the provenance so verifiers see which DB ran the query.
        result["provenance"] = {
            **(result.get("provenance") or {}),
            "backend": backend_id,
        }
        return result

    return query_data_signed
