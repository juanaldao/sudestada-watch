"""INA a5 API client — observed water level and (later) forecasts.

Public reads need no auth. Observed observations come back as a JSON list of
{timestart: ISO-UTC, valor: float, ...}. Timestamps are UTC.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import requests

from . import config
from .md import utcnow

_TIMEOUT = 30


def _get(path: str, params: dict) -> object:
    r = requests.get(f"{config.INA_BASE}{path}", params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_observed(station: str, series_id: int, hours_back: int = 48) -> pd.DataFrame:
    """Return observed level rows for one station, shaped for the `observation` table."""
    now = utcnow()
    start = (now - timedelta(hours=hours_back)).strftime("%Y-%m-%d")
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    data = _get(
        f"/obs/puntual/series/{series_id}/observaciones",
        {"timestart": start, "timeend": end},
    )
    if not isinstance(data, list) or not data:
        return _empty_obs()

    ts = pd.to_datetime([d.get("timestart") for d in data], utc=True, errors="coerce")
    df = pd.DataFrame(
        {
            "ts_utc": ts.tz_localize(None),
            "value": [_num(d.get("valor")) for d in data],
        }
    )
    df = df.dropna(subset=["ts_utc"]).drop_duplicates(subset=["ts_utc"])
    df["source"] = "ina"
    df["station"] = station
    df["variable"] = "level_observed"
    df["unit"] = "m"
    df["ingested_at"] = now.replace(tzinfo=None)
    return df[_OBS_COLS]


def fetch_forecast() -> pd.DataFrame:
    """Return the latest INA forecast run for San Fernando, shaped for `forecast`.

    Endpoint returns {forecast_date, series:[{pronosticos:[{timestart,valor,qualifier}]}]}.
    Qualifiers are the p05/p25/main/p75/p95 bands.
    """
    data = _get(
        f"/sim/calibrados/{config.INA_FORECAST_CAL_ID}/corridas/last",
        {"includeProno": "true"},
    )
    if not isinstance(data, dict):
        return _empty_fcst()
    run = pd.to_datetime(data.get("forecast_date"), utc=True, errors="coerce")
    series = data.get("series") or []
    pron = series[0].get("pronosticos", []) if series and isinstance(series[0], dict) else []
    if pd.isna(run) or not pron:
        return _empty_fcst()

    valid = pd.to_datetime([p.get("timestart") for p in pron], utc=True, errors="coerce")
    df = pd.DataFrame({
        "valid_utc": valid.tz_localize(None),
        "value": [_num(p.get("valor")) for p in pron],
        "qualifier": [p.get("qualifier") or "main" for p in pron],
    })
    df = df.dropna(subset=["valid_utc"])
    df["source"] = "ina"
    df["station"] = config.INA_FORECAST_STATION
    df["variable"] = "level_forecast"
    df["run_utc"] = run.tz_localize(None)
    df["unit"] = "m"
    df["ingested_at"] = utcnow().replace(tzinfo=None)
    return df.drop_duplicates(
        subset=["source", "station", "variable", "run_utc", "valid_utc", "qualifier"]
    )[_FCST_COLS]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_OBS_COLS = ["source", "station", "variable", "ts_utc", "value", "unit", "ingested_at"]
_FCST_COLS = ["source", "station", "variable", "run_utc", "valid_utc", "value", "qualifier",
              "unit", "ingested_at"]


def _empty_obs() -> pd.DataFrame:
    return pd.DataFrame(columns=_OBS_COLS)


def _empty_fcst() -> pd.DataFrame:
    return pd.DataFrame(columns=_FCST_COLS)
