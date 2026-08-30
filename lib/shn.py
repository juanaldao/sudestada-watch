"""SHN scrapers — observed hourly heights (and later pronostico / alerts / tide).

AlturasHorarias CSV: latin-1, ';'-delimited, first column 'Fecha y hora' as
'DD/MM/YYYY HH:MM' in local ART (UTC-3). Station columns hold metres; missing = 'S/D'/'F/S'.
Only the last ~10 days are served, so our DB is the long-term archive.
"""
from __future__ import annotations

import io
import re

import pandas as pd
import requests

from . import config
from .md import utcnow

_TIMEOUT = 30
_HEADERS = {"User-Agent": "sudestada-watch/0.1"}
_OBS_COLS = ["source", "station", "variable", "ts_utc", "value", "unit", "ingested_at"]
_FCST_COLS = ["source", "station", "variable", "run_utc", "valid_utc", "value", "qualifier",
              "unit", "ingested_at"]

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def _fetch_text(url: str) -> str:
    """Fetch an SHN .asp page as plain text (UTF-8) with tags stripped."""
    r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    html = r.content.decode("utf-8", errors="replace")
    html = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _local_to_utc(day: int, month: int, year: int, hh: int, mm: int) -> pd.Timestamp:
    """ART (UTC-3) wall time -> tz-naive UTC timestamp."""
    local = pd.Timestamp(year=year, month=month, day=day, hour=hh, minute=mm)
    return local - pd.Timedelta(hours=config.ARG_TZ_OFFSET_HOURS)


def _dmy_hm_to_utc(dmy: str, hm: str) -> pd.Timestamp:
    d, m, y = (int(x) for x in dmy.split("/"))
    hh, mm = (int(x) for x in hm.split(":"))
    return _local_to_utc(d, m, y, hh, mm)


def fetch_observed_levels() -> pd.DataFrame:
    """Return observed level rows for the configured SHN stations (long format)."""
    r = requests.get(config.SHN_ALTURAS_CSV, timeout=_TIMEOUT)
    r.raise_for_status()
    text = r.content.decode("latin-1")

    raw = pd.read_csv(io.StringIO(text), sep=";", dtype=str)
    # Map actual column headers -> our station keys, case/space-insensitively.
    header_by_key = {}
    for col in raw.columns:
        key = config.SHN_COLUMN_STATIONS.get(col.strip().lower())
        if key:
            header_by_key[key] = col
    if not header_by_key:
        return _empty()

    ts_local = pd.to_datetime(raw.iloc[:, 0], format="%d/%m/%Y %H:%M", errors="coerce")
    # ART (UTC-3) -> UTC: add 3 hours. Store tz-naive UTC.
    ts_utc = ts_local - pd.Timedelta(hours=config.ARG_TZ_OFFSET_HOURS)

    now = utcnow().replace(tzinfo=None)
    frames = []
    for station, col in header_by_key.items():
        vals = raw[col].map(_parse_value)
        frames.append(
            pd.DataFrame(
                {
                    "source": "shn",
                    "station": station,
                    "variable": "level_observed",
                    "ts_utc": ts_utc,
                    "value": vals,
                    "unit": "m",
                    "ingested_at": now,
                }
            )
        )
    out = pd.concat(frames, ignore_index=True)
    return out.dropna(subset=["ts_utc"]).drop_duplicates(
        subset=["source", "station", "variable", "ts_utc"]
    )[_OBS_COLS]


def _parse_value(v):
    if v is None:
        return None
    s = str(v).strip()
    if s.upper() in {t.upper() for t in config.SHN_MISSING_TOKENS}:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_OBS_COLS)


# --- Official alerts (AACRIOPLA) -------------------------------------------------------------

# Stations that appear in the AACRIOPLA "Se estiman las siguientes alturas" table.
_ALERT_STATIONS = {r"SAN FERNANDO": config.SAN_FERNANDO}


