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
