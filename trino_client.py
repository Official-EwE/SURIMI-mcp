"""Query client for SURIMI MCP server.

Supports two backends:
- Trino (default, for gpu-comp-norce with Hive/MinIO stack)
- PostgreSQL (for EDITO deployment, data loaded from CSV exports)

Set DB_BACKEND=postgres + DATABASE_URL to use PostgreSQL.
Table references like "hive.oecd.fsedata" are auto-translated to
"oecd.fsedata" for PostgreSQL (strip the catalog prefix).
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional


class TrinoClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8081,
        catalog: str = "hive",
        user: str = "surimi-mcp",
    ):
        self._host = host
        self._port = port
        self._catalog = catalog
        self._user = user

    def _connection(self):
        import trino
        return trino.dbapi.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            catalog=self._catalog,
        )

    def execute(self, sql: str, limit: int = 1000) -> dict[str, Any]:
        try:
            conn = self._connection()
            cur = conn.cursor()
            cur.execute(sql)
            rows_raw = cur.fetchall()
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            rows = [dict(zip(col_names, row)) for row in rows_raw]
            if len(rows) > limit:
                rows = rows[:limit]
            return {
                "columns": col_names,
                "rows": rows,
                "row_count": len(rows),
                "truncated": len(rows_raw) > limit,
                "error": None,
            }
        except Exception as e:
            result: dict[str, Any] = {
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "error": str(e),
            }
            table_match = self._extract_table_from_sql(sql)
            if table_match and ("column" in str(e).lower()):
                schema_result = self.describe_table(table_match)
                if schema_result["error"] is None:
                    result["available_columns"] = schema_result["columns"]
            return result

    def describe_table(self, table: str) -> dict[str, Any]:
        try:
            conn = self._connection()
            cur = conn.cursor()
            cur.execute(f"SHOW COLUMNS FROM {table}")
            rows = cur.fetchall()
            columns = [
                {"name": row[0], "type": row[1]}
                for row in rows
            ]
            return {"table": table, "columns": columns, "error": None}
        except Exception as e:
            return {"table": table, "columns": [], "error": str(e)}

    @staticmethod
    def _extract_table_from_sql(sql: str) -> Optional[str]:
        match = re.search(r'FROM\s+([\w."]+(?:\.[\w."]+)*)', sql, re.IGNORECASE)
        return match.group(1) if match else None


class PostgresClient:
    """PostgreSQL backend. Same interface as TrinoClient."""

    def __init__(self, database_url: str):
        self._url = database_url

    def _connection(self):
        import psycopg2
        return psycopg2.connect(self._url)

    def _pg_sql(self, sql: str) -> str:
        """Translate Trino-style table refs to PostgreSQL.

        hive.oecd.fsedata → oecd.fsedata (strip catalog prefix).
        SHOW COLUMNS FROM → information_schema query.
        """
        sql = re.sub(
            r'\bhive\.([\w]+)\.([\w]+)\b',
            r'\1.\2',
            sql,
        )
        return sql

    def execute(self, sql: str, limit: int = 1000) -> dict[str, Any]:
        sql = self._pg_sql(sql)
        try:
            conn = self._connection()
            cur = conn.cursor()
            cur.execute(sql)
            rows_raw = cur.fetchall()
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            rows = [dict(zip(col_names, row)) for row in rows_raw]
            if len(rows) > limit:
                rows = rows[:limit]
            conn.close()
            return {
                "columns": col_names,
                "rows": rows,
                "row_count": len(rows),
                "truncated": len(rows_raw) > limit,
                "error": None,
            }
        except Exception as e:
            result: dict[str, Any] = {
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "error": str(e),
            }
            table_match = self._extract_table_from_sql(sql)
            if table_match and ("column" in str(e).lower()):
                schema_result = self.describe_table(table_match)
                if schema_result["error"] is None:
                    result["available_columns"] = schema_result["columns"]
            return result

    def describe_table(self, table: str) -> dict[str, Any]:
        table = self._pg_sql(table)
        parts = table.replace('"', '').split(".")
        if len(parts) == 2:
            schema, tbl = parts
        elif len(parts) == 3:
            _, schema, tbl = parts
        else:
            schema, tbl = "public", parts[-1]

        try:
            conn = self._connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                (schema, tbl),
            )
            rows = cur.fetchall()
            conn.close()
            columns = [{"name": row[0], "type": row[1]} for row in rows]
            if not columns:
                return {"table": table, "columns": [], "error": f"Table {table} not found"}
            return {"table": table, "columns": columns, "error": None}
        except Exception as e:
            return {"table": table, "columns": [], "error": str(e)}

    @staticmethod
    def _extract_table_from_sql(sql: str) -> Optional[str]:
        match = re.search(r'FROM\s+([\w."]+(?:\.[\w."]+)*)', sql, re.IGNORECASE)
        return match.group(1) if match else None


def default_client() -> TrinoClient | PostgresClient:
    backend = os.environ.get("DB_BACKEND", "trino").lower()
    if backend == "postgres":
        url = os.environ.get(
            "DATABASE_URL",
            "postgresql://surimi:surimi_mcp_2026@localhost:26613/surimi",
        )
        return PostgresClient(url)
    return TrinoClient(
        host=os.environ.get("TRINO_HOST", "127.0.0.1"),
        port=int(os.environ.get("TRINO_PORT", "8081")),
        catalog=os.environ.get("TRINO_CATALOG", "hive"),
    )
