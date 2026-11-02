# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A "sudestada watch": ingests Río de la Plata / Paraná Delta water data (San Fernando + Pilote
Norden) and raises flood alerts. Storage is **MotherDuck** (DuckDB cloud); the ETL runs as
ONE **scheduled MotherDuck Flight**, `sudestada-hourly` (registered by
`deploy/sync_flights.py`); alerts go to **Telegram**. GitHub Actions only applies the schema
(`deploy.yml`) and publishes the public site (`run.yml`). (From 2026-08-30 to 2026-11-02 the
ETL ran in Actions because scheduled Flights need a paid plan; the account is now Lite + card.)
The charts are MotherDuck **Dives** (`dives/`), which `run.yml` also republishes hourly as a
public static site at https://juanaldao.github.io/sudestada-watch/ (no MotherDuck account
needed). See `README.md` and `PLAN.md` for the full rationale.

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

# Register/update the production Flight (not CI; --no-schedule / --notify-test for testing)
MOTHERDUCK_TOKEN=... python deploy/sync_flights.py

# Deploy: create the database + apply schema/views (what CI runs on push)
export MOTHERDUCK_TOKEN=...
python deploy/init_db.py

# Public site: snapshot the Dive queries, bundle, preview (needs Node 22)
python site/export_data.py         # honours SUDESTADA_DB / MOTHERDUCK_TOKEN
cd site && npm ci && npm run build && python -m http.server -d dist
```

The only build step is the site bundle (`site/build.mjs`, esbuild). There is no linter config or test framework — the `tests/smoke_*.py` scripts ARE
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
- `flights/*.py` — the four ETL modules, each with a `main()`; each source is wrapped in
  try/except so one failing feed doesn't sink the run. The `sudestada-hourly` Flight runs
  **all four hourly at :03** in dependency order, so
  `eval_alerts` always reads data ingested seconds earlier. Both sources publish at :45, so
  hourly matches the real resolution -- the original 15-min poll re-fetched identical rows.
- `dives/*/*.tsx` — MotherDuck Dives, ALSO published publicly to GitHub Pages by the `site` job
  in `run.yml` (README "Public site"): `site/export_data.py` snapshots each `useSQLQuery`
  literal, and the esbuild bundle aliases that hook to `site/src/shim.js`. Keep Dive SQL as
  plain template literals (no `${}`) and only import packages listed in `site/package.json`.
- `lib/sql/schema.sql` (tables + PKs) and `views.sql` (`v_residual`, `v_latest_level`,
  `v_wind_features`, `v_level_events` -- the extreme-level events behind the History Dive). Views are `CREATE OR REPLACE`; tables are `IF NOT EXISTS`.
- `deploy/init_db.py` — creates the database + applies schema/views; this is what CI runs.
- `deploy/backfill_ina.py` — one-off INA San Fernando hourly history since 2011, run manually
  via `backfill.yml`. Idempotent like everything else.
- `deploy/sync_flights.py` — registers `sudestada-hourly` (F4, secret `sudestada_telegram`,
  installs the repo `@main`, so a push ships code). NOT run by CI; re-run it only when the
  bootstrap, schedule or secrets change. The bootstrap exits before `eval_alerts` if the
  Telegram env vars are missing: the console fallback returns True, so alerts would be marked
  sent in `alert_event` and never delivered.
- `run.yml` `site` job ends with a **staleness check** (`max(observation.ingested_at)` < 2 h),
  the only alarm if the Flight silently stops running.

## Conventions that will bite you if ignored

- **UTC everywhere in storage.** Convert at the edges: SHN pages are local ART (UTC−3, add 3 h
  via `lib/shn.py::_local_to_utc`); INA is already UTC (`...Z`); Open-Meteo requested as UTC.
- **Compute residuals within a single source.** `v_residual` joins observed and tide within one
  source, because a source's tide prediction is on that source's own reference. (An earlier note here claimed INA
  reads ~1.3 m higher than SHN at the same instant — that is **wrong**. Measured 2026-08-30 over
  130 same-instant pairs: **max |INA − SHN| = 0.000 m**. They are not merely close, they are
  identical, which means the two feeds republish the same gauge data for these stations. Treat
  them as ONE source for validation purposes — agreement between them proves nothing, and a bad
  gauge corrupts both. `tests/smoke_levels.py` prints this delta on every run.)
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
- **Actions cron drifts.** Scheduled runs are queued and can be late or skipped. That now only
  affects the public site: in practice `schedule` fired only 4-6x/day, so the site's real
  hourly clock is **cron-job.org POSTing `workflow_dispatch` at :10** (README "Hourly
  trigger"); `schedule` is just a fallback. Never put ingestion or `eval_alerts` back in
  Actions while the Flight runs — two evaluators racing could send an alert twice.
- **DuckDB is pinned exactly** (`requirements.txt`, `pyproject.toml`). The `motherduck` extension
  ships days after each DuckDB release; unpinned, every `md:` connect 404'd for 3.7 days. Bump
  only once MotherDuck supports the new version.

## Known follow-ups (see README "Known follow-ups")

- Raw hourly astronomic tide (SHN `Tmareas` ASP form) is NOT ingested yet → `tide_astro` empty
  → `v_residual` empty. Corrected pleamar/bajamar from the Pronóstico ARE captured.
- Level thresholds in `lib/config.py` are placeholders — tune from history/ERA5 backtests.
- ~~Validate the `MD_CREATE_FLIGHT` arg names~~ — done 2026-08-30 against the MotherDuck SQL
  reference: the cron arg is `schedule_cron` (optional), the secrets arg is
  `flight_secret_names` (`VARCHAR[]` of `TYPE FLIGHTS` secrets, each key injected as a bare env
  var), and `MD_UPDATE_FLIGHT` keys on `flight_id` (UUID) resolved via `MD_LIST_FLIGHTS()` —
  its `name` arg renames. Without `instance_type` a Flight gets the plan default (F16).
