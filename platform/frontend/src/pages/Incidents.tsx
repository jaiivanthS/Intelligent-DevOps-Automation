import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { Incident, IncidentSummary } from "../api";
import { postJSON, usePoll } from "../api";
import { Badge, Card, Empty, ErrorBanner, TimeChart } from "../components";
import { PageHeader } from "../effects";
import { fmt } from "../format";

const METRICS: { key: string; label: string; format: (v: number) => string }[] = [
  { key: "error_ratio", label: "Error ratio", format: (v) => fmt.pct(v) },
  { key: "latency_p95", label: "p95 latency", format: (v) => fmt.ms(v) },
  { key: "request_rate", label: "Request rate", format: (v) => `${v.toFixed(2)}/s` },
  { key: "memory_rss_bytes", label: "Memory", format: (v) => fmt.bytes(v) },
  { key: "cpu_cores", label: "CPU", format: (v) => `${v.toFixed(2)} cores` },
  { key: "dependency_up", label: "Dependency up", format: (v) => v.toFixed(0) },
];

export default function Incidents() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"active" | "all">("active");
  const { data, error, reload } = usePoll<IncidentSummary[]>(
    `/api/incidents?limit=100${filter === "active" ? "&status=active" : ""}`,
    10_000,
  );
  const selected = id ? Number(id) : data?.[0]?.id;

  return (
    <>
      <PageHeader index={6} kicker="Detect · diagnose" title="Incidents" sub="Alerts correlated into incidents, evidence captured automatically, causes ranked by explainable AI.">
        <div className="segmented">
          {(["active", "all"] as const).map((f) => (
            <button key={f} className={f === filter ? "active" : ""} onClick={() => setFilter(f)}>
              {f}
            </button>
          ))}
        </div>
      </PageHeader>
      <ErrorBanner error={error} />
      <div className="grid-sidebar">
        <Card title="Incidents">
          {data?.length ? (
            <ul className="incident-list">
              {data.map((i) => (
                <li key={i.id} className={i.id === selected ? "selected" : ""} onClick={() => navigate(`/incidents/${i.id}`)}>
                  <div className="row-between">
                    <strong>
                      #{i.id} {i.title}
                    </strong>
                    <Badge value={i.status} />
                  </div>
                  <div className="row-gap muted small">
                    <Badge value={i.severity} /> {i.category} · {i.alert_count} alert(s) · {fmt.ago(i.opened_at)}
                    {i.has_rca ? <Badge value="info" label="RCA" /> : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>{filter === "active" ? "No active incidents." : "No incidents recorded yet."}</Empty>
          )}
        </Card>
        {selected ? <IncidentDetail id={selected} onChange={reload} /> : <Card title="Details"><Empty>Select an incident.</Empty></Card>}
      </div>
    </>
  );
}

const ACTION_LABEL: Record<string, string> = {
  rollback: "Roll back to the last good release",
  restart: "Restart the service",
  none: "No automated action; investigate using the checks above",
};

function RcaPanel({ rca, incidentId }: { rca: NonNullable<Incident["rca"]>; incidentId: number }) {
  const agree = rca.rule_based.top_cause === rca.top_cause;
  return (
    <div className="rca">
      <div className="rca-top">
        <div>
          <div className="muted small">Most probable cause</div>
          <div className="rca-cause">{rca.top_cause_title}</div>
          <div className="muted small">{rca.description}</div>
        </div>
        <div className="rca-conf">{fmt.pct(rca.confidence, 0)} confidence</div>
      </div>
      <ol className="ranking">
        {rca.ranking.map((r) => (
          <li key={r.cause}>
            <span>{r.title}</span>
            <span className="bar">
              <span style={{ width: `${Math.round(r.score * 100)}%` }} />
            </span>
            <span className="mono small">{fmt.pct(r.score, 0)}</span>
          </li>
        ))}
      </ol>
      {rca.evidence.length > 0 && (
        <>
          <h3>Why</h3>
          <ul>
            {rca.evidence.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </>
      )}
      <h3>Suggested checks</h3>
      <ul>
        {rca.suggested_checks.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <p>
        Suggested recovery: <strong>{ACTION_LABEL[rca.suggested_action] ?? rca.suggested_action}</strong>
        {rca.suggested_action !== "none" && (
          <>
            {" "}
            · <Link to={`/recovery?incident=${incidentId}&action=${rca.suggested_action}`}>Request this recovery →</Link>
          </>
        )}
      </p>
      <div className="rca-meta">
        <span>
          Rule-based baseline: <strong>{rca.rule_based.top_cause.replace(/_/g, " ")}</strong>{" "}
          <Badge value={agree ? "ok" : "warning"} label={agree ? "agrees" : "disagrees"} />
        </span>
        {rca.anomaly && (
          <span title={rca.anomaly.top_deviations.map((d) => `${d.feature}: z=${d.z}`).join("\n")}>
            Anomaly score {rca.anomaly.score.toFixed(2)}{" "}
            <Badge value={rca.anomaly.is_anomalous ? "warning" : "muted"} label={rca.anomaly.is_anomalous ? "anomalous" : "within normal range"} />
            <span className="muted small">
              {" "}
              top deviations: {rca.anomaly.top_deviations.slice(0, 3).map((d) => d.feature).join(", ")}
            </span>
          </span>
        )}
      </div>
      <p className="muted small">
        {rca.model} · analysed {fmt.ago(rca.analyzed_at)}. Advisory only: recovery always requires operator approval.
      </p>
    </div>
  );
}

function IncidentDetail({ id, onChange }: { id: number; onChange: () => void }) {
  const { data: inc, error, reload } = usePoll<Incident>(`/api/incidents/${id}`, 10_000);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const act = async (path: string, body?: unknown) => {
    setBusy(path);
    setActionError(null);
    try {
      await postJSON(`/api/incidents/${id}/${path}`, body);
      reload();
      onChange();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  if (error) return <ErrorBanner error={error} />;
  if (!inc) return <Card title={`Incident #${id}`}><p className="muted">Loading…</p></Card>;
  const ev = inc.evidence;

  return (
    <div className="stack">
      <Card
        title={
          <>
            #{inc.id} {inc.title}
          </>
        }
        actions={
          <>
            {inc.status === "open" && (
              <button disabled={!!busy} onClick={() => act("acknowledge")}>
                Acknowledge
              </button>
            )}
            {inc.status !== "resolved" ? (
              <button disabled={!!busy} onClick={() => act("resolve", { note: "resolved from platform UI" })}>
                Resolve
              </button>
            ) : (
              <button disabled={!!busy} onClick={() => act("reopen")}>
                Reopen
              </button>
            )}
            <button disabled={!!busy} onClick={() => act("evidence/refresh")}>
              Refresh evidence
            </button>
          </>
        }
      >
        {actionError && <div className="banner banner-bad">{actionError}</div>}
        <div className="row-gap">
          <Badge value={inc.status} /> <Badge value={inc.severity} /> <Badge value="muted" label={inc.category} />
          <span className="muted small">
            opened {fmt.time(inc.opened_at)}
            {inc.resolved_at && ` · resolved ${fmt.time(inc.resolved_at)}`}
          </span>
        </div>
        <table className="compact">
          <thead>
            <tr>
              <th>Alert</th>
              <th>Severity</th>
              <th>Status</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            {inc.alerts.map((a) => (
              <tr key={a.id}>
                <td className="mono">{a.alertname}</td>
                <td>
                  <Badge value={a.severity} />
                </td>
                <td>
                  <Badge value={a.status} />
                </td>
                <td className="small">{a.annotations.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title="Root cause analysis"
        actions={
          <button disabled={!!busy || !inc.evidence} onClick={() => act("rca")}>
            Re-run RCA
          </button>
        }
      >
        {inc.rca ? <RcaPanel rca={inc.rca} incidentId={inc.id} /> : <Empty>{inc.evidence ? "No RCA result yet." : "Waiting for evidence…"}</Empty>}
      </Card>

      <Card title={ev ? `Evidence (last ${ev.window_minutes} min, collected ${fmt.ago(ev.collected_at)})` : "Evidence"}>
        {!ev ? (
          <Empty>Evidence is being collected…</Empty>
        ) : (
          <>
            <div className="evidence-grid">
              {METRICS.map((m) => {
                const e = ev.metrics[m.key];
                if (!e) return null;
                return (
                  <div key={m.key} className="evidence-metric">
                    <div className="row-between">
                      <span className="muted small">{m.label}</span>
                      {e.error ? (
                        <span className="muted small">unavailable</span>
                      ) : (
                        <span className="mono small">
                          {e.baseline != null ? m.format(e.baseline) : "–"} → <strong>{e.now != null ? m.format(e.now) : "–"}</strong>
                        </span>
                      )}
                    </div>
                    {!e.error && <TimeChart points={e.points} format={m.format} height={80} />}
                  </div>
                );
              })}
            </div>
            <h3>Top error/warning log messages (15 min)</h3>
            {ev.logs.error ? (
              <p className="muted">Logs unavailable: {ev.logs.error}</p>
            ) : ev.logs.top_messages?.length ? (
              <table className="compact">
                <tbody>
                  {ev.logs.top_messages.map((m) => (
                    <tr key={`${m.msg}-${m.level}`}>
                      <td className="mono small">{m.count}×</td>
                      <td>
                        <Badge value={m.level.toLowerCase() === "error" ? "error" : "warning"} label={m.level} />
                      </td>
                      <td>{m.msg}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>No error or warning logs.</Empty>
            )}
            <h3>Deployments in the hour before</h3>
            {ev.deployments.length ? (
              <ul className="timeline">
                {ev.deployments.map((d, i) => (
                  <li key={i}>
                    <span className="muted small">{fmt.time(d.ts)}</span>
                    <span>
                      {d.event} <span className="mono">{d.image_tag}</span>
                    </span>
                    <Badge value={d.status} />
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No deployments shortly before this incident.</Empty>
            )}
          </>
        )}
      </Card>

      {inc.ground_truth?.length ? (
        <Card title="Experiment ground truth">
          <p className="muted small">Faults injected deliberately during this incident. Used only to evaluate the RCA engine, never as its input.</p>
          <ul>
            {inc.ground_truth.map((g, i) => (
              <li key={i}>
                <Badge value="experiment" label={g.mode} /> {g.summary}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
