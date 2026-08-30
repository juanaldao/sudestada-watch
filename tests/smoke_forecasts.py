"""Smoke test: forecast + official-alert ingestion.

    SUDESTADA_DB=./_smoke.duckdb python tests/smoke_forecasts.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from flights import ingest_forecasts
from lib.md import connect

ingest_forecasts.main()
ingest_forecasts.main()  # idempotent

con = connect()
ina_q = con.execute(
    "select count(*), count(distinct qualifier) from forecast "
    "where source='ina' and variable='level_forecast'"
).fetchone()
shn_fcst = con.execute(
    "select count(*) from forecast where source='shn'"
).fetchone()[0]
bulletins = con.execute("select count(*) from shn_bulletin").fetchone()[0]
alerts = con.execute(
    "select station, peak_value, peak_time_utc from official_alert order by station"
).fetchall()
print("INA forecast rows / qualifiers:", ina_q)
print("SHN pronostico forecast rows:", shn_fcst)
print("SHN bulletins:", bulletins)
print("Official alerts:", alerts)

assert ina_q[0] > 0, "no INA forecast rows"
assert ina_q[1] >= 3, "expected multiple INA qualifier bands"
assert bulletins >= 1, "no SHN bulletin captured"
print("smoke_forecasts OK")
con.close()
