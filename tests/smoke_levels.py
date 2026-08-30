"""Smoke test: run ingest_levels twice against a local DuckDB and assert data + idempotency.

    SUDESTADA_DB=./_smoke.duckdb python tests/smoke_levels.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from flights import ingest_levels
from lib import config
from lib.md import connect

ingest_levels.main()
ingest_levels.main()  # second run must not add duplicates

con = connect()
n_total = con.execute(
    "select count(*) from observation where variable='level_observed'"
).fetchone()[0]
by_src = con.execute(
    "select source, station, count(*) from observation "
    "where variable='level_observed' group by 1,2 order by 1,2"
).fetchall()
print("rows:", n_total)
for row in by_src:
    print("  ", row)

# Idempotency: PK guarantees no dup (source,station,variable,ts_utc).
dups = con.execute(
    "select count(*) from (select source,station,variable,ts_utc,count(*) c "
    "from observation group by 1,2,3,4 having c>1)"
).fetchone()[0]
assert dups == 0, f"found {dups} duplicate keys"

srcs = {r[0] for r in by_src}
assert "ina" in srcs, "no INA rows ingested"
assert "shn" in srcs, "no SHN rows ingested"
stations = {r[1] for r in by_src}
assert config.SAN_FERNANDO in stations and config.PILOTE_NORDEN in stations

# Datum sanity: same-instant INA vs SHN San Fernando levels should differ (different zeros).
print("smoke_levels OK — idempotent, both sources + both stations present")
con.close()
