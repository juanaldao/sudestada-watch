import { useMemo, useState, useEffect } from "react";
import { useSQLQuery } from "@motherduck/react-sql-query";
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid } from "recharts";

export const REQUIRED_DATABASES = [{ type: "database", path: "md:sudestada", alias: "sudestada" }];

const N = (v) => (v != null ? Number(v) : 0);
const SANS = "'Inter', system-ui, -apple-system, sans-serif";

// Sequential blue for the nested uncertainty bands (one entity, increasing certainty toward
// the centre); orange only where a genuinely second series appears (gust vs sustained wind).
// Both modes stepped for their own surface and validated, not flipped.
const LIGHT = {
  surface: "#fcfcfb", ink: "#0b0b0b", ink2: "#52514e", grid: "#e5e5e5",
  band90: "#cde2fb", band50: "#9ec5f4", line: "#2a78d6", gust: "#eb6834", warn: "#fab219",
};
const DARK = {
  surface: "#1a1a19", ink: "#ffffff", ink2: "#c3c2b7", grid: "#383835",
  band90: "#184f95", band50: "#256abf", line: "#3987e5", gust: "#d95926", warn: "#fab219",
};

function useDark() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setDark(mq.matches);
    on();
    mq.addEventListener ? mq.addEventListener("change", on) : mq.addListener(on);
    return () => { mq.removeEventListener ? mq.removeEventListener("change", on) : mq.removeListener(on); };
  }, []);
  return dark;
}

function Skeleton({ h }) {
  const c = useDark() ? DARK : LIGHT;
  return <div style={{ height: h, background: c.grid, borderRadius: 6, opacity: 0.5 }} />;
}

function Tile({ label, value, sub, accent, c }) {
  return (
    <div style={{ flex: "1 1 150px", minWidth: 150 }}>
      <div style={{ fontFamily: SANS, fontSize: 28, fontWeight: 600, color: accent || c.ink, lineHeight: 1.15 }}>{value}</div>
      <div style={{ fontFamily: SANS, fontSize: 12, color: c.ink2, marginTop: 4 }}>{label}</div>
      {sub ? <div style={{ fontFamily: SANS, fontSize: 11, color: c.ink2, marginTop: 2, opacity: 0.8 }}>{sub}</div> : null}
    </div>
  );
}

function Swatch({ color, label, c, line }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, marginRight: 16 }}>
      <span style={{ width: 14, height: line ? 2 : 10, background: color, borderRadius: line ? 1 : 2, display: "inline-block" }} />
      <span style={{ fontFamily: SANS, fontSize: 12, color: c.ink2 }}>{label}</span>
    </span>
  );
}

