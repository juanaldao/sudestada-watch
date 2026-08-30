"""MotherDuck / DuckDB connection + idempotent-upsert helpers.

Connection uses the `md:` protocol. The token is read from the MOTHERDUCK_TOKEN env var
(set as a GitHub Actions secret and as a MotherDuck Flight secret). Point at a local DuckDB
file instead by setting SUDESTADA_DB to a path (handy for dev/tests).
"""
from __future__ import annotations

import os
import pathlib
from datetime import datetime, timezone

import duckdb

_SQL_DIR = pathlib.Path(__file__).resolve().parent / "sql"
DEFAULT_DATABASE = os.environ.get("SUDESTADA_DATABASE", "sudestada")


def utcnow() -> datetime:
    """Timezone-aware UTC now — the single clock source for `ingested_at`."""
    return datetime.now(timezone.utc)


def connect(database: str | None = None) -> duckdb.DuckDBPyConnection:
    """Open a connection to MotherDuck (or a local file if SUDESTADA_DB is set).

    Precedence:
      1. SUDESTADA_DB set -> local DuckDB file (dev/tests).
      2. MOTHERDUCK_TOKEN set -> md: with explicit token (CI / local against cloud).
      3. otherwise -> bare `md:` — works inside a Flight, where MotherDuck injects the token.
    """
    local = os.environ.get("SUDESTADA_DB")
    if local:
        return duckdb.connect(local)
    db = database or DEFAULT_DATABASE
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if token:
        # Pass the token as config, not in the URI: a stray newline or reserved character
        # in the value makes DuckDB fail URI parsing ("Invalid character in scheme").
        return duckdb.connect(f"md:{db}", config={"motherduck_token": token.strip()})
    return duckdb.connect(f"md:{db}")  # token auto-injected in a Flight runtime


def apply_sql_file(con: duckdb.DuckDBPyConnection, name: str) -> None:
    """Execute a .sql file from the sql/ directory (schema.sql, views.sql)."""
    con.execute((_SQL_DIR / name).read_text(encoding="utf-8"))


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    apply_sql_file(con, "schema.sql")
    apply_sql_file(con, "views.sql")


def upsert(
    con: duckdb.DuckDBPyConnection,
    table: str,
    df,
    conflict_cols: list[str],
    update_cols: list[str] | None = None,
) -> int:
    """Idempotent upsert of a pandas DataFrame into `table`.

    Registers the frame and runs INSERT ... ON CONFLICT. When `update_cols` is given the
    conflicting rows are refreshed (used for forecasts, which get re-issued); otherwise
    conflicts are ignored (observations never change once recorded).

    Returns the number of rows in the input frame (DuckDB doesn't cheaply report affected rows
    for ON CONFLICT, so callers use this for logging, not as an inserted-count guarantee).
    """
    if df is None or len(df) == 0:
        return 0
    cols = list(df.columns)
    col_list = ", ".join(f'"{c}"' for c in cols)
    con.register("_staging", df)
    try:
        if update_cols:
            set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
            action = f"DO UPDATE SET {set_clause}"
        else:
            action = "DO NOTHING"
        conflict_list = ", ".join(f'"{c}"' for c in conflict_cols)
        con.execute(
            f'INSERT INTO "{table}" ({col_list}) SELECT {col_list} FROM _staging '
            f"ON CONFLICT ({conflict_list}) {action}"
        )
    finally:
        con.unregister("_staging")
    return len(df)
