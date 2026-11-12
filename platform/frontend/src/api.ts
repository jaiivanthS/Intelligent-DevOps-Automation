import { useCallback, useEffect, useState } from "react";

/** Upstream call result as returned by the platform API (never throws server-side). */
export interface Result<T> {
  ok: boolean;
  data?: T;
  error?: string;
}

export type Point = [number, number];

export interface PlatformEvent {
  id: number;
  ts: string;
  source: string;
  event: string;
  status: string;
  build: string | null;
  image_tag: string | null;
  environment: string | null;
  payload: Record<string, unknown>;
}

export interface Build {
  number: number;
  display_name: string;
  result: string;
  started_at_ms: number | null;
  duration_ms: number | null;
  description: string | null;
  url: string;
  parameters: Record<string, unknown>;
}

export interface ReleaseState {
  current_image: string | null;
  last_good_image: string | null;
  app_env: string | null;
  available: boolean;
}

export interface ReleaseRecord {
  ts: string;
  action: string;
  result: string;
  image: string;
  from?: string;
  detail?: string;
  actor?: string;
}

export interface IncidentSummary {
  id: number;
  service: string;
  title: string;
  severity: string;
  category: string;
  status: string;
  opened_at: string;
  updated_at: string;
  resolved_at: string | null;
  has_rca: number;
  alert_count: number;
}

export interface MetricEvidence {
  now?: number | null;
  baseline?: number | null;
  max?: number | null;
  points?: Point[];
  error?: string;
}

export interface Incident extends IncidentSummary {
  evidence: {
    collected_at: string;
    window_minutes: number;
    metrics: Record<string, MetricEvidence>;
    logs: {
      error?: string;
      error_lines?: number;
      top_messages?: { msg: string; level: string; count: number }[];
      events?: Record<string, number>;
      samples?: Record<string, unknown>[];
    };
    deployments: Partial<PlatformEvent>[];
    release: ReleaseState;
    release_history: ReleaseRecord[];
  } | null;
  rca: {
    top_cause: string;
    top_cause_title: string;
    description: string;
    confidence: number;
    ranking: { cause: string; title: string; score: number }[];
    evidence: string[];
    suggested_checks: string[];
    suggested_action: "rollback" | "restart" | "none";
    model: string;
    analyzed_at: string;
    rule_based: { top_cause: string; ranking: { cause: string; score: number }[] };
    anomaly: {
      score: number;
      is_anomalous: boolean;
      top_deviations: { feature: string; z: number; value: number }[];
    } | null;
  } | null;
  ground_truth: { mode: string; summary: string; starts_at: string }[] | null;
  notes: { ts: string; status: string; note: string }[] | null;
  alerts: {
    id: number;
    alertname: string;
    severity: string;
    category: string;
    status: string;
    starts_at: string;
    ends_at: string | null;
    labels: Record<string, string>;
    annotations: Record<string, string>;
  }[];
}

export interface LogLine {
  ts_ns: number;
  labels: Record<string, string>;
  line: string;
  json: Record<string, unknown> | null;
}

export async function getJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url, { headers: { Accept: "application/json" } });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

export async function postJSON<T>(url: string, body?: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<T>;
}

/** Fetch `url` now and every `intervalMs` (0 = once). Keeps showing the last good data on error. */
export function usePoll<T>(url: string | null, intervalMs = 10_000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    const load = async () => {
      try {
        const json = await getJSON<T>(url);
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    setLoading(true);
    load();
    const id = intervalMs > 0 ? window.setInterval(load, intervalMs) : undefined;
    return () => {
      cancelled = true;
      if (id) window.clearInterval(id);
    };
  }, [url, intervalMs, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
