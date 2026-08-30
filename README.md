# Sudestada Watch

Gathers Río de la Plata / Paraná Delta water data for **San Fernando** and **Pilote Norden**
and raises alerts when a *sudestada* (persistent SE wind piling water up the estuary) threatens
flooding near Tigre.

- **Storage:** MotherDuck (DuckDB cloud).
- **ETL:** scheduled GitHub Actions (`.github/workflows/run.yml`). MotherDuck Flights were
  the original design, but scheduled Flights require a Business plan.
- **Deploy:** GitHub Actions on push (creates the database and applies schema/views).
- **Alerts:** Telegram.

## Data sources (all reads are public, no auth)

| Source | What | How |
|---|---|---|
| INA a5 API | Observed level (San Fernando `52`, Pilote Norden `3345`); forecast (`cal 432`, p05–p95) | JSON REST |
| SHN | Observed hourly levels (both stations); Pronóstico Mareológico; AACRIOPLA crecida alerts | CSV / HTML scrape |
| Open-Meteo | Wind speed/dir/gusts (forecast + ERA5 history) at the Tigre point | JSON REST |

## Layout

```
lib/            fetch+normalize helpers, MotherDuck connection, config, notifier, sql/
flights/        the four scheduled jobs (each has a main())
deploy/         init_db.py — creates the DB + applies schema (run by CI)
                sync_flights.py — Flights registration; needs a Business plan, not run by CI
tests/          smoke_*.py — run each stage end-to-end against a local DuckDB
```

Cadence (UTC): all four jobs run **hourly at :52**, in order — levels, wind, forecasts, then
alerts. INA and SHN both publish at :45, so hourly is the sources' own resolution; :52 leaves
7 minutes of margin and avoids the contended top of the hour.

## Tables

`observation` (level/tide/wind + residual), `forecast` (INA bands + SHN extremes + wind),
`official_alert` (SHN AACRIOPLA), `shn_bulletin` (Pronóstico text), `alert_event` (what we
raised; dedupe log). Derived views: `v_residual`, `v_latest_level`, `v_wind_features`.

All timestamps are UTC. Residuals are computed **within a single source** (a source's tide
prediction is on its own reference). SHN and INA absolute levels were checked on 2026-08-30 and
were found **identical** (max |INA − SHN| = 0.000 m over 130 same-instant pairs), so the two
feeds appear to republish the same gauge. An earlier note claiming a ~1.3 m offset was wrong,
and cross-source agreement should not be read as corroboration.

## Local dev

```bash
uv venv --python 3.12                 # system Python is PEP 668 externally-managed
source .venv/bin/activate
uv pip install -r requirements.txt

export SUDESTADA_DB=./_smoke.duckdb   # use a local DuckDB file instead of MotherDuck
python tests/smoke_alerts.py          # full pipeline: ingest -> evaluate -> notify (console)
```

Run one job locally against MotherDuck:

```bash
export MOTHERDUCK_TOKEN=...
python flights/ingest_levels.py
```

Without `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, alerts print to the console.

## Deploy

1. Push this repo to GitHub (public, or configure a token so Flights can `pip install` it).
2. Add repo secret **`MOTHERDUCK_TOKEN`**. Optionally set `REPO_URL`
   (e.g. `git+https://github.com/you/sudestada-watch.git@main`); otherwise it's derived from
   the Actions env at the pushed commit.
3. Push to `main` → the **deploy** workflow creates the database and applies schema/views.
   The **run** workflow then executes each job on its cron.
4. **Add repo secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`** so alerts reach Telegram;
   without them they print to the workflow log. Verify the channel with
   `gh workflow run "run sudestada jobs" -f job=notify_test` — alerts are rare, so don't wait
   for a real one to find out whether delivery works.
   Get a token from @BotFather; get the chat id by messaging the bot and reading
   `https://api.telegram.org/bot<token>/getUpdates`.

> `deploy/sync_flights.py` is correct and validated against the MotherDuck SQL reference
> (2026-08-30): `schedule_cron`, `flight_secret_names` (`VARCHAR[]`), and `flight_id` (not
> `name`) for `MD_UPDATE_FLIGHT`. It only needs a Business plan to run.

## Alert rules (`flights/eval_alerts.py`)

1. `shn_official` — active SHN AACRIOPLA crecida for our stations (authoritative).
2. `observed_threshold` — latest observed level ≥ warning/alert threshold.
3. `forecast_threshold` — INA `main` forecast crosses a threshold within `FORECAST_LEAD_HOURS`.
4. `wind_precursor` — sustained SE wind over the last 12 h (`v_wind_features`).

Thresholds live in `lib/config.py`. Each condition notifies once (dedupe via `alert_event`).

## Known follow-ups

- **Raw astronomic tide table** (SHN `Tmareas` ASP form) is not yet ingested — it needs an
  ASP POST/viewstate flow. Until then `tide_astro` is unpopulated and `v_residual` is empty;
  the *corrected* pleamar/bajamar from the Pronóstico Mareológico **are** captured. A cleaner
  path is a harmonic model (e.g. `utide`) to synthesize the hourly astronomic series and make
  `v_residual` (the true surge signal) fully live.
- Level thresholds are placeholders — tune from accumulated history / ERA5 backtests.
- Optional: SMN observed wind as ground truth alongside Open-Meteo.