def fetch_official_alerts() -> pd.DataFrame:
    """Parse the SHN AACRIOPLA crecida notice into `official_alert` rows.

    Returns empty when there is no active AVISO POR CRECIDA. The table looks like:
        SAN FERNANDO 2.25 16:00 21/08/2026
    """
    text = _fetch_text(config.SHN_ALERTS_HTML)
    if "AVISO POR CRECIDA" not in text.upper():
        return pd.DataFrame(columns=_ALERT_COLS)

    m = re.search(
        r"(\d{1,2})\s+DE\s+([A-Za-zÁÉÍÓÚñÑ]+)\s+DE\s+(\d{4}),?\s*(\d{1,2}):(\d{2})\s*HS",
        text, re.IGNORECASE,
    )
    issued = (
        _local_to_utc(int(m[1]), _MONTHS.get(m[2].lower(), 1), int(m[3]), int(m[4]), int(m[5]))
        if m else utcnow().replace(tzinfo=None)
    )

    now = utcnow().replace(tzinfo=None)
    rows = []
    for pattern, station in _ALERT_STATIONS.items():
        mm = re.search(
            pattern + r"\s+([\d.]+)\s+(\d{2}:\d{2})\s+(\d{2}/\d{2}/\d{4})", text
        )
        if not mm:
            continue
        rows.append({
            "source": "shn", "issued_utc": issued, "station": station,
            "peak_value": float(mm[1]), "peak_time_utc": _dmy_hm_to_utc(mm[3], mm[2]),
            "raw_text": text[:4000], "url": config.SHN_ALERTS_HTML, "ingested_at": now,
        })
    return pd.DataFrame(rows, columns=_ALERT_COLS)


_ALERT_COLS = ["source", "issued_utc", "station", "peak_value", "peak_time_utc",
               "raw_text", "url", "ingested_at"]


# --- Pronóstico Mareológico ------------------------------------------------------------------

def fetch_pronostico() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (bulletin_df, forecast_df) from the SHN Pronóstico Mareológico page.

    bulletin: verbatim text + validity window. forecast: corrected pleamar/bajamar extremes
    for San Fernando (source='shn', variable='level_forecast', qualifier 'pleamar'/'bajamar').
    """
    text = _fetch_text(config.SHN_PRONOSTICO_HTML)
    now = utcnow().replace(tzinfo=None)

    vm = re.search(
        r"DESDE\s+LAS\s+(\d{1,2}:\d{2})\s*Hs?\s+DE\s+(\d{2}/\d{2}/\d{4})\s+"
        r"HASTA\s+LAS\s+(\d{1,2}:\d{2})\s*Hs?\s+DE\s+(\d{2}/\d{2}/\d{4})",
        text, re.IGNORECASE,
    )
    valid_from = _dmy_hm_to_utc(vm[2], vm[1]) if vm else pd.NaT
    valid_to = _dmy_hm_to_utc(vm[4], vm[3]) if vm else pd.NaT
    issued = valid_from if not pd.isna(valid_from) else now

    bulletin = pd.DataFrame([{
        "issued_utc": issued, "valid_from_utc": valid_from, "valid_to_utc": valid_to,
        "raw_text": text[:6000], "url": config.SHN_PRONOSTICO_HTML, "ingested_at": now,
    }], columns=_BULLETIN_COLS)

    # San Fernando corrected extremes block: from "SAN FERNANDO" up to the next section.
    fcst_rows = []
    block = re.search(r"SAN FERNANDO(.*?)(?:&nbsp;|RIO DE LA PLATA EXTERIOR|Sección|$)", text)
    if block:
        for state, hm, val, dmy in re.findall(
            r"(PLEAMAR|BAJAMAR)\s+(\d{2}:\d{2})\s+([\d.]+)\s+(\d{2}/\d{2}/\d{4})", block[1]
        ):
            fcst_rows.append({
                "source": "shn", "station": config.SAN_FERNANDO, "variable": "level_forecast",
                "run_utc": issued, "valid_utc": _dmy_hm_to_utc(dmy, hm), "value": float(val),
                "qualifier": state.lower(), "unit": "m", "ingested_at": now,
            })
    forecast = pd.DataFrame(fcst_rows, columns=_FCST_COLS)
    return bulletin, forecast


_BULLETIN_COLS = ["issued_utc", "valid_from_utc", "valid_to_utc", "raw_text", "url",
                  "ingested_at"]
