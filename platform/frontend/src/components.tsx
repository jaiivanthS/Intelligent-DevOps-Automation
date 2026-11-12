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

export function Card(props: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${props.className ?? ""}`}>
      {(props.title || props.actions) && (
        <header className="card-head">
          <h2>{props.title}</h2>
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
  const color = props.color ?? "var(--accent)";
  const gradientId = `g${Math.abs(hash(color + (props.points?.length ?? 0)))}`;
  return (
    <ResponsiveContainer width="100%" height={props.height ?? 160}>
      <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis
          dataKey="t"
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(t: number) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          stroke="var(--muted)"
          fontSize={11}
          minTickGap={40}
        />
        <YAxis tickFormatter={f} stroke="var(--muted)" fontSize={11} width={64} />
        <Tooltip
          labelFormatter={(t) => new Date(Number(t)).toLocaleTimeString()}
          formatter={(v) => [f(Number(v)), "value"]}
          contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }}
        />
        <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2} fill={`url(#${gradientId})`} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}
