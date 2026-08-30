import { useMemo, useState, useEffect } from "react";
import { useSQLQuery } from "@motherduck/react-sql-query";
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea, CartesianGrid } from "recharts";

export const REQUIRED_DATABASES = [{ type: "database", path: "md:sudestada", alias: "sudestada" }];

const N = (v) => (v != null ? Number(v) : 0);
const SANS = "'Inter', system-ui, -apple-system, sans-serif";

// Thresholds mirror lib/config.py. A sudestada is a DIRECTION event first: wind from the SE
// sector piles water up the estuary, the same speed from the N pushes it out.
const WARN_M = 2.5, ALERT_M = 3.0, SE_MIN = 112.5, SE_MAX = 157.5;
const WIND_SPEED_MIN = 8.0, WIND_SE_FRAC_MIN = 0.6;

const isSE = (d) => d >= SE_MIN && d <= SE_MAX;
const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const compass = (d) => COMPASS[Math.round(N(d) / 22.5) % 16];

// One-line verdict, computed from the data so it stays true as the forecast moves.
function verdict(peak, peak95, meanSpeed, fracSE, trend) {
  if (peak >= ALERT_M) return { line: "Alert-level water forecast.", tone: "critical" };
  if (peak >= WARN_M) return { line: "Warning-level water forecast.", tone: "warning" };
  if (meanSpeed >= WIND_SPEED_MIN && fracSE >= WIND_SE_FRAC_MIN)
    return { line: "Sudestada wind precursor is present, though levels stay below threshold.", tone: "warning" };
  if (peak95 >= WARN_M)
    return { line: "No sudestada in the central forecast, but the pessimistic tail reaches the warning line.", tone: "watch" };
  const dir = trend < -0.05 ? " and the trend is away from it" : trend > 0.05 ? " though daily peaks are creeping up" : "";
  return { line: "No sudestada. Not close to one" + dir + ".", tone: "calm" };
}

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

