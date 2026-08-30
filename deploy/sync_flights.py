"""Register/update the Sudestada Watch Flights in MotherDuck from this repo.

Run by GitHub Actions on push (see .github/workflows/deploy.yml), or locally with a token.

Each Flight's source is a tiny bootstrap that pip-installs THIS repo (via requirements_txt =
the git URL) and calls the module's main(). So the Flight always runs the pushed code.

NOTE ON PARAM NAMES: `name`, `source_code`, `requirements_txt` are confirmed from the MD docs.
The `schedule` (cron) and `secrets` argument names should be validated against the current
MotherDuck SQL reference for MD_CREATE_FLIGHT / MD_UPDATE_FLIGHT — they are isolated in
_SCHEDULE_ARG below so a rename is a one-line change. Telegram secrets are NOT pushed from
here (to avoid leaking them into CI logs); set them once as Flight secrets (see README).
"""
from __future__ import annotations

import os
import sys

import duckdb

_SCHEDULE_ARG = "schedule"  # <- validate against MD reference; rename here if needed

# name, importable module in the `flights` package, cron (UTC). Alerts run a few minutes
# after the ingesters so they see the freshest data.
FLIGHTS = [
    {"name": "sudestada-ingest-levels", "module": "ingest_levels", "cron": "*/15 * * * *"},
    {"name": "sudestada-ingest-wind", "module": "ingest_wind", "cron": "0 * * * *"},
    {"name": "sudestada-ingest-forecasts", "module": "ingest_forecasts", "cron": "5 * * * *"},
    {"name": "sudestada-eval-alerts", "module": "eval_alerts", "cron": "7,22,37,52 * * * *"},
]


def repo_requirements() -> str:
    """Build the pip requirement that installs this repo into the Flight runtime."""
    explicit = os.environ.get("REPO_URL")
    if explicit:
        return explicit
    # Derived from GitHub Actions env: github.com/OWNER/REPO @ current sha.
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY")
    ref = os.environ.get("GITHUB_SHA") or os.environ.get("GITHUB_REF_NAME", "main")
    if not repo:
        raise RuntimeError("Set REPO_URL (e.g. git+https://github.com/you/sudestada-watch.git@main)")
    return f"git+{server}/{repo}.git@{ref}"


def source_for(module: str) -> str:
    return f"from flights import {module}\n{module}.main()\n"


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _call(fn: str, name: str, source: str, reqs: str, cron: str) -> str:
    return (
        f"SELECT * FROM {fn}("
        f"name := {_q(name)}, "
        f"source_code := $flight${source}$flight$, "
        f"requirements_txt := {_q(reqs)}, "
        f"{_SCHEDULE_ARG} := {_q(cron)})"
    )


def main() -> None:
    token = os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token")
    if not token:
        print("MOTHERDUCK_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    db = os.environ.get("SUDESTADA_DATABASE", "sudestada")
    con = duckdb.connect(f"md:{db}?motherduck_token={token}")

    # Ensure the database schema/views are current (Flights also self-apply, this is a backstop).
    from pathlib import Path
    sql_dir = Path(__file__).resolve().parent.parent / "lib" / "sql"
    con.execute((sql_dir / "schema.sql").read_text(encoding="utf-8"))
    con.execute((sql_dir / "views.sql").read_text(encoding="utf-8"))

    reqs = repo_requirements()
    print(f"Flight requirements: {reqs}")
    for f in FLIGHTS:
        src = source_for(f["module"])
        try:
            con.execute(_call("MD_CREATE_FLIGHT", f["name"], src, reqs, f["cron"]))
            print(f"created  {f['name']}  ({f['cron']})")
        except duckdb.Error as e:
            # Already exists (or create not idempotent) -> update in place.
            try:
                con.execute(_call("MD_UPDATE_FLIGHT", f["name"], src, reqs, f["cron"]))
                print(f"updated  {f['name']}  ({f['cron']})")
            except duckdb.Error as e2:
                print(f"FAILED   {f['name']}: create={e} update={e2}", file=sys.stderr)
    con.close()
    print("\nReminder: set Flight secrets TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in MotherDuck "
          "(UI: Flights > secrets, or MD_UPDATE_FLIGHT ... secrets := ...). See README.")


if __name__ == "__main__":
    main()
