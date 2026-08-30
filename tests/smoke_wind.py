"""Smoke test: wind ingestion + v_wind_features.

    SUDESTADA_DB=./_smoke.duckdb python tests/smoke_wind.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from flights import ingest_wind
from lib.md import connect

ingest_wind.main()
ingest_wind.main()  # idempotent

con = connect()
n_obs = con.execute(
    "select count(*) from observation where source='open-meteo'"
).fetchone()[0]
n_fcst = con.execute(
    "select count(*) from forecast where source='open-meteo'"
).fetchone()[0]
vars_obs = [r[0] for r in con.execute(
    "select distinct variable from observation where source='open-meteo' order by 1"
).fetchall()]
feat = con.execute(
    "select n_hours, mean_speed_ms, max_gust_ms, frac_se from v_wind_features"
).fetchone()
print("wind obs rows:", n_obs, "forecast rows:", n_fcst, "vars:", vars_obs)
print("v_wind_features:", feat)

assert n_obs > 0, "no wind observation rows"
assert {"wind_speed", "wind_dir", "wind_gust"} <= set(vars_obs)
assert feat is not None and feat[0] is not None and feat[0] > 0, "no wind features computed"
print("smoke_wind OK")
con.close()