// Wind barb: points the way the wind BLOWS TO (bearing + 180), so a SE wind visibly
// pushes up-estuary. Drawn every 3rd hour to stay legible.
function ArrowDot(props) {
  const { cx, cy, payload, index, stroke, every } = props;
  if (cx == null || cy == null || index % every !== 0) return null;
  const rot = N(payload.dir) + 180;
  const se = isSE(N(payload.dir));
  return (
    <g transform={"rotate(" + rot + " " + cx + " " + cy + ")"} opacity={se ? 1 : 0.45}>
      <line x1={cx} y1={cy - 6} x2={cx} y2={cy + 6} stroke={stroke} strokeWidth={se ? 2 : 1.5} />
      <path d={"M " + (cx - 3.5) + " " + (cy + 2.5) + " L " + cx + " " + (cy + 7) + " L " + (cx + 3.5) + " " + (cy + 2.5)}
            fill="none" stroke={stroke} strokeWidth={se ? 2 : 1.5} strokeLinecap="round" strokeLinejoin="round" />
    </g>
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
  const dark = useDark();
  const c = dark ? DARK : LIGHT;

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
    wd AS (
      SELECT valid_utc,
             max(value) FILTER (variable = 'wind_speed') AS spd,
             max(value) FILTER (variable = 'wind_gust')  AS gst,
             max(value) FILTER (variable = 'wind_dir')   AS dir
      FROM "sudestada"."main"."forecast"
      WHERE source = 'open-meteo'
        AND run_utc = (SELECT max(run_utc) FROM "sudestada"."main"."forecast" WHERE source = 'open-meteo')
        AND valid_utc >= now() AT TIME ZONE 'UTC'
      GROUP BY valid_utc
    ),
    w AS (
      SELECT round(max(gst), 1) AS max_gust, round(avg(spd), 1) AS mean_speed,
             round(sum(CASE WHEN dir BETWEEN 112.5 AND 157.5 THEN 1 ELSE 0 END) * 1.0 / count(*), 2) AS frac_se
      FROM wd
    ),
    t AS (  -- are daily peaks rising or falling across the horizon?
      -- Only whole days: a partial first/last day misses part of the tidal cycle, so its peak
      -- is spuriously low and flattens the slope (-0.02 vs -0.08 on real data).
      SELECT round(regr_slope(pk, d), 4) AS trend FROM (
        SELECT epoch(date_trunc('day', valid_utc)) / 86400 AS d, max(value) AS pk
        FROM "sudestada"."main"."forecast"
        WHERE source = 'ina' AND variable = 'level_forecast' AND qualifier = 'main'
          AND run_utc = (SELECT max(run_utc) FROM "sudestada"."main"."forecast" WHERE source = 'ina')
          AND valid_utc >= now() AT TIME ZONE 'UTC'
        GROUP BY 1 HAVING count(*) >= 20
      )
    )
    SELECT obs.sf, obs.at_utc, f.peak, f.peak95, w.max_gust, w.mean_speed, w.frac_se, t.trend
    FROM obs, f, w, t
  `);

  const fc = useMemo(() => (fcQ.data ?? []).map((r) => ({
    label: String(r.label), p05: N(r.p05), p25: N(r.p25), main: N(r.main), p75: N(r.p75), p95: N(r.p95),
  })), [fcQ.data]);

  const wind = useMemo(() => (windQ.data ?? []).map((r) => ({
    label: String(r.label), speed: N(r.speed), gust: N(r.gust), dir: N(r.dir),
  })), [windQ.data]);

  const k = kpiQ.data?.[0];
  const WARN = WARN_M;
  const peak = k ? N(k.peak) : 0;
  const headroom = k ? (WARN - peak) : 0;
  const v = verdict(peak, k ? N(k.peak95) : 0, k ? N(k.mean_speed) : 0, k ? N(k.frac_se) : 0, k ? N(k.trend) : 0);

  // Contiguous stretches of SE-sector wind, shaded behind the wind chart.
  const seSpans = useMemo(() => {
    const out = []; let start = null;
    wind.forEach((d, i) => {
      if (isSE(d.dir) && start === null) start = d.label;
      const ends = !isSE(d.dir) || i === wind.length - 1;
      if (start !== null && ends) { out.push({ x1: start, x2: d.label }); start = null; }
    });
    return out;
  }, [wind]);

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
        {payload[0] && payload[0].payload && payload[0].payload.dir != null ? (
          <div style={{ display: "flex", gap: 10, justifyContent: "space-between", marginTop: 3, paddingTop: 3, borderTop: "1px solid " + c.grid }}>
            <span style={{ color: c.ink2 }}>Direction</span>
            <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: isSE(N(payload[0].payload.dir)) ? 600 : 400 }}>
              {compass(payload[0].payload.dir)} {Math.round(N(payload[0].payload.dir))}{"\u00B0"}{isSE(N(payload[0].payload.dir)) ? " \u2022 SE sector" : ""}
            </span>
          </div>
        ) : null}
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

      {kpiQ.isLoading ? <Skeleton h={54} /> : (
        <div style={{ display: "flex", gap: 12, alignItems: "flex-start", padding: "14px 16px", marginBottom: 22,
                      background: v.tone === "calm" ? (dark ? "#14261a" : "#eef7ee") : (dark ? "#2a2412" : "#fdf6e3"),
                      borderLeft: "3px solid " + (v.tone === "calm" ? "#0ca30c" : c.warn), borderRadius: 4 }}>
          <span style={{ fontSize: 18, lineHeight: 1.2 }} aria-hidden="true">{v.tone === "calm" ? "\u2713" : "\u26A0"}</span>
          <div>
            <div style={{ fontFamily: SANS, fontSize: 15, fontWeight: 600, color: c.ink }}>{v.line}</div>
            <div style={{ fontFamily: SANS, fontSize: 12.5, color: c.ink2, marginTop: 3 }}>
              {k ? "Peak " + peak.toFixed(2) + " m vs " + WARN_M.toFixed(1) + " m warning. Wind averages "
                   + N(k.mean_speed).toFixed(1) + " m/s with " + Math.round(N(k.frac_se) * 100)
                   + "% from the SE sector \u2014 the precursor needs " + WIND_SPEED_MIN.toFixed(0) + " m/s and "
                   + Math.round(WIND_SE_FRAC_MIN * 100) + "%." : ""}
            </div>
          </div>
        </div>
      )}

      {kpiQ.isLoading ? <Skeleton h={70} /> : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24, marginBottom: 28 }}>
          <Tile c={c} label="Observed now (SHN)" value={k ? N(k.sf).toFixed(2) + " m" : "—"} sub={k ? String(k.at_utc).slice(0, 16) + " UTC" : ""} />
          <Tile c={c} label="Forecast peak (central)" value={peak.toFixed(2) + " m"} sub={k ? "p95 " + N(k.peak95).toFixed(2) + " m" : ""} />
          <Tile c={c} label="Headroom to warning" value={headroom.toFixed(2) + " m"} sub={"warning at " + WARN.toFixed(1) + " m"} accent={c.line} />
          <Tile c={c} label="Mean wind, next 48 h" value={k ? N(k.mean_speed).toFixed(1) + " m/s" : "—"} sub={k ? "max gust " + N(k.max_gust).toFixed(1) + " m/s" : ""} />
          <Tile c={c} label="Wind from the SE sector" value={k ? Math.round(N(k.frac_se) * 100) + "%" : "—"}
                sub={"precursor needs " + Math.round(WIND_SE_FRAC_MIN * 100) + "%"}
                accent={k && N(k.frac_se) >= WIND_SE_FRAC_MIN ? c.warn : undefined} />
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
        <Swatch c={c} color={c.band50} label="Wind from SE sector" />
        <span style={{ fontFamily: SANS, fontSize: 12, color: c.ink2 }}>arrows show where the wind blows to</span>
      </div>
      {windQ.isLoading ? <Skeleton h={200} /> : (
        <ResponsiveContainer width="100%" height={200}>
          <ComposedChart data={wind} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis dataKey="label" {...axis} minTickGap={48} tickLine={false} />
            <YAxis {...axis} tickLine={false} width={48}
                   label={{ value: "m/s", angle: 0, position: "top", offset: 12, fill: c.ink2, fontSize: 11 }} />
            <Tooltip content={tip("m/s")} cursor={{ stroke: c.ink2, strokeWidth: 1 }} />
            {seSpans.map((sp, i) => (
              <ReferenceArea key={i} x1={sp.x1} x2={sp.x2} fill={c.band50} fillOpacity={dark ? 0.35 : 0.45} stroke="none" />
            ))}
            <Line dataKey="speed" name="Sustained" stroke={c.line} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="gust" name="Gust" stroke={c.gust} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey={() => 0.6} stroke="none" isAnimationActive={false} legendType="none"
                  dot={<ArrowDot stroke={c.ink2} every={3} />} activeDot={false} />
            <ReferenceLine y={8} stroke={c.warn} strokeWidth={2} strokeDasharray="5 4"
                           label={{ value: "precursor 8 m/s", position: "insideTopLeft", fill: c.ink2, fontSize: 11 }} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
