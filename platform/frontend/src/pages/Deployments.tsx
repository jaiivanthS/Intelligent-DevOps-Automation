import type { PlatformEvent, ReleaseRecord, ReleaseState, Result } from "../api";
import { usePoll } from "../api";
import { Badge, Card, Empty, ErrorBanner, FromResult } from "../components";
import { fmt } from "../format";

interface DeploymentsData {
  release: ReleaseState;
  running: Result<{ version: string; env: string; ready: boolean }>;
  history: ReleaseRecord[];
  events: PlatformEvent[];
}

export default function Deployments() {
  const { data, error } = usePoll<DeploymentsData>("/api/deployments", 10_000);
  const release = data?.release;
  const runningTag = data?.running.ok ? data.running.data?.version : undefined;
  const drift = runningTag && release?.current_image && fmt.tag(release.current_image) !== runningTag;

  return (
    <>
      <h1>Deployments</h1>
      <ErrorBanner error={error} />
      <div className="grid-2">
        <Card title="Environment">
          {release?.available ? (
            <dl className="kv">
              <dt>Environment</dt>
              <dd>{release.app_env ?? "–"}</dd>
              <dt>Deployed image</dt>
              <dd className="mono small">{release.current_image ?? "–"}</dd>
              <dt>Last good image</dt>
              <dd className="mono small">{release.last_good_image ?? "–"}</dd>
            </dl>
          ) : (
            <Empty>Release state is not mounted into the platform API.</Empty>
          )}
        </Card>
        <Card title="Running service">
          <FromResult result={data?.running} what="demo-app">
            {(info) => (
              <dl className="kv">
                <dt>Version</dt>
                <dd className="mono">{info.version}</dd>
                <dt>Readiness</dt>
                <dd>
                  <Badge value={info.ready ? "ready" : "down"} label={info.ready ? "ready" : "not ready"} />
                </dd>
                <dt>Consistency</dt>
                <dd>{drift ? <Badge value="warning" label="running version ≠ deployed image" /> : <Badge value="ok" label="consistent" />}</dd>
              </dl>
            )}
          </FromResult>
        </Card>
      </div>

      <Card title="Release history (app host audit trail)">
        {data?.history.length ? (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Result</th>
                <th>Image</th>
                <th>From</th>
                <th>Actor</th>
              </tr>
            </thead>
            <tbody>
              {data.history.map((r, i) => (
                <tr key={`${r.ts}-${i}`}>
                  <td className="muted">{fmt.time(r.ts)}</td>
                  <td>{r.action}</td>
                  <td>
                    <Badge value={r.result} />
                  </td>
                  <td className="mono small">{fmt.tag(r.image)}</td>
                  <td className="mono small">{fmt.tag(r.from)}</td>
                  <td className="muted small">{r.actor ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No releases recorded yet.</Empty>
        )}
      </Card>

      <Card title="Pipeline deployment events">
        {data?.events.length ? (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Build</th>
                <th>Stage</th>
                <th>Status</th>
                <th>Image tag</th>
                <th>Env</th>
              </tr>
            </thead>
            <tbody>
              {data.events.map((e) => (
                <tr key={e.id}>
                  <td className="muted">{fmt.time(e.ts)}</td>
                  <td className="mono">{e.build ? `#${e.build}` : "–"}</td>
                  <td>{e.event}</td>
                  <td>
                    <Badge value={e.status} />
                  </td>
                  <td className="mono small">{e.image_tag ?? "–"}</td>
                  <td>{e.environment ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No deployment events received yet.</Empty>
        )}
      </Card>
    </>
  );
}
