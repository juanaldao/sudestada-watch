"""Open-Meteo wind — hourly speed/direction/gusts for the Tigre point.

Past+current hours land as `observation` (feeds v_wind_features, the SE-precursor signal);
future hours land as `forecast`. Units forced to m/s; times requested in UTC (tz-naive).
"""
from __future__ import annotations

import pandas as pd
import requests

from . import config
from .md import utcnow

_TIMEOUT = 30
_OBS_COLS = ["source", "station", "variable", "ts_utc", "value", "unit", "ingested_at"]
_FCST_COLS = ["source", "station", "variable", "run_utc", "valid_utc", "value", "qualifier",
              "unit", "ingested_at"]

# Open-Meteo hourly field -> (our variable, unit)
_FIELDS = {
    "wind_speed_10m": ("wind_speed", "m/s"),
    "wind_direction_10m": ("wind_dir", "deg"),
    "wind_gusts_10m": ("wind_gust", "m/s"),
}


def fetch_wind() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (observation_df, forecast_df) for the Tigre point."""
    params = {
        "latitude": config.TIGRE_LAT,
        "longitude": config.TIGRE_LON,
        "hourly": ",".join(_FIELDS),
        "wind_speed_unit": "ms",
        "timezone": "UTC",
        "past_days": 1,
        "forecast_days": 3,
    }
    r = requests.get(config.OPEN_METEO_FORECAST, params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    hourly = r.json().get("hourly", {})
    times = pd.to_datetime(hourly.get("time", []), errors="coerce")  # already UTC, tz-naive
    if len(times) == 0:
        return _empty_obs(), _empty_fcst()

    now = utcnow().replace(tzinfo=None)
    run = now.replace(minute=0, second=0, microsecond=0)
    is_past = times <= now

    obs_frames, fcst_frames = [], []
    for field, (variable, unit) in _FIELDS.items():
        vals = pd.to_numeric(pd.Series(hourly.get(field, [])), errors="coerce")
        base = pd.DataFrame({"ts": times, "value": vals.values})

        past = base[is_past]
        obs_frames.append(pd.DataFrame({
            "source": "open-meteo", "station": config.TIGRE_POINT, "variable": variable,
            "ts_utc": past["ts"], "value": past["value"], "unit": unit, "ingested_at": now,
        }))

        future = base[~is_past]
        fcst_frames.append(pd.DataFrame({
            "source": "open-meteo", "station": config.TIGRE_POINT, "variable": variable,
            "run_utc": run, "valid_utc": future["ts"], "value": future["value"],
            "qualifier": "main", "unit": unit, "ingested_at": now,
        }))

    obs = pd.concat(obs_frames, ignore_index=True).dropna(subset=["ts_utc"])[_OBS_COLS]
    fcst = pd.concat(fcst_frames, ignore_index=True).dropna(subset=["valid_utc"])[_FCST_COLS]
    return obs, fcst


def _empty_obs() -> pd.DataFrame:
    return pd.DataFrame(columns=_OBS_COLS)


def _empty_fcst() -> pd.DataFrame:
    return pd.DataFrame(columns=_FCST_COLS)
