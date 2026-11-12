import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Point, Result } from "./api";
import { tone } from "./format";

/** "/02 System status" -> lime "/02" + text; plain strings get a lime "//" prefix. */
function CardTitle({ title }: { title: ReactNode }) {
  if (typeof title !== "string") return <>{title}</>;
  const m = /^(\/\d+)\s+(.*)$/.exec(title);
  return m ? (
    <>
      <span className="pre">{m[1]}</span>
      {m[2]}
    </>
  ) : (
    <>
      <span className="pre">//</span>
      {title}
    </>
  );
}

export function Card(props: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${props.className ?? ""}`}>
      {(props.title || props.actions) && (
        <header className="card-head">
          <h2>
            <CardTitle title={props.title} />
          </h2>
          <div className="card-actions">{props.actions}</div>
        </header>
      )}
      <div className="card-body">{props.children}</div>
    </section>
  );
}

export function Badge({ value, label }: { value: string | null | undefined; label?: string }) {
  return <span className={`badge badge-${tone(value)}`}>{label ?? value ?? "–"}</span>;
}

export function Stat(props: { label: string; value: ReactNode; sub?: ReactNode; state?: string }) {
  return (
    <div className={`stat stat-${props.state ? tone(props.state) : "muted"}`}>
      <div className="stat-label">{props.label}</div>
      <div className="stat-value">{props.value}</div>
      {props.sub && <div className="stat-sub">{props.sub}</div>}
    </div>
  );
}

export function Unavailable({ what, error }: { what: string; error?: string | null }) {
  return (
    <div className="unavailable" title={error ?? undefined}>
      <strong>{what} unavailable.</strong> <span className="muted">{error}</span>
    </div>
  );
}

/** Render a platform `Result<T>`: data via `children`, or an "unavailable" note. */
export function FromResult<T>(props: { result: Result<T> | undefined; what: string; children: (data: T) => ReactNode }) {
  if (!props.result) return <p className="muted">Loading…</p>;
  if (!props.result.ok || props.result.data === undefined)
    return <Unavailable what={props.what} error={props.result.error} />;
  return <>{props.children(props.result.data)}</>;
}

export function ErrorBanner({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="banner banner-bad">Platform API error: {error}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function TimeChart(props: {
  points: Point[] | undefined;
  format?: (v: number) => string;
  height?: number;
  color?: string;
  threshold?: number;
}) {
  const data = (props.points ?? []).map(([t, v]) => ({ t: t * 1000, v }));
  if (!data.length) return <Empty>No data in this time range.</Empty>;
  const f = props.format ?? ((v: number) => v.toFixed(2));
  const color = props.color ?? "#c8ff1e";
  const id = Math.abs(hash(color + (props.points?.length ?? 0) + (props.height ?? 0)));
  return (
    <ResponsiveContainer width="100%" height={props.height ?? 170}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={`g${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.32} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
          <filter id={`glow${id}`} x="-10%" y="-30%" width="120%" height="160%">
            <feGaussianBlur stdDeviation="2.2" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <CartesianGrid stroke="#1a1e15" strokeDasharray="2 4" />
        <XAxis
          dataKey="t"
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(t: number) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          stroke="#4d5644"
          tick={{ fill: "#7f8a72", fontSize: 10, fontFamily: "JetBrains Mono" }}
          minTickGap={40}
        />
        <YAxis tickFormatter={f} stroke="#4d5644" tick={{ fill: "#7f8a72", fontSize: 10, fontFamily: "JetBrains Mono" }} width={64} />
        <Tooltip
          labelFormatter={(t) => new Date(Number(t)).toLocaleTimeString()}
          formatter={(v) => [f(Number(v)), "value"]}
          cursor={{ stroke: color, strokeDasharray: "3 3" }}
          contentStyle={{ background: "#060706", border: `1px solid ${color}`, borderRadius: 0, fontFamily: "JetBrains Mono", fontSize: 11 }}
          labelStyle={{ color: "#7f8a72" }}
          itemStyle={{ color }}
        />
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={2}
          fill={`url(#g${id})`}
          filter={`url(#glow${id})`}
          animationDuration={900}
          activeDot={{ r: 4, fill: color, stroke: "#000" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}
