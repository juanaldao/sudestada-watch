# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A "sudestada watch": ingests Río de la Plata / Paraná Delta water data (San Fernando + Pilote
Norden) and raises flood alerts. Storage is **MotherDuck** (DuckDB cloud); ETL runs as
**scheduled GitHub Actions** (`.github/workflows/run.yml`); alerts go to **Telegram**.
MotherDuck Flights were the original design and the code still suits them, but scheduled
Flights need a Business plan, so Actions carries the cron. `deploy.yml` applies the schema. See `README.md` and `PLAN.md` for the full rationale.

## Commands

```bash
# One-time setup. The system Python is EXTERNALLY-MANAGED (PEP 668) and has no pip,
# so install into a venv; 3.12 matches the CI runner in .github/workflows/deploy.yml.
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt

# Run any stage/pipeline against a LOCAL DuckDB file (no MotherDuck needed):
export SUDESTADA_DB=./_smoke.duckdb
python tests/smoke_schema.py       # schema + views load
python tests/smoke_levels.py       # INA + SHN level ingestion + idempotency
python tests/smoke_wind.py         # Open-Meteo wind + v_wind_features
python tests/smoke_forecasts.py    # INA forecast + SHN pronostico/alerts
python tests/smoke_alerts.py       # FULL end-to-end: ingest -> evaluate -> notify (console)

# Run a single job against MotherDuck (real cloud DB):
MOTHERDUCK_TOKEN=... python flights/ingest_levels.py

# Deploy: create the database + apply schema/views (what CI runs on push)
export MOTHERDUCK_TOKEN=...
python deploy/init_db.py
```

There is no build step, linter config, or test framework — the `tests/smoke_*.py` scripts ARE
the test suite (plain asserts, hitting live APIs). Set `SUDESTADA_DB` to run them offline-safe
against a throwaway file; delete the file between runs to start clean.

## Connection precedence (`lib/md.py::connect`)

1. `SUDESTADA_DB` set → local DuckDB file (dev/tests).
2. `MOTHERDUCK_TOKEN` set → `md:` with explicit token (CI / local-against-cloud).
3. neither → bare `md:` — only works **inside a Flight**, where MotherDuck injects the token.

## Architecture (the big picture)

Data flows: **fetch/parse in Python (`lib/`) → normalize to a pandas frame → idempotent upsert
into DuckDB → derived signals are SQL views → `eval_alerts` reads views and notifies.**
Everything after the frame lands is SQL; Python only touches the messy edges.

- `lib/{ina,shn,wind}.py` — one fetcher per source. Each returns a DataFrame whose columns
  match a table exactly (`observation`/`forecast`/`official_alert`/`shn_bulletin`).
- `lib/md.py` — connection + `ensure_schema` (applies `lib/sql/*.sql`) + `upsert` (registers
  the frame, `INSERT ... ON CONFLICT DO NOTHING`, or `DO UPDATE` for forecasts).
- `lib/config.py` — stations, source IDs (INA series 52/3345, cal 432), endpoints, thresholds.
- `flights/*.py` — the four scheduled jobs, each with a `main()`; each source is wrapped in
  try/except so one failing feed doesn't sink the run. Scheduled by `run.yml`, which maps the
  cron that fired to a module. Cadence: `ingest_levels` 15 min,
  `ingest_wind` + `ingest_forecasts` hourly, `eval_alerts` at :07/:22/:37/:52.
- `lib/sql/schema.sql` (tables + PKs) and `views.sql` (`v_residual`, `v_latest_level`,
  `v_wind_features`). Views are `CREATE OR REPLACE`; tables are `IF NOT EXISTS`.
- `deploy/init_db.py` — creates the database + applies schema/views; this is what CI runs.
- `deploy/sync_flights.py` — Flights registration. NOT run by CI; needs a Business plan.
  Kept as the path back to Flights if the account is upgraded.

## Conventions that will bite you if ignored

- **UTC everywhere in storage.** Convert at the edges: SHN pages are local ART (UTC−3, add 3 h
  via `lib/shn.py::_local_to_utc`); INA is already UTC (`...Z`); Open-Meteo requested as UTC.
- **Never compare INA vs SHN absolute levels** — different vertical datums (INA reads ~1.3 m
  higher at the same instant). `v_residual` joins observed and tide **within a single source**.
- **Idempotency is load-bearing.** Every table has a natural PK and ingestion relies on
  `ON CONFLICT`. Keep frame columns and PKs in sync when adding fields; reruns must not dup.
- **Alert dedupe** lives in `alert_event` keyed by `(rule, station, dedupe_key)`. A condition
  notifies once; changing a `dedupe_key` formula in `eval_alerts.py` changes re-alert cadence.
- **Encodings:** SHN `AlturasHorarias` CSV is **latin-1**; the SHN `.asp` HTML pages are
  **UTF-8**. Missing values in the CSV are `S/D`/`F/S` → null.
- **Keep the package installable.** The repo is packaged (`pyproject.toml`, packages `lib` +
  `flights`; `lib/sql/*.sql` ships as package data) and both `run.yml` and a Flight invoke a
  module as `from flights import <mod>; <mod>.main()`. Keep imports working from an installed
  package and keep SQL under `lib/sql/` — that is what makes the Flights path still viable.
- **Actions cron drifts.** Scheduled runs are queued and can be late or skipped. Safe here only
  because ingestion is idempotent and alerts dedupe; don't add a job that assumes exact times.

## Known follow-ups (see README "Known follow-ups")

- Raw hourly astronomic tide (SHN `Tmareas` ASP form) is NOT ingested yet → `tide_astro` empty
  → `v_residual` empty. Corrected pleamar/bajamar from the Pronóstico ARE captured.
- Level thresholds in `lib/config.py` are placeholders — tune from history/ERA5 backtests.
- ~~Validate the `MD_CREATE_FLIGHT` arg names~~ — done 2026-08-30 against the MotherDuck SQL
  reference: the cron arg is `schedule_cron`, the secrets arg is `flight_secret_names`
  (`VARCHAR[]`), and `MD_UPDATE_FLIGHT` keys on `flight_id` (UUID) resolved via
  `MD_LIST_FLIGHTS()` — its `name` arg renames. Telegram secrets are set on the Flights, not
  pushed by CI.
