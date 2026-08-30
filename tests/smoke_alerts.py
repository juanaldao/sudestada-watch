"""End-to-end smoke: ingest everything, evaluate alerts twice, assert dedupe.

    SUDESTADA_DB=./_smoke.duckdb python tests/smoke_alerts.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from flights import eval_alerts, ingest_forecasts, ingest_levels, ingest_wind
from lib.md import connect

ingest_levels.main()
ingest_wind.main()
ingest_forecasts.main()

print("\n--- eval #1 ---")
eval_alerts.main()
con = connect()
n1 = con.execute("select count(*) from alert_event").fetchone()[0]
rows = con.execute(
    "select rule, severity, station, notified from alert_event order by rule"
).fetchall()
for r in rows:
    print("  event:", r)
con.close()

print("\n--- eval #2 (should add 0) ---")
eval_alerts.main()
con = connect()
n2 = con.execute("select count(*) from alert_event").fetchone()[0]
con.close()

print(f"\nalert_event count: eval#1={n1}, eval#2={n2}")
assert n2 == n1, "dedupe failed — second eval created new events"
print("smoke_alerts OK — dedupe holds")
