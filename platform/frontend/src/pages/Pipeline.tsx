import { useState } from "react";
import type { Build, PlatformEvent, Result } from "../api";
import { usePoll } from "../api";
import { Badge, Card, Empty, ErrorBanner, FromResult } from "../components";
import { fmt } from "../format";

interface BuildsResponse extends Result<Build[]> {
  events: PlatformEvent[];
}

interface BuildDetail {
  number: number;
  stages: Result<{ name: string; status: string; duration_ms: number }[]>;
  tests: Result<{ passed: number; failed: number; skipped: number; failures: { test: string; error: string }[] }>;
  events: PlatformEvent[];
}

export default function Pipeline({ jenkinsUrl }: { jenkinsUrl: string | null }) {
  const { data, error } = usePoll<BuildsResponse>("/api/pipeline/builds", 10_000);
  const [selected, setSelected] = useState<number | null>(null);
  const builds = data?.ok ? data.data ?? [] : [];
  const current = selected ?? builds[0]?.number ?? null;

  return (
    <>
      <h1>Pipeline</h1>
      <ErrorBanner error={error} />
      <div className="grid-sidebar">
        <Card
          title="Builds"
          actions={jenkinsUrl && <a href={`${jenkinsUrl}/job/demo-app/`} target="_blank" rel="noreferrer">Open Jenkins ↗</a>}
        >
          <FromResult result={data ?? undefined} what="Jenkins API">
            {(list) =>
              list.length ? (
                <table className="selectable">
                  <thead>
                    <tr>
                      <th>Build</th>
                      <th>Result</th>
                      <th>Duration</th>
                      <th>Started</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((b) => (
                      <tr key={b.number} className={b.number === current ? "selected" : ""} onClick={() => setSelected(b.number)}>
                        <td>
                          <div className="mono">{b.display_name}</div>
                          {b.description && <div className="muted small">{b.description}</div>}
                        </td>
                        <td>
                          <Badge value={b.result} />
                        </td>
                        <td>{fmt.duration(b.duration_ms)}</td>
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
          {data && !data.ok && data.events.length > 0 && <EventsTable events={data.events} />}
        </Card>
        {current !== null ? <BuildPanel number={current} /> : <Card title="Build details"><Empty>Select a build.</Empty></Card>}
      </div>
    </>
  );
}

function BuildPanel({ number }: { number: number }) {
  const { data } = usePoll<BuildDetail>(`/api/pipeline/builds/${number}`, 10_000);
  const [showLog, setShowLog] = useState(false);
  const { data: log } = usePoll<Result<string>>(showLog ? `/api/pipeline/builds/${number}/log?lines=400` : null, 0);

  return (
    <div className="stack">
      <Card title={`Build #${number}: stages`}>
        <FromResult result={data?.stages} what="Stage view">
          {(stages) => (
            <div className="stages">
              {stages.map((s) => (
                <div key={s.name} className={`stage stage-${s.status.toLowerCase()}`}>
                  <div className="stage-name">{s.name}</div>
                  <div className="stage-meta">
                    <Badge value={s.status === "SUCCESS" ? "success" : s.status === "FAILED" ? "failed" : s.status} label={s.status} />
                    <span className="muted small">{fmt.duration(s.duration_ms)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </FromResult>
      </Card>
      <Card title="Test report">
        <FromResult result={data?.tests} what="Test report">
          {(t) => (
            <>
              <p>
                <Badge value="passed" label={`${t.passed} passed`} /> <Badge value={t.failed ? "failed" : "muted"} label={`${t.failed} failed`} />{" "}
                <Badge value="muted" label={`${t.skipped} skipped`} />
              </p>
              {t.failures.map((f) => (
                <details key={f.test}>
                  <summary className="mono">{f.test}</summary>
                  <pre className="log">{f.error}</pre>
                </details>
              ))}
            </>
          )}
        </FromResult>
      </Card>
      {data?.events.length ? (
        <Card title="Platform events for this build">
          <EventsTable events={data.events} />
        </Card>
      ) : null}
      <Card title="Console output" actions={<button onClick={() => setShowLog((s) => !s)}>{showLog ? "Hide" : "Show"} log</button>}>
        {showLog ? (
          <FromResult result={log ?? undefined} what="Console log">
            {(text) => <pre className="log">{text}</pre>}
          </FromResult>
        ) : (
          <Empty>Last 400 lines of the Jenkins console log.</Empty>
        )}
      </Card>
    </div>
  );
}

function EventsTable({ events }: { events: PlatformEvent[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Build</th>
          <th>Event</th>
          <th>Status</th>
          <th>Image</th>
        </tr>
      </thead>
      <tbody>
        {events.map((e) => (
          <tr key={e.id}>
            <td className="muted">{fmt.time(e.ts)}</td>
            <td className="mono">{e.build ? `#${e.build}` : "–"}</td>
            <td>{e.event}</td>
            <td>
              <Badge value={e.status} />
            </td>
            <td className="mono small">{e.image_tag ?? "–"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
