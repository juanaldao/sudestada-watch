-- Sudestada Watch — derived-signal views. Rerun-safe (CREATE OR REPLACE).

-- Meteorological surge = observed level - astronomic tide, computed WITHIN a single source
-- (a source's tide prediction is on that source's own reference, so never cross them here).
-- NB: measured 2026-08-30, SHN and INA absolute levels are identical (max delta 0.000 m over
-- 130 same-instant pairs) -- same gauge, not two sources. An earlier note claiming a ~1.3 m
-- datum offset between them was wrong. This residual is the
-- real sudestada signal; raw level is dominated by the ordinary astronomic tide.
CREATE OR REPLACE VIEW v_residual AS
SELECT
    obs.source,
    obs.station,
    obs.ts_utc,
    obs.value - tide.value AS residual_m
FROM observation AS obs
JOIN observation AS tide
  ON  tide.source  = obs.source
  AND tide.station = obs.station
  AND tide.ts_utc  = obs.ts_utc
  AND tide.variable = 'tide_astro'
WHERE obs.variable = 'level_observed'
  AND obs.value IS NOT NULL
  AND tide.value IS NOT NULL;

-- Newest observed level per source/station.
CREATE OR REPLACE VIEW v_latest_level AS
SELECT source, station, ts_utc, value AS level_m, unit
FROM observation
WHERE variable = 'level_observed' AND value IS NOT NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY source, station ORDER BY ts_utc DESC) = 1;

-- Sustained-wind precursor over the trailing 12 h at the Tigre point.
-- SE sector = wind direction in [112.5, 157.5) deg (ESE-SSE). eval_alerts applies the
-- speed/fraction thresholds; this view just exposes the raw aggregates.
CREATE OR REPLACE VIEW v_wind_features AS
WITH recent AS (
    SELECT ts_utc, variable, value
    FROM observation
    WHERE station = 'tigre_point'
      AND variable IN ('wind_speed', 'wind_dir', 'wind_gust')
      AND ts_utc >= now() - INTERVAL 12 HOUR
),
pivoted AS (
    SELECT
        ts_utc,
        MAX(value) FILTER (WHERE variable = 'wind_speed') AS wind_speed,
        MAX(value) FILTER (WHERE variable = 'wind_dir')   AS wind_dir,
        MAX(value) FILTER (WHERE variable = 'wind_gust')  AS wind_gust
    FROM recent
    GROUP BY ts_utc
)
SELECT
    count(*)                                                                   AS n_hours,
    avg(wind_speed)                                                            AS mean_speed_ms,
    max(wind_gust)                                                             AS max_gust_ms,
    avg(CASE WHEN wind_dir >= 112.5 AND wind_dir < 157.5 THEN 1.0 ELSE 0.0 END) AS frac_se
FROM pivoted;

-- Extreme-level EVENTS at San Fernando, for the history Dive. Only hours at/above 2.5 m
-- ('high', the warning threshold in lib/config.py::LEVEL_THRESHOLDS_M) or at/below 0.1 m
-- ('low', bajante) count; ordinary levels are dropped. INA only: it carries the history
-- back to 2011 (deploy/backfill_ina.py) and SHN republishes the same gauge, so including
-- both would double-count. Gaps-and-islands per kind: a qualifying hour more than 12 h after
-- the previous one starts a new event, so the successive high tides of one sudestada merge.
-- Isolated gauge spikes (one reading > 0.8 m away from BOTH neighbours, same direction, e.g.
-- 1.59 -> 2.85 -> 1.41 in Jan 2019) are dropped first, or they would read as fake events.
CREATE OR REPLACE VIEW v_level_events AS
WITH lv AS (
    SELECT ts_utc, value,
           value - lag(value)  OVER w AS d_prev,
           value - lead(value) OVER w AS d_next
    FROM observation
    WHERE source = 'ina' AND station = 'san_fernando' AND variable = 'level_observed'
      AND value IS NOT NULL
    WINDOW w AS (ORDER BY ts_utc)
),
hits AS (
    SELECT ts_utc, value,
           CASE WHEN value >= 2.5 THEN 'high' ELSE 'low' END AS kind
    FROM lv
    WHERE (value >= 2.5 OR value <= 0.1)
      AND NOT (abs(d_prev) > 0.8 AND abs(d_next) > 0.8 AND sign(d_prev) = sign(d_next))
),
marked AS (
    SELECT *,
           CASE WHEN ts_utc - lag(ts_utc) OVER (PARTITION BY kind ORDER BY ts_utc)
                     <= INTERVAL 12 HOUR THEN 0 ELSE 1 END AS is_new
    FROM hits
),
numbered AS (
    SELECT *, sum(is_new) OVER (PARTITION BY kind ORDER BY ts_utc) AS event_no
    FROM marked
)
SELECT
    kind,
    min(ts_utc) AS start_utc,
    max(ts_utc) AS end_utc,
    count(*)    AS hours,
    CASE WHEN kind = 'high' THEN max(value) ELSE min(value) END AS extreme_m,
    CASE WHEN kind = 'high' THEN arg_max(ts_utc, value) ELSE arg_min(ts_utc, value) END AS extreme_utc
FROM numbered
GROUP BY kind, event_no;
