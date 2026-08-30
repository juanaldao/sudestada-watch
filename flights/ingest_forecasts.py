"""Flight: ingest official forecasts + alerts (hourly).

  - INA a5 forecast run (cal 432) -> forecast (p05/p25/main/p75/p95)
  - SHN Pronóstico Mareológico -> shn_bulletin (verbatim) + forecast (corrected extremes)
  - SHN AACRIOPLA crecida notice -> official_alert

Each source is isolated so one failure doesn't sink the others.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lib import ina, shn
from lib.md import connect, ensure_schema, upsert

FCST_CONFLICT = ["source", "station", "variable", "run_utc", "valid_utc", "qualifier"]
ALERT_CONFLICT = ["source", "issued_utc", "station"]
BULLETIN_CONFLICT = ["issued_utc"]
FCST_UPDATE = ["value", "ingested_at"]


def _try(label, fn):
    try:
        return fn()
    except Exception as e:
        print(f"[{label}] ERROR: {e!r}")
        return None


def main() -> None:
    con = connect()
    ensure_schema(con)

    df = _try("ina.forecast", ina.fetch_forecast)
    if df is not None:
        print(f"[ina] forecast: {upsert(con, 'forecast', df, FCST_CONFLICT, FCST_UPDATE)} rows")

    pron = _try("shn.pronostico", shn.fetch_pronostico)
    if pron is not None:
        bulletin, fcst = pron
        print(f"[shn] bulletin: {upsert(con, 'shn_bulletin', bulletin, BULLETIN_CONFLICT)} rows")
        print(f"[shn] pronostico forecast: "
              f"{upsert(con, 'forecast', fcst, FCST_CONFLICT, FCST_UPDATE)} rows")

    alerts = _try("shn.alerts", shn.fetch_official_alerts)
    if alerts is not None:
        print(f"[shn] official alerts: "
              f"{upsert(con, 'official_alert', alerts, ALERT_CONFLICT)} rows")

    con.close()
    print("ingest_forecasts done")


if __name__ == "__main__":
    main()
