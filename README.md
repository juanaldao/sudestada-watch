# Sudestada Watch

Gathers Río de la Plata / Paraná Delta water data for **San Fernando** and **Pilote Norden**
and raises alerts when a *sudestada* (persistent SE wind piling water up the estuary) threatens
flooding near Tigre.

- **Storage:** MotherDuck (DuckDB cloud).
- **ETL:** MotherDuck Flights (scheduled Python, native cron).
- **Deploy:** GitHub Actions on push (registers/updates the Flights; does not trigger them).
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
deploy/         sync_flights.py — registers Flights via MD_CREATE_FLIGHT/MD_UPDATE_FLIGHT
tests/          smoke_*.py — run each stage end-to-end against a local DuckDB
```

Flights & cadence (UTC): `ingest_levels` every 15 min · `ingest_wind` hourly ·
`ingest_forecasts` hourly · `eval_alerts` at :07/:22/:37/:52.

## Tables

`observation` (level/tide/wind + residual), `forecast` (INA bands + SHN extremes + wind),
`official_alert` (SHN AACRIOPLA), `shn_bulletin` (Pronóstico text), `alert_event` (what we
raised; dedupe log). Derived views: `v_residual`, `v_latest_level`, `v_wind_features`.

All timestamps are UTC. **Datum caveat:** SHN and INA use different vertical zeros — never
compare their absolute levels; residuals are computed within a single source.

## Local dev

```bash
uv venv --python 3.12                 # system Python is PEP 668 externally-managed
source .venv/bin/activate
uv pip install -r requirements.txt

export SUDESTADA_DB=./_smoke.duckdb   # use a local DuckDB file instead of MotherDuck
python tests/smoke_alerts.py          # full pipeline: ingest -> evaluate -> notify (console)
```

Run one Flight locally against MotherDuck:

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
3. Push to `main` → the **deploy** workflow applies schema/views and registers/updates the
   four Flights. Each Flight pip-installs this repo and runs its module on its cron.
4. **Set Telegram secrets on the Flights** (once) in the MotherDuck UI (Flights → secrets) or
   via `MD_UPDATE_FLIGHT(... secrets := ...)`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
   Get a token from @BotFather; get the chat id by messaging the bot and reading
   `https://api.telegram.org/bot<token>/getUpdates`.

> The `schedule`/`secrets` argument names in `deploy/sync_flights.py` are isolated at the top
> of that file — validate them against the current MotherDuck SQL reference and adjust if the
> API differs.

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
