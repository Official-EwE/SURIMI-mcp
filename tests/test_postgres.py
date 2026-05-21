"""Tests for PostgreSQL backend (requires local surimi-db running)."""
import os
import pytest

PG_URL = "postgresql://surimi:surimi_mcp_2026@localhost:26613/surimi"


@pytest.fixture
def client():
    from trino_client import PostgresClient
    return PostgresClient(PG_URL)


def _db_available():
    try:
        import psycopg2
        conn = psycopg2.connect(PG_URL)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="surimi-db not running")


def test_pg_query_oecd(client):
    result = client.execute(
        "SELECT country_code, direct_transfers_meur "
        "FROM oecd.oecd_fisheries_support_estimates_eu_coastal_states "
        "WHERE year = '2020' LIMIT 5"
    )
    assert result["error"] is None
    assert len(result["rows"]) > 0


def test_pg_query_trino_style_table_ref(client):
    result = client.execute(
        "SELECT country_code, direct_transfers_meur "
        "FROM hive.oecd.oecd_fisheries_support_estimates_eu_coastal_states "
        "WHERE year = '2020' LIMIT 5"
    )
    assert result["error"] is None
    assert len(result["rows"]) > 0


def test_pg_describe_table(client):
    result = client.describe_table("oecd.oecd_fisheries_support_estimates_eu_coastal_states")
    assert result["error"] is None
    assert len(result["columns"]) > 0
    assert any(c["name"] == "country_code" for c in result["columns"])


def test_pg_describe_table_trino_fqn(client):
    result = client.describe_table("hive.oecd.fsedata")
    assert result["error"] is None
    assert len(result["columns"]) > 0


def test_pg_bad_column_returns_error(client):
    result = client.execute("SELECT bad_col FROM oecd.fsedata")
    assert result["error"] is not None


def test_default_client_postgres():
    os.environ["DB_BACKEND"] = "postgres"
    os.environ["DATABASE_URL"] = PG_URL
    from trino_client import default_client, PostgresClient
    c = default_client()
    assert isinstance(c, PostgresClient)
    del os.environ["DB_BACKEND"]
    del os.environ["DATABASE_URL"]
