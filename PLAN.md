# Sudestada Watch — Data Ingestion & Alerting (Phase 1)

## Status: IMPLEMENTED & verified (2026-08-21)

Phase 1 is built and passing end-to-end smoke tests against live data (it fired real alerts:
SHN crecida San Fernando 2.25 m + INA forecast peak 2.50 m, with dedupe holding). As-built
deltas from the original design below:

- SQL files live at **`lib/sql/`** (not root `sql/`) so they ship as package data for pip
  install inside a Flight; loaded via `lib/md.py::ensure_schema`.
- Added a **`shn_bulletin`** table (verbatim Pronóstico Mareológico text + validity window),
  since the pronóstico is prose + corrected pleamar/bajamar, not a clean numeric table.
- Repo is a **pip-installable package** (`pyproject.toml`, packages `lib` + `flights`); each
  Flight's source pip-installs the repo from git and calls `<module>.main()`.
- `notify.py` implements **Telegram** (Bot API) behind a `Notifier` interface, with a console
  fallback for dev.
- **Deferred:** raw hourly astronomic-tide series (SHN `Tmareas` ASP POST form) — so
  `tide_astro` is unpopulated and `v_residual` is currently empty; corrected extremes from the
  pronóstico are captured. Follow-up: synthesize hourly astro via a harmonic model (`utide`).
- ~~Confirm before first deploy:~~ **done 2026-08-30** — `MD_CREATE_FLIGHT` takes
  `schedule_cron` and `flight_secret_names`; `MD_UPDATE_FLIGHT` keys on `flight_id`.
- **Scheduling changed 2026-08-30:** MotherDuck rejected every scheduled Flight with
  "Scheduled runs are not available on your plan. Upgrade to a Business plan." The cron moved
  to `.github/workflows/run.yml`. This reverses the PLAN decision below that rejected Actions
  as a scheduler — that rationale assumed Flights' native cron was available. `sync_flights.py`
  is kept and is correct; it needs only a plan upgrade.

## Context

A *sudestada* is a persistent SE wind over the Río de la Plata that piles water up the
estuary and floods the low-lying Tigre / Paraná Delta. The goal is a "sudestada watch":
first **gather** the relevant data programmatically and keep our own history, then **alert**
when conditions point to a flood.

Target stations: **San Fernando** and **Pilote Norden**. Target variables: **measured water
level**, **astronomic tide**, **wind**, and **official forecasts** (incl. SHN's *Pronóstico
Mareológico*).

Storage is **MotherDuck** (DuckDB cloud). ETL runs as **MotherDuck Flights** (managed,
scheduled Python jobs). **GitHub Actions is used for CI/deploy of the Flight code**, not for
runtime triggering — Flights already provide native cron, secrets, retries, and run history,
and GitHub's scheduled cron is too unreliable for a 15-min poll.

Research (verified live, 2026-08-20) settled the access mechanics for each source. Two are
clean REST APIs; the SHN products require CSV/scrape/PDF.

## Data sources (confirmed reachable, no auth for reads)

| Source | Product | Station(s) | Access | Mechanism |
|---|---|---|---|---|
| **INA a5** | Observed level (~15 min) | San Fernando `series_id 52`, Pilote Norden `series_id 3345` | `GET /a5/obs/puntual/series/{id}/observaciones?timestart=&timeend=[&format=csv]` | JSON REST API |
| **INA a5** | Forecast level (~7-day hourly, p05/p25/main/p75/p95) | San Fernando `cal_id 432` | `GET /a5/sim/calibrados/432/corridas/last?includeProno=true` | JSON REST API |
| **SHN** | Observed hourly heights (rolling 10 days) | San Fernando **and** Pilote Norden (same table) | `GET /oceanografia/AlturasHorarias.asp?export=csv` | CSV (ISO-8859-1) |
| **SHN** | Astronomic tide table | San Fernando | `/oceanografia/Tmareas/Form_Tmareas.asp` | HTML scrape |
| **SHN** | *Pronóstico Mareológico* | Río de la Plata Interior (incl. San Fernando) | `/oceanografia/pronostico.asp` + stable PDF `/Oceanografia/pronostico/pronostico.pdf` | HTML + PDF poll |
| **SHN** | ⭐ Official sudestada alerts | per-station peak + time | `/oceanografia/AACRIOPLA.asp` | HTML scrape |
| **Open-Meteo** | Wind forecast + gusts | point ~ Tigre (-34.42, -58.58) | `api.open-meteo.com/v1/forecast?...hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m` | JSON REST, no key |
| **Open-Meteo** | Historical ERA5 wind (backtesting) | same point | `archive-api.open-meteo.com/v1/archive` | JSON REST, no key |
| **SMN** *(optional)* | Observed wind ground truth | San Fernando / Aeroparque | `ws.smn.gob.ar/map_items/weather` | de-facto JSON |

