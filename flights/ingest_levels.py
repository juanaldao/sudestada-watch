"""Flight: ingest observed water levels (every 15 min).

Sources: INA a5 (San Fernando 52, Pilote Norden 3345) + SHN AlturasHorarias CSV (both).
Idempotent — reruns never duplicate rows (ON CONFLICT DO NOTHING on the observation PK).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lib import config, ina, shn
from lib.md import connect, ensure_schema, upsert

CONFLICT = ["source", "station", "variable", "ts_utc"]


def main() -> None:
    con = connect()
    ensure_schema(con)

    total = 0
    for station, series_id in config.INA_OBSERVED_SERIES.items():
        try:
            df = ina.fetch_observed(station, series_id)
            n = upsert(con, "observation", df, CONFLICT)
            total += n
            print(f"[ina] {station}: {n} rows")
        except Exception as e:  # one bad source must not sink the Flight
            print(f"[ina] {station} ERROR: {e!r}")

    try:
        df = shn.fetch_observed_levels()
        n = upsert(con, "observation", df, CONFLICT)
        total += n
        print(f"[shn] observed levels: {n} rows")
    except Exception as e:
        print(f"[shn] ERROR: {e!r}")

    con.close()
    print(f"ingest_levels done — {total} rows processed")


if __name__ == "__main__":
    main()
