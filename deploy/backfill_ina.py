"""One-off: backfill INA hourly San Fernando levels into `observation`, year by year.

This is the data `v_level_events` and the history Dive read. INA series 52 is hourly from
2011; before that it holds one reading a day, which cannot resolve a tide, so the default
range starts at 2011. Pilote Norden (3345) has no history before 2026, so it is skipped.
Idempotent (ON CONFLICT DO NOTHING on the observation PK): reruns and overlap with the hourly
ingest_levels job are harmless.

Usage: python deploy/backfill_ina.py [first_year] [last_year]   (default 2011 .. this year)
Run in CI via .github/workflows/backfill.yml, or locally with SUDESTADA_DB / MOTHERDUCK_TOKEN.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lib import config, ina  # noqa: E402
from lib.md import connect, ensure_schema, upsert, utcnow  # noqa: E402

CONFLICT = ["source", "station", "variable", "ts_utc"]  # same as flights/ingest_levels.py


def main() -> None:
    this_year = utcnow().year
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 2011
    last = int(sys.argv[2]) if len(sys.argv) > 2 else this_year

    station = config.SAN_FERNANDO
    series_id = config.INA_OBSERVED_SERIES[station]
    con = connect()
    ensure_schema(con)

    total = 0
    for year in range(first, last + 1):
        df = ina.fetch_observed(station, series_id, start=f"{year}-01-01", end=f"{year + 1}-01-01")
        n = upsert(con, "observation", df, CONFLICT)
        total += n
        print(f"[ina] {station} {year}: {n} rows")

    con.close()
    print(f"backfill done — {total} rows processed")


if __name__ == "__main__":
    main()
