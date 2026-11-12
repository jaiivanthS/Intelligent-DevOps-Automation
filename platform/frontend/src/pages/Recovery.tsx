import { Fragment, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { ReleaseState } from "../api";
import { postJSON, usePoll } from "../api";
import { Badge, Card, Empty, ErrorBanner } from "../components";
import { PageHeader } from "../effects";
import { fmt } from "../format";

interface RecoveryAction {
  id: number;
  incident_id: number | null;
  action: "rollback" | "restart";
  target_image: string | null;
  from_image: string | null;
  reason: string;
  status: string;
  requested_by: string;
  requested_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  jenkins_queue: string | null;
  jenkins_build: string | null;
  started_at: string | null;
  finished_at: string | null;
  detail: string | null;
  health: {
    smoke_test?: { smoke_test: string; checks: { check: string; ok: boolean; detail: string }[] } | null;
    platform_check?: { reachable: boolean; ready: boolean; version: string | null; version_matches_target?: boolean; error?: string };
  } | null;
}

interface Options {
  release: ReleaseState;
  active: RecoveryAction | null;
  blockers: string[];
  rollback: { available: boolean; default_target: string | null; reason: string | null; targets: string[] };
  restart: { available: boolean };
  approval_token_required: boolean;
  distinct_approver_required: boolean;
}

const NAME_KEY = "platform.operatorName";
const loadName = () => {
  try {
    return localStorage.getItem(NAME_KEY) ?? "";
  } catch {
    return "";
  }
};
const saveName = (n: string) => {
  try {
    localStorage.setItem(NAME_KEY, n);
  } catch {
    /* storage unavailable: name just isn't remembered */
  }
};

export default function Recovery() {
  const [params] = useSearchParams();
  const { data: opts, error, reload } = usePoll<Options>("/api/recovery/options", 5_000);
  const { data: actions, reload: reloadActions } = usePoll<RecoveryAction[]>("/api/recovery/actions?limit=30", 5_000);
  const [name, setName] = useState(loadName);
  const refresh = () => {
    reload();
    reloadActions();
  };

  return (
    <>
      <PageHeader index={7} kicker="Human in the loop" title="Recovery" sub="Request → approve → execute in Jenkins → health-check. Nothing touches production without a named approver." />
      <ErrorBanner error={error} />
      {opts?.blockers.map((b) => (
        <div key={b} className="banner banner-warn">
          {b}
        </div>
      ))}
      <div className="grid-2">
        <RequestCard
          opts={opts}
          name={name}
          setName={setName}
          presetAction={params.get("action")}
          presetIncident={params.get("incident")}
          onDone={refresh}
        />
        <ActiveCard opts={opts} name={name} setName={setName} onDone={refresh} />
      </div>
      <Card title="Recovery history">
        {actions?.length ? <History actions={actions} /> : <Empty>No recovery actions yet.</Empty>}
      </Card>
    </>
  );
}

function NameInput({ name, setName }: { name: string; setName: (n: string) => void }) {
  return (
    <label className="field">
      <span>Your name</span>
      <input
        value={name}
        onChange={(e) => {
          setName(e.target.value);
          saveName(e.target.value);
        }}
        placeholder="e.g. Asha"
        maxLength={80}
        required
      />
    </label>
  );
}

function RequestCard(props: {
  opts: Options | null;
  name: string;
  setName: (n: string) => void;
  presetAction: string | null;
  presetIncident: string | null;
  onDone: () => void;
}) {
  const { opts } = props;
  const [action, setAction] = useState<"rollback" | "restart">(props.presetAction === "restart" ? "restart" : "rollback");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState(props.presetIncident ? `Suggested by RCA for incident #${props.presetIncident}` : "");
  const [incident, setIncident] = useState(props.presetIncident ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (opts && !target) setTarget(opts.rollback.default_target ?? "");
  }, [opts, target]);

  const disabled = !opts || !!opts.active || busy || (action === "rollback" ? !opts.rollback.available : !opts.restart.available);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await postJSON("/api/recovery/actions", {
        action,
        reason,
        requested_by: props.name.trim(),
        target_image: action === "rollback" ? target || null : null,
        incident_id: incident ? Number(incident) : null,
      });
      props.onDone();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Request a recovery action">
      <dl className="kv">
        <dt>Running</dt>
        <dd className="mono">{fmt.tag(opts?.release.current_image)}</dd>
        <dt>Last good</dt>
        <dd className="mono">{fmt.tag(opts?.release.last_good_image)}</dd>
      </dl>
      <form className="form" onSubmit={submit}>
        <div className="segmented">
          {(["rollback", "restart"] as const).map((a) => (
            <button type="button" key={a} className={a === action ? "active" : ""} onClick={() => setAction(a)}>
              {a}
            </button>
          ))}
        </div>
        {action === "rollback" &&
          (opts?.rollback.available ? (
            <label className="field">
              <span>Roll back to</span>
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                {opts.rollback.targets.map((t) => (
                  <option key={t} value={t}>
                    {fmt.tag(t)}
                    {t === opts.rollback.default_target ? " (last good)" : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="muted small">Rollback unavailable: {opts?.rollback.reason ?? "loading…"}</p>
          ))}
        <label className="field">
          <span>Reason</span>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} minLength={3} maxLength={2000} required />
        </label>
        <div className="row-gap">
          <NameInput name={props.name} setName={props.setName} />
          <label className="field narrow">
            <span>Incident # (optional)</span>
            <input value={incident} onChange={(e) => setIncident(e.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </label>
        </div>
        {err && <div className="banner banner-bad">{err}</div>}
        <button type="submit" className="primary" disabled={disabled}>
          Request {action}
        </button>
        {opts?.active && <p className="muted small">Another action is already pending or running.</p>}
        <p className="muted small">
          Nothing runs until an operator approves. The approved action is executed by the Jenkins recovery job and then
          health-checked.
        </p>
      </form>
    </Card>
  );
}

const STEPS = ["requested", "approved", "running", "finished"];

function stepIndex(status: string): number {
  if (status === "pending_approval") return 0;
  if (status === "approved") return 1;
  if (status === "running") return 2;
  return 3;
}

function ActiveCard(props: { opts: Options | null; name: string; setName: (n: string) => void; onDone: () => void }) {
  const a = props.opts?.active ?? null;
  const [token, setToken] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!a)
    return (
      <Card title="Approval queue">
        <Empty>No recovery action is waiting for approval or running.</Empty>
      </Card>
    );

  const decide = async (verb: "approve" | "reject") => {
    setBusy(true);
    setErr(null);
    try {
      await postJSON(`/api/recovery/actions/${a.id}/${verb}`, {
        by: props.name.trim(),
        note: note || null,
        approval_token: token || null,
      });
      setToken("");
      props.onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const idx = stepIndex(a.status);
  return (
    <Card title={`#${a.id} ${a.action} → ${fmt.tag(a.target_image)}`} actions={<Badge value={a.status} label={a.status.replace("_", " ")} />}>
      <ol className="steps">
        {STEPS.map((s, i) => (
          <li key={s} className={i < idx ? "done" : i === idx ? "current" : ""}>
            {s}
          </li>
        ))}
      </ol>
      <dl className="kv">
        <dt>Requested</dt>
        <dd>
          {a.requested_by} · {fmt.ago(a.requested_at)}
        </dd>
        <dt>Reason</dt>
        <dd>{a.reason}</dd>
        <dt>Change</dt>
        <dd className="mono small">
          {fmt.tag(a.from_image)} → {fmt.tag(a.target_image)}
        </dd>
        {a.incident_id && (
          <>
            <dt>Incident</dt>
            <dd>
              <Link to={`/incidents/${a.incident_id}`}>#{a.incident_id}</Link>
            </dd>
          </>
        )}
        {a.decided_by && (
          <>
            <dt>Approved by</dt>
            <dd>
              {a.decided_by} · {fmt.ago(a.decided_at)}
            </dd>
          </>
        )}
        {a.jenkins_queue && (
          <>
            <dt>Jenkins</dt>
            <dd>
              <a href={a.jenkins_queue} target="_blank" rel="noreferrer">
                queued build ↗
              </a>
            </dd>
          </>
        )}
      </dl>
      {a.status === "pending_approval" && (
        <form className="form" onSubmit={(e) => e.preventDefault()}>
          <div className="row-gap">
            <NameInput name={props.name} setName={props.setName} />
            {props.opts?.approval_token_required && (
              <label className="field">
                <span>Approval token</span>
                <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
              </label>
            )}
          </div>
          <label className="field">
            <span>Note (optional)</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
          </label>
          {props.opts?.distinct_approver_required && <p className="muted small">Four-eyes rule: you cannot approve your own request.</p>}
          {err && <div className="banner banner-bad">{err}</div>}
          <div className="actions">
            <button type="button" className="primary" disabled={busy || props.name.trim().length < 2} onClick={() => decide("approve")}>
              Approve &amp; execute
            </button>
            <button type="button" disabled={busy || props.name.trim().length < 2} onClick={() => decide("reject")}>
              Reject
            </button>
          </div>
        </form>
      )}
      {a.status === "running" && <p className="muted">Executing in Jenkins, then running the post-recovery health check…</p>}
    </Card>
  );
}

function History({ actions }: { actions: RecoveryAction[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <table className="selectable">
      <thead>
        <tr>
          <th>#</th>
          <th>Action</th>
          <th>Change</th>
          <th>Status</th>
          <th>Requested</th>
          <th>Approved</th>
          <th>Health check</th>
        </tr>
      </thead>
      <tbody>
        {actions.map((a) => {
          const smoke = a.health?.smoke_test?.smoke_test;
          const pc = a.health?.platform_check;
          return (
            <Fragment key={a.id}>
              <tr onClick={() => setOpen(open === a.id ? null : a.id)} className={open === a.id ? "selected" : ""}>
                <td className="mono">{a.id}</td>
                <td>
                  {a.action}
                  {a.incident_id && <span className="muted small"> · inc #{a.incident_id}</span>}
                </td>
                <td className="mono small">
                  {fmt.tag(a.from_image)} → {fmt.tag(a.target_image)}
                </td>
                <td>
                  <Badge value={a.status} label={a.status.replace("_", " ")} />
                </td>
                <td className="small">
                  {a.requested_by} <span className="muted">{fmt.ago(a.requested_at)}</span>
                </td>
                <td className="small">{a.decided_by ?? "–"}</td>
                <td>
                  {smoke ? <Badge value={smoke} label={`smoke ${smoke}`} /> : "–"}{" "}
                  {pc && <Badge value={pc.ready ? "ready" : "down"} label={pc.ready ? "service ready" : "not ready"} />}
                </td>
              </tr>
              {open === a.id && (
                <tr>
                  <td colSpan={7}>
                    <div className="detail-box">
                      <div>
                        <strong>Reason:</strong> {a.reason}
                      </div>
                      {a.decision_note && (
                        <div>
                          <strong>Decision note:</strong> {a.decision_note}
                        </div>
                      )}
                      {a.detail && (
                        <div>
                          <strong>Result:</strong> {a.detail}
                        </div>
                      )}
                      {a.health?.smoke_test?.checks?.length ? (
                        <ul className="checks">
                          {a.health.smoke_test.checks.map((c) => (
                            <li key={c.check}>
                              <Badge value={c.ok ? "passed" : "failed"} label={c.ok ? "PASS" : "FAIL"} /> {c.check}{" "}
                              <span className="muted small">{c.detail}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {pc && (
                        <div className="small">
                          Platform check: reachable {String(pc.reachable)}, ready {String(pc.ready)}, version{" "}
                          <span className="mono">{pc.version ?? "–"}</span>
                          {pc.version_matches_target !== undefined && ` (matches target: ${pc.version_matches_target})`}
                        </div>
                      )}
                      <div className="muted small">
                        {a.started_at && `started ${fmt.time(a.started_at)}`} {a.finished_at && `· finished ${fmt.time(a.finished_at)}`}{" "}
                        {a.jenkins_build && `· Jenkins build #${a.jenkins_build}`}
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
