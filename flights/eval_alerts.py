"""Flight: evaluate sudestada alert rules (every 15 min), notify once per condition.

Rules (highest authority first):
  1. shn_official      — an active SHN AACRIOPLA crecida notice for our stations.
  2. observed_threshold — latest observed level >= warning/alert threshold.
  3. forecast_threshold — INA forecast 'main' crosses threshold within the lead window.
  4. wind_precursor    — sustained SE wind over the last 12 h (v_wind_features).

Dedupe: a candidate is keyed by (rule, station, dedupe_key). We only notify keys not already
in alert_event, then record them — so a standing condition alerts once, not every tick.
Level dedupe is bucketed per day+severity; official/forecast keys are per issuance/run.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lib import config
from lib.md import connect, ensure_schema, utcnow
from lib.notify import get_notifier

EMOJI = {"watch": "👀", "warning": "⚠️", "alert": "🚨"}


def _severity_for(level: float, thr: dict | None) -> str | None:
    if not thr:
        return None
    if level >= thr["alert"]:
        return "alert"
    if level >= thr["warning"]:
        return "warning"
    return None


def _collect(con) -> list[dict]:
    now = utcnow().replace(tzinfo=None)
    cands: list[dict] = []

    # 1. SHN official crecida (always notify; escalate by peak).
    for station, peak, peak_t, issued in con.execute(
        "select station, peak_value, peak_time_utc, issued_utc from official_alert "
        "qualify row_number() over (partition by station order by issued_utc desc)=1"
    ).fetchall():
        thr = config.LEVEL_THRESHOLDS_M.get(("shn", station))
        sev = _severity_for(peak or 0, thr) or "warning"
        cands.append({
            "ts_utc": now, "rule": "shn_official", "severity": sev, "station": station,
            "dedupe_key": f"shn:{issued:%Y-%m-%dT%H:%M}:{station}",
            "message": f"SHN AVISO POR CRECIDA — {station}: pico {peak} m a las "
                       f"{peak_t:%H:%M} UTC del {peak_t:%d/%m} (emitido {issued:%d/%m %H:%M} UTC).",
        })

    # 2. Observed level threshold.
    for source, station, ts, level in con.execute(
        "select source, station, ts_utc, level_m from v_latest_level"
    ).fetchall():
        sev = _severity_for(level, config.LEVEL_THRESHOLDS_M.get((source, station)))
        if sev:
            cands.append({
                "ts_utc": now, "rule": "observed_threshold", "severity": sev, "station": station,
                "dedupe_key": f"obs:{source}:{station}:{sev}:{ts:%Y-%m-%d}",
                "message": f"Nivel observado ({source}) en {station}: {level:.2f} m "
                           f"a las {ts:%H:%M} UTC — umbral {sev}.",
            })

    # 3. INA forecast threshold within the lead window.
    row = con.execute(
        "select run_utc, max(value) peak, arg_max(valid_utc, value) peak_t from forecast "
        "where source='ina' and variable='level_forecast' and qualifier='main' "
        "and valid_utc between now() and now() + to_hours(?) group by run_utc "
        "qualify row_number() over (order by run_utc desc)=1",
        [config.FORECAST_LEAD_HOURS],
    ).fetchone()
    if row and row[1] is not None:
        run, peak, peak_t = row
        sev = _severity_for(peak, config.LEVEL_THRESHOLDS_M.get(("ina", config.INA_FORECAST_STATION)))
        if sev:
            cands.append({
                "ts_utc": now, "rule": "forecast_threshold", "severity": sev,
                "station": config.INA_FORECAST_STATION,
                "dedupe_key": f"fcst:ina:{config.INA_FORECAST_STATION}:{run:%Y-%m-%dT%H:%M}",
                "message": f"Pronóstico INA {config.INA_FORECAST_STATION}: pico {peak:.2f} m "
                           f"a las {peak_t:%H:%M UTC %d/%m} (run {run:%d/%m %H:%M} UTC) — {sev}.",
            })

    # 4. Sustained SE wind precursor.
    feat = con.execute(
        "select n_hours, mean_speed_ms, max_gust_ms, frac_se from v_wind_features"
    ).fetchone()
    if feat and feat[0] and feat[3] is not None:
        n_hours, mean_speed, max_gust, frac_se = feat
        if frac_se >= config.WIND_SE_FRAC_MIN and (mean_speed or 0) >= config.WIND_MEAN_SPEED_MIN_MS:
            cands.append({
                "ts_utc": now, "rule": "wind_precursor", "severity": "watch",
                "station": config.TIGRE_POINT,
                "dedupe_key": f"wind:{now:%Y-%m-%d %H}"[:13],  # per-hour bucket
                "message": f"Viento del SE sostenido: {frac_se:.0%} de las últimas {int(n_hours)} h, "
                           f"media {mean_speed:.1f} m/s, ráfaga máx {max_gust:.1f} m/s — posible sudestada.",
            })
    return cands


def main() -> None:
    con = connect()
    ensure_schema(con)
    notifier = get_notifier()

    new_count = 0
    for c in _collect(con):
        exists = con.execute(
            "select 1 from alert_event where rule=? and station=? and dedupe_key=?",
            [c["rule"], c["station"], c["dedupe_key"]],
        ).fetchone()
        if exists:
            continue
        text = f"{EMOJI.get(c['severity'], '')} [{c['severity'].upper()}] {c['message']}"
        notified = notifier.send(text)
        con.execute(
            "insert into alert_event (ts_utc, rule, severity, station, dedupe_key, message, notified) "
            "values (?,?,?,?,?,?,?) on conflict do nothing",
            [c["ts_utc"], c["rule"], c["severity"], c["station"], c["dedupe_key"],
             c["message"], notified],
        )
        new_count += 1

    con.close()
    print(f"eval_alerts done — {new_count} new alert(s) notified")


if __name__ == "__main__":
    main()
