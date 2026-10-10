"""Snapshot every Dive query into site/dist/data.json for the public GitHub Pages site.

The Dives in dives/*/ are the single source of truth: this script pulls each
`useSQLQuery(`...`)` literal out of their .tsx, runs it, and stores the rows keyed by the
whitespace-normalised SQL. The site build aliases `@motherduck/react-sql-query` to
site/src/shim.js, which looks the same key up -- so the page renders the Dive code unchanged,
with no MotherDuck account or token in the browser.

Queries that use now() are evaluated at export time; the run workflow re-exports hourly,
right after ingestion, which is the data's real resolution anyway.

Run:  MOTHERDUCK_TOKEN=... python site/export_data.py
      SUDESTADA_DB=./_smoke.duckdb python site/export_data.py   (local file, attached as "sudestada")
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from lib.md import connect, utcnow  # noqa: E402

OUT = ROOT / "site" / "dist" / "data.json"
_QUERY = re.compile(r"useSQLQuery\(\s*`(.*?)`\s*\)", re.S)


def norm(sql: str) -> str:
    """Must match site/src/shim.js::norm exactly."""
    return " ".join(sql.split())


def dive_queries() -> list[str]:
    out = []
    for tsx in sorted((ROOT / "dives").glob("*/*.tsx")):
        found = _QUERY.findall(tsx.read_text(encoding="utf-8"))
        if not found:
            raise SystemExit(f"{tsx}: no useSQLQuery literals found -- did the Dive change shape?")
        for sql in found:
            # The key must equal the string JS sees; an interpolation or escape would differ.
            if "${" in sql or "\\" in sql:
                raise SystemExit(f"{tsx}: query uses ${{...}} or an escape; the snapshot can't key it")
            out.append(sql)
    return out


def _json(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    raise TypeError(f"unserialisable {type(v).__name__}: {v!r}")


def _connect() -> duckdb.DuckDBPyConnection:
    # The Dive SQL names "sudestada"."main".*, so a local file must be attached under that alias.
    local = os.environ.get("SUDESTADA_DB")
    if local:
        con = duckdb.connect()
        con.execute(f"ATTACH '{local}' AS sudestada (READ_ONLY)")
        return con
    return connect()


def main() -> None:
    con = _connect()
    queries = {}
    for sql in dive_queries():
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        queries[norm(sql)] = [dict(zip(cols, row)) for row in cur.fetchall()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated_utc": utcnow().isoformat(), "queries": queries},
                              default=_json, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(queries)} queries, {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
