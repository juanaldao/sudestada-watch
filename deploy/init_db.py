"""Create the MotherDuck database if needed and apply schema.sql / views.sql.

Run by GitHub Actions on push (see .github/workflows/deploy.yml), or locally with a token.
This is the deploy step for the Actions-scheduled setup; `sync_flights.py` is the equivalent
for MotherDuck Flights and needs a Business plan (see its docstring).
"""
from __future__ import annotations

import os
import pathlib
import sys

import duckdb

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lib import md  # noqa: E402


def main() -> None:
    token = (os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token") or "").strip()
    if not token:
        sys.exit("MOTHERDUCK_TOKEN not set")
    db = os.environ.get("SUDESTADA_DATABASE", "sudestada")
    # Bare `md:` so the database can be created on a fresh account; schema.sql/views.sql use
    # unqualified names, so the current database has to be set before applying them.
    con = duckdb.connect("md:", config={"motherduck_token": token})
    con.execute(f'CREATE DATABASE IF NOT EXISTS "{db}"')
    con.execute(f'USE "{db}"')
    md.ensure_schema(con)
    # Filter by catalog: bare `md:` attaches every database, so an unfiltered
    # information_schema query also lists other databases' tables and MotherDuck's system views.
    objs = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_catalog = ? AND table_schema = 'main' ORDER BY 1", [db]
    ).fetchall()]
    con.close()
    print(f"schema applied to {db}: {objs}")


if __name__ == "__main__":
    main()
