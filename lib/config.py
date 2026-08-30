"""Static configuration: stations, source IDs, geo point, and alert thresholds.

Verified live 2026-08-20. IDs from the INA a5 API and SHN AlturasHorarias table.
"""
from __future__ import annotations

# --- Stations (our canonical keys) -----------------------------------------------------------
SAN_FERNANDO = "san_fernando"
PILOTE_NORDEN = "pilote_norden"
TIGRE_POINT = "tigre_point"  # geo point for gridded wind

# --- INA a5 API -------------------------------------------------------------------------------
INA_BASE = "https://alerta.ina.gob.ar/a5"
INA_OBSERVED_SERIES = {
    SAN_FERNANDO: 52,      # var H, metres
    PILOTE_NORDEN: 3345,   # var H, metres
}
INA_FORECAST_CAL_ID = 432  # "regre_sfer" — Río de la Plata tide regression @ San Fernando
INA_FORECAST_STATION = SAN_FERNANDO

# --- SHN --------------------------------------------------------------------------------------
SHN_ALTURAS_CSV = "https://www.hidro.gob.ar/oceanografia/AlturasHorarias.asp?export=csv"
SHN_PRONOSTICO_HTML = "https://www.hidro.gob.ar/oceanografia/pronostico.asp"
SHN_PRONOSTICO_PDF = "https://www.hidro.gob.ar/Oceanografia/pronostico/pronostico.pdf"
SHN_ALERTS_HTML = "https://www.hidro.gob.ar/oceanografia/AACRIOPLA.asp"
# Column header (in the CSV) -> our station key. Headers are matched case-insensitively.
SHN_COLUMN_STATIONS = {
    "san fernando": SAN_FERNANDO,
    "pilote norden": PILOTE_NORDEN,
}
SHN_MISSING_TOKENS = {"S/D", "F/S", "", "-"}
ARG_TZ_OFFSET_HOURS = -3  # SHN pages are local ART (UTC-3), no DST

# --- Wind (Open-Meteo) ------------------------------------------------------------------------
TIGRE_LAT = -34.42
TIGRE_LON = -58.58
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# --- Alert thresholds (configurable; tune from history) --------------------------------------
# Level thresholds are per source because of the datum caveat.
LEVEL_THRESHOLDS_M = {
    # (source, station): {"warning": m, "alert": m}
    ("shn", SAN_FERNANDO): {"warning": 2.5, "alert": 3.0},
    ("shn", PILOTE_NORDEN): {"warning": 2.5, "alert": 3.0},
    ("ina", SAN_FERNANDO): {"warning": 2.5, "alert": 3.0},
}
FORECAST_LEAD_HOURS = 48          # look this far ahead for forecast threshold crossings
WIND_SE_FRAC_MIN = 0.6            # >= 60% of the last 12 h in the SE sector
WIND_MEAN_SPEED_MIN_MS = 8.0      # with mean speed at/above this
WIND_RESIDUAL_RISE_MIN_M = 0.3    # and residual rising by at least this over the window