export default function SudestadaForecast() {
  const c = useDark() ? DARK : LIGHT;

  const fcQ = useSQLQuery(`
    SELECT strftime(valid_utc, '%d %b %H:%M') AS label,
           max(value) FILTER (qualifier = 'p05')  AS p05,
           max(value) FILTER (qualifier = 'p25')  AS p25,
           max(value) FILTER (qualifier = 'main') AS main,
           max(value) FILTER (qualifier = 'p75')  AS p75,
           max(value) FILTER (qualifier = 'p95')  AS p95
    FROM "sudestada"."main"."forecast"
    WHERE source = 'ina' AND variable = 'level_forecast'
      AND run_utc = (SELECT max(run_utc) FROM "sudestada"."main"."forecast" WHERE source = 'ina')
      AND valid_utc >= now() AT TIME ZONE 'UTC'
    GROUP BY valid_utc ORDER BY valid_utc
  `);

  const windQ = useSQLQuery(`
    SELECT strftime(valid_utc, '%d %b %H:%M') AS label,
           max(value) FILTER (variable = 'wind_speed') AS speed,
           max(value) FILTER (variable = 'wind_gust')  AS gust,
           max(value) FILTER (variable = 'wind_dir')   AS dir
    FROM "sudestada"."main"."forecast"
    WHERE source = 'open-meteo'
      AND run_utc = (SELECT max(run_utc) FROM "sudestada"."main"."forecast" WHERE source = 'open-meteo')
      AND valid_utc >= now() AT TIME ZONE 'UTC'
    GROUP BY valid_utc ORDER BY valid_utc
  `);

  const kpiQ = useSQLQuery(`
    WITH obs AS (
      SELECT round(max(level_m) FILTER (station = 'san_fernando'), 2) AS sf,
             max(ts_utc) AS at_utc
      FROM "sudestada"."main"."v_latest_level" WHERE source = 'shn'
    ),
    f AS (
      SELECT round(max(value) FILTER (qualifier = 'main'), 2) AS peak,
             round(max(value) FILTER (qualifier = 'p95'), 2)  AS peak95
      FROM "sudestada"."main"."forecast"
      WHERE source = 'ina' AND variable = 'level_forecast'
        AND run_utc = (SELECT max(run_utc) FROM "sudestada"."main"."forecast" WHERE source = 'ina')
        AND valid_utc >= now() AT TIME ZONE 'UTC'
    ),
    w AS (
      SELECT round(max(value) FILTER (variable = 'wind_gust'), 1) AS max_gust,
             round(avg(value) FILTER (variable = 'wind_speed'), 1) AS mean_speed
      FROM "sudestada"."main"."forecast"
      WHERE source = 'open-meteo'
        AND run_utc = (SELECT max(run_utc) FROM "sudestada"."main"."forecast" WHERE source = 'open-meteo')
        AND valid_utc >= now() AT TIME ZONE 'UTC'
    )
    SELECT obs.sf, obs.at_utc, f.peak, f.peak95, w.max_gust, w.mean_speed FROM obs, f, w
  `);

  const fc = useMemo(() => (fcQ.data ?? []).map((r) => ({
    label: String(r.label), p05: N(r.p05), p25: N(r.p25), main: N(r.main), p75: N(r.p75), p95: N(r.p95),
  })), [fcQ.data]);

  const wind = useMemo(() => (windQ.data ?? []).map((r) => ({
    label: String(r.label), speed: N(r.speed), gust: N(r.gust), dir: N(r.dir),
  })), [windQ.data]);

  const k = kpiQ.data?.[0];
  const WARN = 2.5;
  const peak = k ? N(k.peak) : 0;
  const headroom = k ? (WARN - peak) : 0;

  const tip = (unit) => ({ active, payload, label }) => {
    if (!active || !payload || !payload.length) return null;
    return (
      <div style={{ background: c.surface, border: "1px solid " + c.grid, borderRadius: 6, padding: "8px 10px", fontFamily: SANS, fontSize: 12, color: c.ink }}>
        <div style={{ color: c.ink2, marginBottom: 4 }}>{label} UTC</div>
        {payload.filter((p) => p.name).map((p) => (
          <div key={p.name} style={{ display: "flex", gap: 10, justifyContent: "space-between" }}>
            <span style={{ color: c.ink2 }}>{p.name}</span>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>{Array.isArray(p.value) ? N(p.value[0]).toFixed(2) + "–" + N(p.value[1]).toFixed(2) : N(p.value).toFixed(2)} {unit}</span>
          </div>
        ))}
      </div>
    );
  };

  const axis = { stroke: c.grid, tick: { fill: c.ink2, fontSize: 11, fontFamily: SANS } };

  return (
    <div style={{ background: c.surface, padding: 24, fontFamily: SANS, minHeight: "100%" }}>
      <h1 style={{ fontSize: 22, fontWeight: 600, color: c.ink, margin: "0 0 2px" }}>Sudestada watch — forecast</h1>
      <div style={{ fontSize: 13, color: c.ink2, marginBottom: 20 }}>
        San Fernando water level, INA forecast with uncertainty bands. All times UTC.
      </div>

      {kpiQ.isLoading ? <Skeleton h={70} /> : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24, marginBottom: 28 }}>
          <Tile c={c} label="Observed now (SHN)" value={k ? N(k.sf).toFixed(2) + " m" : "—"} sub={k ? String(k.at_utc).slice(0, 16) + " UTC" : ""} />
          <Tile c={c} label="Forecast peak (central)" value={peak.toFixed(2) + " m"} sub={k ? "p95 " + N(k.peak95).toFixed(2) + " m" : ""} />
          <Tile c={c} label="Below warning threshold" value={headroom.toFixed(2) + " m"} sub={"warning at " + WARN.toFixed(1) + " m"} accent={c.line} />
          <Tile c={c} label="Mean wind, next 48 h" value={k ? N(k.mean_speed).toFixed(1) + " m/s" : "—"} sub={k ? "max gust " + N(k.max_gust).toFixed(1) + " m/s" : ""} />
        </div>
      )}

      <div style={{ fontSize: 13, fontWeight: 600, color: c.ink, marginBottom: 2 }}>Predicted level</div>
      <div style={{ marginBottom: 8 }}>
        <Swatch c={c} color={c.line} label="Central forecast" line />
        <Swatch c={c} color={c.band50} label="50% range (p25–p75)" />
        <Swatch c={c} color={c.band90} label="90% range (p05–p95)" />
        <Swatch c={c} color={c.warn} label="Warning threshold" line />
      </div>
      {fcQ.isLoading ? <Skeleton h={300} /> : (
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={fc} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis dataKey="label" {...axis} minTickGap={48} tickLine={false} />
            <YAxis {...axis} tickLine={false} width={48} domain={[0, 2.7]}
                   label={{ value: "m", angle: 0, position: "top", offset: 12, fill: c.ink2, fontSize: 11 }} />
            <Tooltip content={tip("m")} cursor={{ stroke: c.ink2, strokeWidth: 1 }} />
            <Area dataKey={(d) => [d.p05, d.p95]} name="90% range" fill={c.band90} stroke="none" isAnimationActive={false} />
            <Area dataKey={(d) => [d.p25, d.p75]} name="50% range" fill={c.band50} stroke="none" isAnimationActive={false} />
            <Line dataKey="main" name="Central" stroke={c.line} strokeWidth={2} dot={false} isAnimationActive={false} />
            <ReferenceLine y={WARN} stroke={c.warn} strokeWidth={2} strokeDasharray="5 4"
                           label={{ value: "warning 2.5 m", position: "insideTopLeft", fill: c.ink2, fontSize: 11 }} />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      <div style={{ fontSize: 13, fontWeight: 600, color: c.ink, margin: "28px 0 2px" }}>Wind at Tigre — the driver</div>
      <div style={{ marginBottom: 8 }}>
        <Swatch c={c} color={c.line} label="Sustained speed" line />
        <Swatch c={c} color={c.gust} label="Gust" line />
      </div>
      {windQ.isLoading ? <Skeleton h={200} /> : (
        <ResponsiveContainer width="100%" height={200}>
          <ComposedChart data={wind} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis dataKey="label" {...axis} minTickGap={48} tickLine={false} />
            <YAxis {...axis} tickLine={false} width={48}
                   label={{ value: "m/s", angle: 0, position: "top", offset: 12, fill: c.ink2, fontSize: 11 }} />
            <Tooltip content={tip("m/s")} cursor={{ stroke: c.ink2, strokeWidth: 1 }} />
            <Line dataKey="speed" name="Sustained" stroke={c.line} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="gust" name="Gust" stroke={c.gust} strokeWidth={2} dot={false} isAnimationActive={false} />
            <ReferenceLine y={8} stroke={c.warn} strokeWidth={2} strokeDasharray="5 4"
                           label={{ value: "precursor 8 m/s", position: "insideTopLeft", fill: c.ink2, fontSize: 11 }} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