INA base: `https://alerta.ina.gob.ar/a5` (Swagger `/a5/swagger/index.html`; Python `a5-client`).

## Architecture — MotherDuck-native

```
repo/
  flights/
    ingest_levels.py     # INA (52, 3345) + SHN AlturasHorarias CSV -> observation
    ingest_wind.py       # Open-Meteo forecast+gusts -> observation/forecast
    ingest_forecasts.py  # INA cal_id 432 + SHN pronostico + AACRIOPLA + tide table
    eval_alerts.py       # run alert SQL over views, dedupe, send notification
  sql/
    schema.sql           # tables + primary keys
    views.sql            # v_residual, v_wind_features, v_latest_level
  lib/
    md.py                # MotherDuck connection (duckdb.connect('md:...'))
    ina.py shn.py wind.py # fetch + normalize helpers (return arrow/pandas frames)
    notify.py            # Notifier interface + email/WhatsApp impls
  deploy/
    sync_flights.py      # MD_CREATE_FLIGHT / apply schema+views (run by GitHub Action)
  .github/workflows/deploy.yml
```

**Flights & cadence** (each its own native cron):
- `ingest_levels` — every **15 min** (INA + SHN observed).
- `ingest_wind` — **hourly** (Open-Meteo forecast+gusts; refreshes forward-looking rows).
- `ingest_forecasts` — **hourly** (INA forecast run, SHN pronóstico/alerts/tide).
- `eval_alerts` — every **15 min**, after levels.

Each Flight: `fetch → normalize to a frame → register frame in DuckDB → idempotent upsert`.
Fetching/parsing (ISO-8859-1 CSV, PDF, HTML, JSON) is Python; everything after landing is SQL.

### Tables (DuckDB, in a MotherDuck database e.g. `sudestada`)

- **observation**(`source`, `station`, `variable`, `ts_utc`, `value` DOUBLE, `unit`,
  `ingested_at`) — PK (`source`,`station`,`variable`,`ts_utc`).
- **forecast**(`source`, `station`, `variable`, `run_utc`, `valid_utc`, `value`, `qualifier`,
  `ingested_at`) — PK (`source`,`station`,`variable`,`run_utc`,`valid_utc`,`qualifier`);
  holds INA p05..p95 bands and SHN pronóstico peaks.
- **official_alert**(`source`, `issued_utc`, `station`, `peak_value`, `peak_time_utc`,
  `raw_text`, `url`) — from SHN AACRIOPLA.
- **alert_event**(`ts_utc`, `rule`, `severity`, `station`, `message`, `notified`) — dedupe log.

`variable` ∈ {`level_observed`,`level_forecast`,`tide_astro`,`wind_speed`,`wind_dir`,
`wind_gust`,`residual`}. **Idempotent upsert:** `INSERT INTO t SELECT * FROM frame ON CONFLICT
DO NOTHING` (or `DO UPDATE` for forecast rows), leaning on the primary keys. Rerunning a Flight
never duplicates rows.

### Derived signals as SQL views (the real sudestada signal)

- **`v_residual`**: `level_observed − tide_astro` per station/ts = the meteorological surge
  (more diagnostic than raw level, which is dominated by ordinary tide).
- **`v_wind_features`**: over trailing N hours, fraction of hours with `wind_dir` in
  [112.5°,157.5°] (ESE–SSE) above a speed floor, plus max gust — the "sustained SE" precursor.
- **`v_latest_level`**: newest observed level per station.

