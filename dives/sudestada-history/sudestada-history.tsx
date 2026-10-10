import { useMemo, useState, useEffect } from "react";
import { useSQLQuery } from "@motherduck/react-sql-query";
import { ScatterChart, Scatter, BarChart, Bar, XAxis, YAxis, ZAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid } from "recharts";

// History of EXTREME water levels at San Fernando: hours at/above 2.5 m (high water) or
// at/below 0.1 m (low water), grouped into events by v_level_events (lib/sql/views.sql).
// Ordinary levels are deliberately absent. INA only, hourly since 2011
// (deploy/backfill_ina.py). Stored in UTC; shifted -3 h for display, as in the forecast Dive.
export const REQUIRED_DATABASES = [{ type: "database", path: "md:sudestada", alias: "sudestada" }];

const N = (v) => (v != null ? Number(v) : 0);
const SANS = "'Inter', system-ui, -apple-system, sans-serif";
const HIGH_M = 2.5, LOW_M = 0.1;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Same surfaces and inks as the forecast Dive. High water takes the warm hue, low water the
// cool one, so the two kinds read apart in every chart and table.
const LIGHT = {
  surface: "#fcfcfb", ink: "#0b0b0b", ink2: "#52514e", grid: "#e5e5e5",
  high: "#eb6834", low: "#2a78d6", warn: "#fab219",
};
const DARK = {
  surface: "#1a1a19", ink: "#ffffff", ink2: "#c3c2b7", grid: "#383835",
  high: "#d95926", low: "#3987e5", warn: "#fab219",
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
      <span style={{ width: line ? 14 : 10, height: line ? 2 : 10, background: color, borderRadius: line ? 1 : 5, display: "inline-block" }} />
      <span style={{ fontFamily: SANS, fontSize: 12, color: c.ink2 }}>{label}</span>
    </span>
  );
}

function SectionTitle({ c, children, sub }) {
  return (
    <div style={{ margin: "28px 0 8px" }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: c.ink }}>{children}</div>
      {sub ? <div style={{ fontSize: 12, color: c.ink2, marginTop: 2 }}>{sub}</div> : null}
    </div>
  );
}

