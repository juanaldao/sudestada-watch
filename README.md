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
   The **run** workflow then executes each job hourly (see *Hourly trigger* below).
4. **Add repo secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`** so alerts reach Telegram;
   without them they print to the workflow log. Verify the channel with
   `gh workflow run "run sudestada jobs" -f job=notify_test` — alerts are rare, so don't wait
   for a real one to find out whether delivery works.
   Get a token from @BotFather; get the chat id by messaging the bot and reading
   `https://api.telegram.org/bot<token>/getUpdates`.

### Hourly trigger (cron-job.org)

GitHub's `schedule` trigger is best-effort: with `52 * * * *` it actually fired only 4–6 times
a day. So an external cron calls the workflow's `workflow_dispatch` API instead, and the
`schedule` entry stays as a fallback.

1. Create a **fine-grained PAT** scoped to this repo only, permission **Actions: Read and
   write**, nothing else. Set an expiry and put a reminder in your calendar to renew it.
   When it expires the dispatches start failing with 401.
2. On cron-job.org, create a job:
   - URL: `https://api.github.com/repos/juanaldao/sudestada-watch/actions/workflows/run.yml/dispatches`
   - Schedule: every hour at minute **52**, timezone UTC
   - Method **POST**, body `{"ref":"main"}` (`job` defaults to `all`)
   - Headers: `Authorization: Bearer <PAT>`, `Accept: application/vnd.github+json`,
     `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`
   - Enable failure notifications. A successful dispatch returns **204**.
3. Check: the next run in the Actions tab shows event `workflow_dispatch`.

> **DuckDB is pinned** (`duckdb==1.5.6`). The `md:` connection loads the `motherduck`
> extension, which MotherDuck publishes some days *after* each DuckDB release. An unpinned
> install picked up a fresh release and every run 404'd for 3.7 days (2026-09-28 → 10-02).
> Bump the pin only once MotherDuck supports the new version.

> `deploy/sync_flights.py` is correct and validated against the MotherDuck SQL reference
> (2026-08-30): `schedule_cron`, `flight_secret_names` (`VARCHAR[]`), and `flight_id` (not
> `name`) for `MD_UPDATE_FLIGHT`. It only needs a Business plan to run.

## Public site (GitHub Pages)

The Dives need a MotherDuck account to view, so the **run** workflow also publishes them as a
public static site, rebuilt every hour in a `site` job after ingestion:

1. `site/export_data.py` pulls every `useSQLQuery(`...`)` literal out of `dives/*/*.tsx`,
   runs it against MotherDuck, and writes the rows to `site/dist/data.json`, keyed by the
   whitespace-normalised SQL.
2. `site/build.mjs` (esbuild) bundles the Dive `.tsx` files **unchanged**, aliasing
   `@motherduck/react-sql-query` to `site/src/shim.js`, which serves that snapshot.

So the Dives stay the single source of truth: edit a Dive and the site follows on the next run.
Query SQL must stay a plain template literal (no `${...}`), or the export refuses it. No token
reaches the browser. Enable once: *Settings → Pages → Source: GitHub Actions*. Republish on
demand with `gh workflow run "run sudestada jobs" -f job=site`.

Local preview:

```bash
SUDESTADA_DB=./_smoke.duckdb python site/export_data.py   # or MOTHERDUCK_TOKEN=...
cd site && npm ci && npm run build && python -m http.server -d dist
```

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