These keep `eval_alerts` mostly declarative SQL.

## Alerting engine (`eval_alerts` Flight)

Runs SQL over the views + `official_alert`, applies rules (highest authority first), writes
`alert_event`, and sends a notification via `notify.py`. Thresholds are config in the repo.

1. **Official SHN alert** in AACRIOPLA for our stations → forward verbatim (highest confidence).
2. **Observed level** ≥ threshold at San Fernando / Pilote Norden (INA metadata `nivel_alerta`
   where present; else historical quantile once we've accumulated history).
3. **Forecast level** — INA `cal_id 432` `main` ≥ threshold within lead-time window → early
   warning; escalate if p75/p95 also cross.
4. **Meteorological precursor** — `v_wind_features` sustained SE over threshold + rising
   `v_residual` → "sudestada developing" watch.

Severity `watch / warning / alert`. **Dedupe** via `alert_event`: a standing condition
notifies once per issuance, not every 15-min tick. `notify.py` sends via the **Telegram Bot
API** (`POST https://api.telegram.org/bot<token>/sendMessage`, `chat_id` + `text`) — a single
`requests` call, no extra SDK — behind a `Notifier` interface so other channels drop in later.
Bot token + chat id live in **MotherDuck Flight secrets**, not the repo.

## Orchestration & deploy

- **Runtime:** MotherDuck Flights native cron (managed retries + run history).
- **CI/deploy:** GitHub Actions on push to `main` runs `deploy/sync_flights.py` → applies
  `schema.sql`/`views.sql` and `MD_CREATE_FLIGHT` (create/update) so the repo is the source of
  truth and Flights are versioned. `motherduck_token` stored as a GitHub secret; the DuckDB CLI
  / Python client connects via `md:` using that token.

## Key caveats to handle

- **Timezones:** SHN pages local ART (UTC−3); INA a5 UTC (`...Z`); Open-Meteo configurable —
  **store everything UTC**, convert at the edges.
- **Vertical datum:** ~~may use different reference zeros~~ — **measured 2026-08-30: SHN and INA are
  identical** (max |INA − SHN| = 0.000 m across 130 same-instant pairs) — they republish the same
  gauge, so they are not independent sources and cannot cross-validate each other. Still compute
  residuals **within a single source**; the feared datum step does not exist.
- **SHN CSV:** ISO-8859-1; `S/D`/`F/S` = missing → null.
- **10-day window:** SHN observed CSV retains only 10 days → our MotherDuck tables are the
  long-term archive; the 15-min Flight must run reliably.
- **Politeness:** INA caches ~15 min; poll observed ~15 min, forecast per new `forecast_date`,
  SHN pages hourly, `pronostico.pdf` by content hash.

## Verification (end-to-end)

1. Run each Flight once (locally via `python flights/ingest_levels.py` against a dev MotherDuck
   db, then in the Flights UI) → rows land in `observation`/`forecast`/`official_alert`.
2. Assert INA observed San Fernando (52) + Pilote Norden (3345) rows for last 24 h; INA
   forecast (432) has all five qualifiers.
3. Assert SHN CSV parsed both stations; spot-check a value vs the live page.
4. Assert Open-Meteo wind rows (speed/dir/gust) for the Tigre point.
5. `SELECT * FROM v_residual`/`v_wind_features` return sensible values.
6. Force a synthetic low threshold → `eval_alerts` raises an `alert_event`, notifies once, and
   does **not** re-notify on the next tick (dedupe). Rerun any Flight → no duplicate rows
   (ON CONFLICT idempotency).

## Suggested build order

1. `sql/schema.sql` + `sql/views.sql` + `lib/md.py`.
2. `lib/ina.py` + `lib/shn.py` + `flights/ingest_levels.py` (the two confirmed core feeds).
3. `lib/wind.py` + `flights/ingest_wind.py`; wire `v_residual`/`v_wind_features`.
4. `flights/ingest_forecasts.py` (INA forecast + SHN pronóstico/alerts/tide).
5. `flights/eval_alerts.py` + `lib/notify.py` (Telegram) + dedupe.
6. `deploy/sync_flights.py` + `.github/workflows/deploy.yml`; set Flight crons + secrets.
