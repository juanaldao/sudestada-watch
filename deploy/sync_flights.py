"""Register/update the Sudestada Watch production Flight in MotherDuck from this repo.

The ETL runs as ONE scheduled MotherDuck Flight, `sudestada-hourly`; GitHub Actions only
publishes the public site (run.yml) and applies the schema (deploy.yml). NOT RUN BY CI: run it
locally with a token whenever the Flight's source, schedule or secrets change. Scheduling needs
a paid plan: Lite with a card on file (since 2026-11-02), or Business. Without one,
MD_CREATE_FLIGHT with schedule_cron fails with "Scheduled runs are not available on your plan"
(hit 2026-08-30).

ONE hourly Flight runs all four modules in dependency order: the sources publish hourly at
:45, and every Flight run pays a pip-install bootstrap, so four Flights on 15-min crons (the
original design) cost ~10x the compute for no new data.

The Flight's source is a tiny bootstrap that pip-installs THIS repo at @main (via
requirements_txt = the git URL) and calls each module's main(). So the Flight always runs the
pushed code; only a change to the bootstrap, schedule or secrets needs a re-sync.

Telegram credentials live in a MotherDuck secret of TYPE FLIGHTS named `sudestada_telegram`
(keys TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID; create it once, see README). Each key is
injected as a bare env var, which is what lib/notify.py reads. The values are never pushed
from here.

PARAM NAMES are validated against the MotherDuck SQL reference (2026-08-30, 2026-11-02): the
cron argument is `schedule_cron` (optional: omit for an on-demand Flight) and the secrets
argument is `flight_secret_names` (a VARCHAR[], not `secrets`). MD_UPDATE_FLIGHT identifies a
Flight by `flight_id` (UUID) — its `name` argument RENAMES it — so we resolve the id via
MD_LIST_FLIGHTS() first.

Usage:
  python deploy/sync_flights.py                 # create/update sudestada-hourly, scheduled
  python deploy/sync_flights.py --no-schedule   # same, on-demand only (testing)
  python deploy/sync_flights.py --notify-test   # on-demand sudestada-notify-test Flight that
                                                # sends one Telegram message; delete after use
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

_SCHEDULE_ARG = "schedule_cron"  # validated against the MD SQL reference

# One Flight, hourly at :03 UTC. Modules run in this order so eval_alerts reads data ingested
# seconds earlier.
FLIGHT_NAME = "sudestada-hourly"
FLIGHT_CRON = "3 * * * *"
INGESTERS = ["ingest_levels", "ingest_wind", "ingest_forecasts"]
ALERTS = "eval_alerts"
NOTIFY_TEST_NAME = "sudestada-notify-test"

FLIGHT_SECRET = "sudestada_telegram"
# F4 is the smallest size; the plan default (F16) is 4x the price for a ~20 s I/O-bound run.
INSTANCE_TYPE = "F4"
MAX_RUNTIME_SEC = 600

DEFAULT_REPO = "git+https://github.com/juanaldao/sudestada-watch.git@main"

# Per-module Flights from the original 15-min design. Never scheduled (2026-08-30 error), but
# if any exist they would double the work, so main() warns about them.
LEGACY_FLIGHTS = [
    "sudestada-ingest-levels",
    "sudestada-ingest-wind",
    "sudestada-ingest-forecasts",
    "sudestada-eval-alerts",
    "sudestada-ingest-trial",
]


def repo_requirements() -> str:
    """The pip requirement that installs this repo into the Flight runtime.

    Tracks @main, not a sha, so a push is all it takes to update the Flight's code.
    """
    return os.environ.get("REPO_URL") or DEFAULT_REPO


def source_for() -> str:
    """Ingest, then refuse to evaluate alerts without Telegram credentials.

    Without them lib/notify.py falls back to the console notifier, which reports success, so
    eval_alerts would record each alert in alert_event and it would never be sent.
    """
    ingest = "".join(f"from flights import {m}\n{m}.main()\n" for m in INGESTERS)
    guard = (
        "import os, sys\n"
        "if not (os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID')):\n"
        f"    sys.exit('TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set: attach the {FLIGHT_SECRET} "
        f"secret; skipping {ALERTS}')\n"
    )
    return ingest + guard + f"from flights import {ALERTS}\n{ALERTS}.main()\n"


NOTIFY_TEST_SOURCE = (
    "import sys\n"
    "from lib.notify import get_notifier\n"
    "ok = get_notifier().send('\\u2705 sudestada watch: test notification from the Flight. "
    "If you can read this, the alert channel works.')\n"
    "print('delivered:', ok)\n"
    "sys.exit(0 if ok else 1)\n"
)


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _args(source: str, reqs: str, cron: str | None) -> str:
    args = (
        f"source_code := $flight${source}$flight$, "
        f"requirements_txt := {_q(reqs)}, "
        f"flight_secret_names := [{_q(FLIGHT_SECRET)}], "
        f"instance_type := {_q(INSTANCE_TYPE)}, "
        f"max_runtime_sec := {MAX_RUNTIME_SEC}"
    )
    if cron:
        args += f", {_SCHEDULE_ARG} := {_q(cron)}"
    return args


def _create(name: str, source: str, reqs: str, cron: str | None) -> str:
    return f"SELECT * FROM MD_CREATE_FLIGHT(name := {_q(name)}, {_args(source, reqs, cron)})"


def _update(flight_id: str, source: str, reqs: str, cron: str | None) -> str:
    """MD_UPDATE_FLIGHT keys on flight_id; passing `name` would rename the Flight."""
    return f"SELECT * FROM MD_UPDATE_FLIGHT(flight_id := {_q(flight_id)}, {_args(source, reqs, cron)})"


def existing_flights(con) -> dict[str, str]:
    """Map flight_name -> flight_id. The name column is `flight_name`, not `name`."""
    rows = con.execute(
        'SELECT flight_id, flight_name FROM MD_LIST_FLIGHTS("LIMIT" := 1000)'
    ).fetchall()
    return {name: str(fid) for fid, name in rows}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--no-schedule", action="store_true",
                   help="create/update without a cron (on-demand only, for testing)")
    p.add_argument("--notify-test", action="store_true",
                   help=f"create/update the on-demand {NOTIFY_TEST_NAME} Flight instead")
    opts = p.parse_args()

    token = (os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token") or "").strip()
    if not token:
        print("MOTHERDUCK_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    db = os.environ.get("SUDESTADA_DATABASE", "sudestada")
    # Token as config, not in the URI — see lib/md.py::connect. Connect to bare `md:` so we
    # can create the database on a fresh account; schema.sql/views.sql are unqualified, so
    # USE it before applying them.
    con = duckdb.connect("md:", config={"motherduck_token": token})
    con.execute(f'CREATE DATABASE IF NOT EXISTS "{db}"')
    con.execute(f'USE "{db}"')

    # Ensure the database schema/views are current (Flights also self-apply, this is a backstop).
    from pathlib import Path
    sql_dir = Path(__file__).resolve().parent.parent / "lib" / "sql"
    con.execute((sql_dir / "schema.sql").read_text(encoding="utf-8"))
    con.execute((sql_dir / "views.sql").read_text(encoding="utf-8"))

    if opts.notify_test:
        name, src, cron = NOTIFY_TEST_NAME, NOTIFY_TEST_SOURCE, None
    else:
        name, src = FLIGHT_NAME, source_for()
        cron = None if opts.no_schedule else FLIGHT_CRON

    reqs = repo_requirements()
    print(f"Flight requirements: {reqs}")
    known = existing_flights(con)
    fid = known.get(name)
    try:
        if fid is None:
            con.execute(_create(name, src, reqs, cron))
            print(f"created  {name}  ({cron or 'on-demand'})")
        else:
            con.execute(_update(fid, src, reqs, cron))
            print(f"updated  {name}  ({cron or 'schedule unchanged'})")
    except duckdb.Error as e:
        con.close()
        sys.exit(f"FAILED   {name}: {e}")
    known = existing_flights(con)
    con.close()
    print(f"flight_id {known.get(name)}  ->  CALL MD_RUN_FLIGHT(flight_id := '{known.get(name)}')")
    leftover = [n for n in LEGACY_FLIGHTS if n in known]
    if leftover:
        print(f"\nWARNING: legacy Flights still exist: {', '.join(leftover)}. "
              "Delete them (MD_DELETE_FLIGHT or the UI), or they will run alongside this one.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
