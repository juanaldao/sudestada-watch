-- Sudestada Watch — MotherDuck / DuckDB schema
-- All timestamps are stored in UTC. See lib/*.py for the normalization at the edges.
--
-- Idempotency: every table has a natural primary key so ingestion Flights can use
--   INSERT ... ON CONFLICT DO NOTHING / DO UPDATE and never create duplicates on rerun.

-- Raw/observed time series: measured level, astronomic tide, wind, and the derived residual.
CREATE TABLE IF NOT EXISTS observation (
    source      VARCHAR   NOT NULL,   -- 'ina' | 'shn' | 'open-meteo' | 'smn'
    station     VARCHAR   NOT NULL,   -- 'san_fernando' | 'pilote_norden' | 'tigre_point'
    variable    VARCHAR   NOT NULL,   -- level_observed | tide_astro | wind_speed | wind_dir | wind_gust | residual
    ts_utc      TIMESTAMP NOT NULL,   -- observation instant, UTC
    value       DOUBLE,               -- NULL = missing (e.g. SHN 'S/D' / 'F/S')
    unit        VARCHAR   NOT NULL,   -- 'm' | 'm/s' | 'deg'
    ingested_at TIMESTAMP NOT NULL,   -- UTC wall-clock at ingestion
    PRIMARY KEY (source, station, variable, ts_utc)
);

-- Forecast time series: INA a5 (p05/p25/main/p75/p95 bands) and SHN pronostico peaks.
CREATE TABLE IF NOT EXISTS forecast (
    source      VARCHAR   NOT NULL,   -- 'ina' | 'shn' | 'open-meteo'
    station     VARCHAR   NOT NULL,
    variable    VARCHAR   NOT NULL,   -- level_forecast | wind_speed | wind_dir | wind_gust
    run_utc     TIMESTAMP NOT NULL,   -- forecast_date / model run time, UTC
    valid_utc   TIMESTAMP NOT NULL,   -- time the forecast value is valid for, UTC
    value       DOUBLE,
    qualifier   VARCHAR   NOT NULL,   -- 'main' | 'p05' | 'p25' | 'p75' | 'p95' | 'peak'
    unit        VARCHAR   NOT NULL,
    ingested_at TIMESTAMP NOT NULL,
    PRIMARY KEY (source, station, variable, run_utc, valid_utc, qualifier)
);

-- Official SHN sudestada / crecida notices (AACRIOPLA). The authoritative alarm.
CREATE TABLE IF NOT EXISTS official_alert (
    source        VARCHAR   NOT NULL DEFAULT 'shn',
    issued_utc    TIMESTAMP NOT NULL,
    station       VARCHAR   NOT NULL,
    peak_value    DOUBLE,             -- predicted peak height (m), if parsed
    peak_time_utc TIMESTAMP,          -- predicted time of peak, UTC
    raw_text      VARCHAR   NOT NULL, -- verbatim notice text
    url           VARCHAR,
    ingested_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (source, issued_utc, station)
);

-- SHN Pronóstico Mareológico bulletins (prose forecast + validity window), kept verbatim.
CREATE TABLE IF NOT EXISTS shn_bulletin (
    issued_utc     TIMESTAMP NOT NULL,
    valid_from_utc TIMESTAMP,
    valid_to_utc   TIMESTAMP,
    raw_text       VARCHAR   NOT NULL,
    url            VARCHAR,
    ingested_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (issued_utc)
);

-- Alerts WE raised. Used to dedupe notifications (notify once per issuance, not per tick).
CREATE TABLE IF NOT EXISTS alert_event (
    ts_utc    TIMESTAMP NOT NULL,   -- when we raised it, UTC
    rule      VARCHAR   NOT NULL,   -- 'shn_official' | 'observed_threshold' | 'forecast_threshold' | 'wind_precursor'
    severity  VARCHAR   NOT NULL,   -- 'watch' | 'warning' | 'alert'
    station   VARCHAR   NOT NULL,
    dedupe_key VARCHAR  NOT NULL,   -- stable key identifying the underlying condition
    message   VARCHAR   NOT NULL,
    notified  BOOLEAN   NOT NULL DEFAULT FALSE,
    PRIMARY KEY (rule, station, dedupe_key)
);