// One small bar chart; used in pairs so highs and lows each get their own scale (their
// counts differ year to year, and a shared axis would flatten whichever kind is rarer).
function CountBars({ data, dataKey, color, title, c, height = 180 }) {
  const axis = { stroke: c.grid, tick: { fill: c.ink2, fontSize: 11, fontFamily: SANS } };
  return (
    <div style={{ flex: "1 1 320px", minWidth: 280 }}>
      <div style={{ fontSize: 12, color: c.ink2, marginBottom: 4 }}>{title}</div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={c.grid} vertical={false} />
          <XAxis dataKey="label" {...axis} tickLine={false} interval="preserveStartEnd" minTickGap={8} />
          <YAxis {...axis} tickLine={false} width={36} allowDecimals={false} />
          <Tooltip cursor={{ fill: c.grid, opacity: 0.4 }}
                   content={({ active, payload, label }) => active && payload && payload.length ? (
                     <div style={{ background: c.surface, border: "1px solid " + c.grid, borderRadius: 6, padding: "6px 10px", fontFamily: SANS, fontSize: 12, color: c.ink }}>
                       <span style={{ color: c.ink2 }}>{label}</span>{"  "}{N(payload[0].value)} events
                       {payload[0].payload && payload[0].payload.partial ? <div style={{ color: c.ink2 }}>partial year</div> : null}
                     </div>
                   ) : null} />
          <Bar dataKey={dataKey} fill={color} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function EventTable({ rows, c, color, title }) {
  const th = { textAlign: "left", fontWeight: 500, color: c.ink2, padding: "4px 8px", borderBottom: "1px solid " + c.grid };
  const td = { padding: "4px 8px", borderBottom: "1px solid " + c.grid, color: c.ink, fontVariantNumeric: "tabular-nums" };
  return (
    <div style={{ flex: "1 1 320px", minWidth: 280 }}>
      <div style={{ fontSize: 12, color: c.ink2, marginBottom: 4 }}>{title}</div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: SANS, fontSize: 12.5 }}>
        <thead><tr><th style={th}>#</th><th style={th}>When (ART)</th><th style={{ ...th, textAlign: "right" }}>Level</th><th style={{ ...th, textAlign: "right" }}>Hours past line</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ ...td, color: c.ink2 }}>{i + 1}</td>
              <td style={td}>{String(r.at_label)}</td>
              <td style={{ ...td, textAlign: "right", color, fontWeight: 600 }}>{N(r.extreme_m).toFixed(2)} m</td>
              <td style={{ ...td, textAlign: "right" }}>{N(r.hours)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SudestadaHistory() {
  const dark = useDark();
  const c = dark ? DARK : LIGHT;

  const metaQ = useSQLQuery(`
    SELECT year(min(ts_utc)) AS first_year,
           strftime(max(ingested_at) - INTERVAL 3 HOUR, '%d %b %H:%M') AS updated
    FROM "sudestada"."main"."observation"
    WHERE source = 'ina' AND station = 'san_fernando' AND variable = 'level_observed'
  `);

  const evQ = useSQLQuery(`
    SELECT kind, extreme_m, hours,
           epoch_ms(extreme_utc - INTERVAL 3 HOUR) AS x,
           strftime(extreme_utc - INTERVAL 3 HOUR, '%d %b %Y %H:%M') AS at_label
    FROM "sudestada"."main"."v_level_events"
    ORDER BY extreme_utc
  `);

  const yearQ = useSQLQuery(`
    WITH e AS (SELECT kind, year(extreme_utc - INTERVAL 3 HOUR) AS y FROM "sudestada"."main"."v_level_events")
    SELECT y, count(*) FILTER (kind = 'high') AS high, count(*) FILTER (kind = 'low') AS low
    FROM e GROUP BY y ORDER BY y
  `);

  const monthQ = useSQLQuery(`
    WITH e AS (SELECT kind, month(extreme_utc - INTERVAL 3 HOUR) AS m FROM "sudestada"."main"."v_level_events")
    SELECT m, count(*) FILTER (kind = 'high') AS high, count(*) FILTER (kind = 'low') AS low
    FROM e GROUP BY m ORDER BY m
  `);

  const kpiQ = useSQLQuery(`
    WITH e AS (SELECT * FROM "sudestada"."main"."v_level_events")
    SELECT
      (SELECT max(extreme_m) FROM e WHERE kind = 'high') AS rec_high,
      (SELECT strftime(arg_max(extreme_utc, extreme_m) - INTERVAL 3 HOUR, '%d %b %Y') FROM e WHERE kind = 'high') AS rec_high_at,
      (SELECT min(extreme_m) FROM e WHERE kind = 'low') AS rec_low,
      (SELECT strftime(arg_min(extreme_utc, extreme_m) - INTERVAL 3 HOUR, '%d %b %Y') FROM e WHERE kind = 'low') AS rec_low_at,
      (SELECT count(*) FROM e WHERE kind = 'high') AS n_high,
      (SELECT count(*) FROM e WHERE kind = 'low') AS n_low,
      (SELECT count(*) FROM e WHERE kind = 'high' AND extreme_utc >= now() AT TIME ZONE 'UTC' - INTERVAL 365 DAY) AS n_high_12m,
      (SELECT count(*) FROM e WHERE kind = 'low' AND extreme_utc >= now() AT TIME ZONE 'UTC' - INTERVAL 365 DAY) AS n_low_12m
  `);

  const topQ = useSQLQuery(`
    (SELECT 'high' AS kind, extreme_m, hours, strftime(extreme_utc - INTERVAL 3 HOUR, '%d %b %Y %H:%M') AS at_label
     FROM "sudestada"."main"."v_level_events" WHERE kind = 'high' ORDER BY extreme_m DESC, extreme_utc LIMIT 10)
    UNION ALL
    (SELECT 'low' AS kind, extreme_m, hours, strftime(extreme_utc - INTERVAL 3 HOUR, '%d %b %Y %H:%M') AS at_label
     FROM "sudestada"."main"."v_level_events" WHERE kind = 'low' ORDER BY extreme_m ASC, extreme_utc LIMIT 10)
  `);

  const meta = metaQ.data?.[0];
  const k = kpiQ.data?.[0];

  const events = useMemo(() => (evQ.data ?? []).map((r) => ({
    kind: String(r.kind), x: N(r.x), y: N(r.extreme_m), hours: N(r.hours), label: String(r.at_label),
  })), [evQ.data]);
  const highs = useMemo(() => events.filter((e) => e.kind === "high"), [events]);
  const lows = useMemo(() => events.filter((e) => e.kind === "low"), [events]);

  const thisYear = new Date().getFullYear();
  const years = useMemo(() => (yearQ.data ?? []).map((r) => ({
    label: N(r.y) === thisYear ? N(r.y) + "*" : String(N(r.y)),
    high: N(r.high), low: N(r.low), partial: N(r.y) === thisYear,
  })), [yearQ.data, thisYear]);

  const months = useMemo(() => {
    const by = new Map((monthQ.data ?? []).map((r) => [N(r.m), r]));
    return MONTHS.map((name, i) => ({ label: name, high: N(by.get(i + 1)?.high), low: N(by.get(i + 1)?.low) }));
  }, [monthQ.data]);

  const top = topQ.data ?? [];
  const topHigh = top.filter((r) => String(r.kind) === "high");
  const topLow = top.filter((r) => String(r.kind) === "low");

  const axis = { stroke: c.grid, tick: { fill: c.ink2, fontSize: 11, fontFamily: SANS } };
  const yearTick = (ms) => String(new Date(ms).getUTCFullYear());

  const eventTip = ({ active, payload }) => {
    if (!active || !payload || !payload.length) return null;
    const e = payload[0].payload;
    return (
      <div style={{ background: c.surface, border: "1px solid " + c.grid, borderRadius: 6, padding: "8px 10px", fontFamily: SANS, fontSize: 12, color: c.ink }}>
        <div style={{ color: c.ink2, marginBottom: 4 }}>{e.label} ART</div>
        <div style={{ fontWeight: 600, color: e.kind === "high" ? c.high : c.low }}>
          {e.kind === "high" ? "High water" : "Low water"} · {e.y.toFixed(2)} m
        </div>
        <div style={{ color: c.ink2, marginTop: 2 }}>{e.hours} h {e.kind === "high" ? "at/above " + HIGH_M.toFixed(1) + " m" : "at/below " + LOW_M.toFixed(1) + " m"}</div>
      </div>
    );
  };

  return (
    <div style={{ background: c.surface, padding: 24, fontFamily: SANS, minHeight: "100%" }}>
      <h1 style={{ fontSize: 22, fontWeight: 600, color: c.ink, margin: "0 0 2px" }}>Sudestada watch — history</h1>
      <div style={{ fontSize: 13, color: c.ink2, marginBottom: 20 }}>
        Extreme water levels at San Fernando: high water at or above {HIGH_M.toFixed(1)} m and low water at or below {LOW_M.toFixed(1)} m.
        Consecutive hours past a line (gaps up to 12 h) count as one event.
        INA hourly data{meta ? " since " + N(meta.first_year) : ""}. All times Argentina (ART, UTC−3).
        {meta && meta.updated ? <div style={{ marginTop: 4 }}>Last updated on {String(meta.updated)} ART</div> : null}
      </div>

      {kpiQ.isLoading ? <Skeleton h={70} /> : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24, marginBottom: 8 }}>
          <Tile c={c} label="Record high" value={k ? N(k.rec_high).toFixed(2) + " m" : "—"} sub={k ? String(k.rec_high_at) : ""} accent={c.high} />
          <Tile c={c} label="Record low" value={k ? N(k.rec_low).toFixed(2) + " m" : "—"} sub={k ? String(k.rec_low_at) : ""} accent={c.low} />
          <Tile c={c} label="High-water events" value={k ? String(N(k.n_high)) : "—"} sub={k ? N(k.n_high_12m) + " in the last 12 months" : ""} />
          <Tile c={c} label="Low-water events" value={k ? String(N(k.n_low)) : "—"} sub={k ? N(k.n_low_12m) + " in the last 12 months" : ""} />
        </div>
      )}

      <SectionTitle c={c} sub="Each dot is one event at its most extreme reading. Hover for the date and duration.">Every event</SectionTitle>
      <div style={{ marginBottom: 8 }}>
        <Swatch c={c} color={c.high} label="High water (peak)" />
        <Swatch c={c} color={c.low} label="Low water (lowest point)" />
        <Swatch c={c} color={c.warn} label={HIGH_M.toFixed(1) + " m / " + LOW_M.toFixed(1) + " m lines"} line />
      </div>
      {evQ.isLoading ? <Skeleton h={320} /> : (
        <ResponsiveContainer width="100%" height={320}>
          <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis type="number" dataKey="x" domain={["dataMin", "dataMax"]} scale="time" {...axis}
                   tickFormatter={yearTick} tickLine={false} minTickGap={32} />
            <YAxis type="number" dataKey="y" {...axis} tickLine={false} width={48}
                   label={{ value: "m", angle: 0, position: "top", offset: 12, fill: c.ink2, fontSize: 11 }} />
            <ZAxis range={[22, 22]} />
            <Tooltip content={eventTip} cursor={{ stroke: c.ink2, strokeWidth: 1 }} />
            <ReferenceLine y={HIGH_M} stroke={c.warn} strokeWidth={1.5} strokeDasharray="5 4"
                           label={{ value: HIGH_M.toFixed(1) + " m", position: "insideTopLeft", fill: c.ink2, fontSize: 11 }} />
            <ReferenceLine y={LOW_M} stroke={c.warn} strokeWidth={1.5} strokeDasharray="5 4"
                           label={{ value: LOW_M.toFixed(1) + " m", position: "insideBottomLeft", fill: c.ink2, fontSize: 11 }} />
            <Scatter data={lows} fill={c.low} fillOpacity={0.55} isAnimationActive={false} />
            <Scatter data={highs} fill={c.high} fillOpacity={0.9} isAnimationActive={false} />
          </ScatterChart>
        </ResponsiveContainer>
      )}

      <SectionTitle c={c} sub={"Each panel has its own scale. * = year in progress."}>Events per year</SectionTitle>
      {yearQ.isLoading ? <Skeleton h={180} /> : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
          <CountBars c={c} data={years} dataKey="high" color={c.high} title="High-water events" />
          <CountBars c={c} data={years} dataKey="low" color={c.low} title="Low-water events" />
        </div>
      )}

      <SectionTitle c={c} sub="All years combined, by the month of each event's extreme.">Season</SectionTitle>
      {monthQ.isLoading ? <Skeleton h={180} /> : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
          <CountBars c={c} data={months} dataKey="high" color={c.high} title="High-water events by month" />
          <CountBars c={c} data={months} dataKey="low" color={c.low} title="Low-water events by month" />
        </div>
      )}

      <SectionTitle c={c}>The ten most extreme</SectionTitle>
      {topQ.isLoading ? <Skeleton h={240} /> : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
          <EventTable c={c} rows={topHigh} color={c.high} title="Highest water" />
          <EventTable c={c} rows={topLow} color={c.low} title="Lowest water" />
        </div>
      )}
    </div>
  );
}
