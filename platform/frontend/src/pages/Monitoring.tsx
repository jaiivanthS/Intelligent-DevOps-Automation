import { useState } from "react";
import type { Point, Result } from "../api";
import { usePoll } from "../api";
import { Badge, Card, Empty, ErrorBanner, FromResult, TimeChart, Unavailable } from "../components";
import { PageHeader } from "../effects";
import { fmt } from "../format";

interface MonitoringData {
  minutes: number;
  series: Record<string, { ok: boolean; points?: Point[]; error?: string }>;
  targets: Result<{ job: string; instance: string; health: string; last_error: string | null }[]>;
  alerts: Result<{ alertname: string; labels: Record<string, string>; annotations: Record<string, string>; starts_at: string }[]>;
}

const RANGES = [15, 60, 360, 1440];
const CHARTS: { key: string; title: string; format: (v: number) => string; color: string }[] = [
  { key: "request_rate", title: "Request rate (req/s)", format: (v) => v.toFixed(2), color: "#c8ff1e" },
  { key: "error_ratio", title: "Error ratio (5xx)", format: (v) => fmt.pct(v), color: "#ff3d57" },
  { key: "latency_p95", title: "p95 latency", format: (v) => fmt.ms(v), color: "#ffb21e" },
  { key: "memory_rss_bytes", title: "Memory (RSS)", format: (v) => fmt.bytes(v), color: "#4de8ff" },
  { key: "cpu_cores", title: "CPU (cores)", format: (v) => v.toFixed(2), color: "#c8ff1e" },
  { key: "dependency_up", title: "inventory-db reachable", format: (v) => v.toFixed(0), color: "#a6e000" },
];

export default function Monitoring() {
  const [minutes, setMinutes] = useState(60);
  const { data, error } = usePoll<MonitoringData>(`/api/monitoring?minutes=${minutes}`, 15_000);

  return (
    <>
      <PageHeader index={4} kicker="Telemetry" title="Monitoring" sub="Golden signals from Prometheus, live alerts and scrape-target health.">
        <div className="segmented">
          {RANGES.map((m) => (
            <button key={m} className={m === minutes ? "active" : ""} onClick={() => setMinutes(m)}>
              {m < 60 ? `${m}m` : `${m / 60}h`}
            </button>
          ))}
        </div>
      </PageHeader>
      <ErrorBanner error={error} />
      <div className="grid-3">
        {CHARTS.map((c) => {
          const s = data?.series[c.key];
          return (
            <Card key={c.key} title={c.title}>
              {!s ? <p className="muted">Loading…</p> : s.ok ? <TimeChart points={s.points} format={c.format} color={c.color} /> : <Unavailable what="Prometheus" error={s.error} />}
            </Card>
          );
        })}
      </div>
      <div className="grid-2">
        <Card title="Firing alerts">
          <FromResult result={data?.alerts} what="Alertmanager">
            {(alerts) =>
              alerts.length ? (
                <ul className="list">
                  {alerts.map((a, i) => (
                    <li key={`${a.alertname}-${i}`}>
                      <Badge value={a.labels.severity} />
                      <strong>{a.alertname}</strong>
                      <span className="muted small">{a.annotations.summary}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>No alerts firing.</Empty>
              )
            }
          </FromResult>
        </Card>
        <Card title="Scrape targets">
          <FromResult result={data?.targets} what="Prometheus">
            {(targets) => (
              <table>
                <tbody>
                  {targets.map((t) => (
                    <tr key={`${t.job}-${t.instance}`}>
                      <td>{t.job}</td>
                      <td className="mono small">{t.instance}</td>
                      <td>
                        <Badge value={t.health} />
                      </td>
                      <td className="muted small">{t.last_error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </FromResult>
        </Card>
      </div>
    </>
  );
}
