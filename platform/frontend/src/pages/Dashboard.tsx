import { Link } from "react-router-dom";
import type { Build, IncidentSummary, PlatformEvent, ReleaseState, Result } from "../api";
import { usePoll } from "../api";
import type { Config } from "../App";
import { Badge, Card, Empty, ErrorBanner, FromResult, Stat } from "../components";
import { CountUp, Meter, Ticker, Typed } from "../effects";
import { fmt } from "../format";
import Radar from "../Radar";

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
const NODES: [string, string][] = [
  ["jenkins", "JENKINS"],
  ["prometheus", "PROMETHEUS"],
  ["loki", "LOKI"],
  ["alertmanager", "ALERTMGR"],
  ["app", "DEMO-APP"],
  ["release_state", "RELEASES"],
  ["rca", "RCA"],
];

export default function Dashboard({ config }: { config: Config | null }) {
  const { data, error } = usePoll<DashboardData>("/api/dashboard", 10_000);
  const info = val(data?.service.info);
  const rps = val(data?.service.request_rate) ?? null;
  const err = val(data?.service.error_ratio) ?? null;
  const p95 = val(data?.service.latency_p95) ?? null;
  const alerts = val(data?.alerts);
  const firing = alerts?.length;
  const openCount = data?.incidents.open_count ?? 0;
  const online = NODES.filter(([k]) => config?.[k]).length;

  const state: "bad" | "warn" | "good" = !info || openCount > 0 ? "bad" : (err ?? 0) > 0.01 || (p95 ?? 0) > 0.25 || firing ? "warn" : "good";
  const stateLabel = { good: "ALL SYSTEMS OPERATIONAL", warn: "DEGRADED PERFORMANCE", bad: info ? "INCIDENT ACTIVE" : "SERVICE UNREACHABLE" }[state];

  const tickerItems = [
    ...(alerts ?? []).map((a) => (
      <>
        <Badge value="firing" label="ALERT" /> <b>{a.alertname}</b>
      </>
    )),
    ...(data?.events ?? []).map((e) => (
      <>
        <span className="lime">{fmt.ago(e.ts)}</span> <b>{e.event}</b> {e.build && `#${e.build}`} <Badge value={e.status} />
      </>
    )),
  ];

  return (
    <>
      <ErrorBanner error={error} />

      <section className="hero">
        <div className="hero-left">
          <div className="side-index" aria-hidden>
            <i className="on" />
            <i />
            <i />
          </div>
          <div className="section-label">
            <span className="num">/01</span> Mission control
          </div>
          <h1 className="hero-title" aria-label="Ship. Sense. Heal.">
            <span className="line">
              <span className="glitch" data-text="SHIP.">
                SHIP.
              </span>
            </span>
            <span className="line">
              <span>SENSE.</span>
            </span>
            <span className="line">
              <span className="outline" style={{ animationDelay: "0.24s" }}>
                HEAL.
              </span>
            </span>
          </h1>
          <div className="hero-tag">
            <Typed text="THE PIPELINE ISN'T MANUAL." delay={0.9} />
            <Typed text="IT'S SYSTEMATIC." delay={1.9} last />
          </div>
          <p className="hero-copy">
            Build, test, deploy, observe and recover <span className="lime">{data?.service.name ?? "demo-app"}</span>:
            CI/CD on Jenkins, telemetry from Prometheus &amp; Loki, explainable AI root-cause analysis and human-approved
            recovery.
          </p>
          <div className="hero-actions">
            <Link to="/pipeline" className="btn primary">
              View pipeline <span className="arrow">↗</span>
            </Link>
            <Link to="/incidents" className="btn ghost">
              {openCount ? `${openCount} open incident${openCount > 1 ? "s" : ""}` : "Incidents"} <span className="arrow">⌗</span>
            </Link>
          </div>
        </div>

        <div className="hero-right">
          <div className="hero-readout tl">
            &gt;SCANNING TELEMETRY...
            <br />
            <span className="lime">
              {online}/{NODES.length} LINKS
            </span>
          </div>
          <div className="hero-readout tr lime">{info ? `v${info.version}` : "OFFLINE"}</div>
          <span className="crosshair" style={{ left: "12%", top: "22%" }}>
            +
          </span>
          <span className="crosshair" style={{ right: "30%", top: "14%", animationDelay: "1s" }}>
            +
          </span>
          <span className="crosshair" style={{ left: "24%", bottom: "18%", animationDelay: "2s" }}>
            ✕
          </span>
          <Radar nodes={NODES.map(([k, label]) => ({ key: k, label, up: !!config?.[k] }))} />
          <div className="coord-box">
            <div>
              <span>RPS</span> <CountUp value={rps} format={(v) => v.toFixed(2)} />
            </div>
            <div>
              <span>ERR</span> <CountUp value={err} format={(v) => fmt.pct(v)} />
            </div>
            <div>
              <span>P95</span> <CountUp value={p95} format={(v) => fmt.ms(v)} />
            </div>
          </div>
          <div className="hero-meter" aria-hidden>
            {Array.from({ length: 14 }, (_, i) => (
              <i key={i} style={{ animationDelay: `${(i * 0.13) % 1.4}s` }} />
            ))}
          </div>
          <div className="hero-readout br">//NODE_01 · AP-SOUTH-1</div>
        </div>
      </section>

      <Ticker label="LIVE FEED" items={tickerItems} />

      <div className="stats">
        <Stat
          label="Service"
          state={info ? (info.ready ? "up" : "warning") : "down"}
          value={info ? (info.ready ? "ONLINE" : "DEGRADED") : "OFFLINE"}
          sub={info ? `${info.version} · ${info.env}` : data?.service.info.error}
        />
        <Stat
          label="Request rate"
          value={<CountUp value={rps} format={(v) => `${v.toFixed(2)}/s`} />}
          sub={data?.service.request_rate.ok === false ? "Prometheus unavailable" : "API · 2m avg"}
          state={rps === null ? undefined : "ok"}
        />
        <Stat
          label="Error ratio"
          value={<CountUp value={err} format={(v) => fmt.pct(v)} />}
          state={err === null ? undefined : err > 0.05 ? "critical" : err > 0.01 ? "warning" : "ok"}
          sub="5xx · 2m"
        />
        <Stat
          label="p95 latency"
          value={<CountUp value={p95} format={(v) => fmt.ms(v)} />}
          state={p95 === null ? undefined : p95 > 0.5 ? "critical" : p95 > 0.25 ? "warning" : "ok"}
          sub="API routes"
        />
        <Stat label="Open incidents" value={<CountUp value={openCount} format={(v) => String(Math.round(v))} />} state={openCount > 0 ? "critical" : "ok"} sub="auto-correlated" />
        <Stat
          label="Firing alerts"
          value={<CountUp value={firing} format={(v) => String(Math.round(v))} />}
          state={firing === undefined ? undefined : firing > 0 ? "warning" : "ok"}
          sub={data?.alerts.ok === false ? "Alertmanager unavailable" : "Alertmanager"}
        />
      </div>

      <div className="grid-3">
        <Card title="/02 System status">
          <div className="meters">
            <Meter label="Error budget" ratio={err === null ? null : err / 0.05} value={fmt.pct(err)} tone={err !== null && err > 0.05 ? "bad" : err !== null && err > 0.01 ? "warn" : "good"} />
            <Meter label="p95 / 500ms" ratio={p95 === null ? null : p95 / 0.5} value={fmt.ms(p95)} tone={p95 !== null && p95 > 0.5 ? "bad" : p95 !== null && p95 > 0.25 ? "warn" : "good"} />
            <Meter label="Throughput" ratio={rps === null ? null : rps / 10} value={rps === null ? "–" : `${rps.toFixed(1)}/s`} />
            <Meter label="Integrations" ratio={online / NODES.length} value={`${online}/${NODES.length}`} tone={online < NODES.length ? "warn" : "good"} />
            <Meter label="Incidents" ratio={Math.min(1, openCount / 3)} value={String(openCount)} tone={openCount ? "bad" : "good"} />
          </div>
          <div className={`sys-pill ${state === "good" ? "" : state}`}>
            <i /> {stateLabel}
          </div>
        </Card>

        <Card title="/03 Latest builds" actions={<Link to="/pipeline">Pipeline ↗</Link>}>
          <FromResult result={data?.pipeline.builds} what="Jenkins">
            {(builds) =>
              builds.length ? (
                <table>
                  <tbody>
                    {builds.map((b) => (
                      <tr key={b.number}>
                        <td className="mono lime">#{b.number}</td>
                        <td className="small">{b.display_name}</td>
                        <td>
                          <Badge value={b.result} />
                        </td>
                        <td className="muted small">{fmt.ago(b.started_at_ms)}</td>
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
              Last pipeline event: build #{data.pipeline.last_event.build} → <Badge value={data.pipeline.last_event.status} />{" "}
              {fmt.ago(data.pipeline.last_event.ts)}
            </p>
          )}
        </Card>

        <Card title="/04 Current release" actions={<Link to="/deployments">Deploys ↗</Link>}>
          {data?.release.available ? (
            <>
              <div className="stat-value lime" style={{ margin: "2px 0 14px" }}>
                {fmt.tag(data.release.current_image)}
              </div>
              <dl className="kv">
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
            </>
          ) : (
            <Empty>Release state not available (app host state directory not mounted).</Empty>
          )}
        </Card>
      </div>

      <div className="grid-2">
        <Card title="/05 Open incidents" actions={<Link to="/incidents">Incidents ↗</Link>}>
          {data?.incidents.open.length ? (
            <ul className="list">
              {data.incidents.open.map((i) => (
                <li key={i.id}>
                  <Badge value={i.severity} />
                  <Link to={`/incidents/${i.id}`}>
                    #{i.id} {i.title}
                  </Link>
                  <span className="muted small" style={{ marginLeft: "auto" }}>
                    {fmt.ago(i.opened_at)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No open incidents. All quiet on the wire.</Empty>
          )}
        </Card>

        <Card title="/06 Pipeline events">
          {data?.events.length ? (
            <ul className="timeline">
              {data.events.map((e, i) => (
                <li key={e.id} style={{ animationDelay: `${i * 0.04}s` }}>
                  <span className="muted small">{fmt.ago(e.ts)}</span>
                  <span>
                    <strong>{e.event}</strong> {e.build && <span className="mono lime">#{e.build}</span>}
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
