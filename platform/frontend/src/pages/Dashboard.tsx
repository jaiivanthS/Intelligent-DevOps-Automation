import { Link } from "react-router-dom";
import type { Build, IncidentSummary, PlatformEvent, ReleaseState, Result } from "../api";
import { usePoll } from "../api";
import { Badge, Card, Empty, ErrorBanner, FromResult, Stat } from "../components";
import { fmt } from "../format";

interface DashboardData {
  service: {
    name: string;
    info: Result<{ version: string; env: string; ready: boolean }>;
    request_rate: Result<number | null>;
    error_ratio: Result<number | null>;
    latency_p95: Result<number | null>;
  };
  pipeline: { builds: Result<Build[]>; last_event: PlatformEvent | null };
  release: ReleaseState;
  incidents: { open: IncidentSummary[]; open_count: number };
  alerts: Result<{ alertname: string; labels: Record<string, string> }[]>;
  events: PlatformEvent[];
}

const val = <T,>(r: Result<T> | undefined) => (r?.ok ? r.data : undefined);

export default function Dashboard() {
  const { data, error } = usePoll<DashboardData>("/api/dashboard", 10_000);
  const info = val(data?.service.info);
  const err = val(data?.service.error_ratio) ?? null;
  const p95 = val(data?.service.latency_p95) ?? null;
  const firing = val(data?.alerts)?.length;

  return (
    <>
      <h1>Dashboard</h1>
      <ErrorBanner error={error} />
      <div className="stats">
        <Stat
          label="Service"
          state={info ? (info.ready ? "up" : "warning") : "down"}
          value={info ? (info.ready ? "Healthy" : "Degraded") : "Unreachable"}
          sub={info ? `${info.version} · ${info.env}` : data?.service.info.error}
        />
        <Stat
          label="Request rate"
          value={`${fmt.num(val(data?.service.request_rate) ?? null)} /s`}
          sub={data?.service.request_rate.ok === false ? "Prometheus unavailable" : "API, 2m avg"}
        />
        <Stat
          label="Error ratio"
          value={fmt.pct(err)}
          state={err === null ? undefined : err > 0.05 ? "critical" : err > 0.01 ? "warning" : "ok"}
          sub="5xx, 2m"
        />
        <Stat
          label="p95 latency"
          value={fmt.ms(p95)}
          state={p95 === null ? undefined : p95 > 0.5 ? "critical" : p95 > 0.25 ? "warning" : "ok"}
        />
        <Stat
          label="Open incidents"
          value={data?.incidents.open_count ?? "–"}
          state={data && data.incidents.open_count > 0 ? "critical" : "ok"}
        />
        <Stat
          label="Firing alerts"
          value={firing ?? "–"}
          state={firing === undefined ? undefined : firing > 0 ? "warning" : "ok"}
          sub={data?.alerts.ok === false ? "Alertmanager unavailable" : undefined}
        />
      </div>

      <div className="grid-2">
        <Card title="Latest builds" actions={<Link to="/pipeline">Pipeline →</Link>}>
          <FromResult result={data?.pipeline.builds} what="Jenkins">
            {(builds) =>
              builds.length ? (
                <table>
                  <tbody>
                    {builds.map((b) => (
                      <tr key={b.number}>
                        <td className="mono">#{b.number}</td>
                        <td>{b.display_name}</td>
                        <td>
                          <Badge value={b.result} />
                        </td>
                        <td className="muted">{fmt.ago(b.started_at_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty>No builds yet.</Empty>
              )
            }
          </FromResult>
          {data?.pipeline.last_event && (
            <p className="muted small">
              Last pipeline event: build {data.pipeline.last_event.build} → <Badge value={data.pipeline.last_event.status} />{" "}
              {fmt.ago(data.pipeline.last_event.ts)}
            </p>
          )}
        </Card>

        <Card title="Current release" actions={<Link to="/deployments">Deployments →</Link>}>
          {data?.release.available ? (
            <dl className="kv">
              <dt>Running</dt>
              <dd className="mono">{fmt.tag(data.release.current_image)}</dd>
              <dt>Last good</dt>
              <dd className="mono">{fmt.tag(data.release.last_good_image)}</dd>
              <dt>Environment</dt>
              <dd>{data.release.app_env ?? "–"}</dd>
              <dt>Status</dt>
              <dd>
                {data.release.current_image === data.release.last_good_image ? (
                  <Badge value="promoted" label="promoted" />
                ) : (
                  <Badge value="waiting" label="not yet promoted" />
                )}
              </dd>
            </dl>
          ) : (
            <Empty>Release state not available (app host state directory not mounted).</Empty>
          )}
        </Card>

        <Card title="Open incidents" actions={<Link to="/incidents">Incidents →</Link>}>
          {data?.incidents.open.length ? (
            <ul className="list">
              {data.incidents.open.map((i) => (
                <li key={i.id}>
                  <Badge value={i.severity} />
                  <Link to={`/incidents/${i.id}`}>
                    #{i.id} {i.title}
                  </Link>
                  <span className="muted small">{fmt.ago(i.opened_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No open incidents. 🎉</Empty>
          )}
        </Card>

        <Card title="Recent pipeline events">
          {data?.events.length ? (
            <ul className="timeline">
              {data.events.map((e) => (
                <li key={e.id}>
                  <span className="muted small">{fmt.ago(e.ts)}</span>
                  <span>
                    <strong>{e.event}</strong> {e.build && <span className="mono">#{e.build}</span>}
                  </span>
                  <Badge value={e.status} />
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No events received from Jenkins yet.</Empty>
          )}
        </Card>
      </div>
    </>
  );
}
