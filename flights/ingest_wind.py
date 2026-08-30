"""Flight: ingest wind (hourly) from Open-Meteo for the Tigre point.

Past/current hours -> observation (feeds v_wind_features); future hours -> forecast.
Forecast rows use DO UPDATE so a fresh run refreshes the forward-looking values.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lib import wind
from lib.md import connect, ensure_schema, upsert

OBS_CONFLICT = ["source", "station", "variable", "ts_utc"]
FCST_CONFLICT = ["source", "station", "variable", "run_utc", "valid_utc", "qualifier"]


def main() -> None:
    con = connect()
    ensure_schema(con)
    try:
        obs_df, fcst_df = wind.fetch_wind()
        n_obs = upsert(con, "observation", obs_df, OBS_CONFLICT)
        n_fcst = upsert(con, "forecast", fcst_df, FCST_CONFLICT, update_cols=["value", "ingested_at"])
        print(f"ingest_wind done — {n_obs} obs rows, {n_fcst} forecast rows")
    except Exception as e:
        print(f"[open-meteo] ERROR: {e!r}")
    con.close()


if __name__ == "__main__":
    main()
