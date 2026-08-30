"""Smoke test: schema.sql + views.sql load cleanly and expose the expected objects.

Run against a throwaway local DuckDB file:
    SUDESTADA_DB=./_smoke.duckdb python tests/smoke_schema.py
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lib import md

con = md.connect()
md.ensure_schema(con)

tables = {r[0] for r in con.execute(
    "select table_name from information_schema.tables where table_schema='main'").fetchall()}
views = {r[0] for r in con.execute(
    "select view_name from duckdb_views() where not internal").fetchall()}

expected_tables = {"observation", "forecast", "official_alert", "alert_event"}
expected_views = {"v_residual", "v_latest_level", "v_wind_features"}

assert expected_tables <= tables, f"missing tables: {expected_tables - tables}"
assert expected_views <= views, f"missing views: {expected_views - views}"

# Views must be queryable even when empty.
for v in expected_views:
    con.execute(f"select * from {v} limit 1").fetchall()

print("schema+views OK — tables:", sorted(tables & expected_tables),
      "views:", sorted(views & expected_views))
con.close()
