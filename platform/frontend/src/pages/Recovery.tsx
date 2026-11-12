import type { ReleaseRecord, ReleaseState } from "../api";
import { usePoll } from "../api";
import { Badge, Card, Empty, ErrorBanner } from "../components";
import { fmt } from "../format";

interface DeploymentsData {
  release: ReleaseState;
  history: ReleaseRecord[];
}

export default function Recovery() {
  const { data, error } = usePoll<DeploymentsData>("/api/deployments", 10_000);
  const release = data?.release;
  const recoveries = (data?.history ?? []).filter((r) => ["rollback", "auto-restore", "restart"].includes(r.action));

  return (
    <>
      <h1>Recovery</h1>
      <ErrorBanner error={error} />
      <div className="grid-2">
        <Card title="Recovery options">
          <dl className="kv">
            <dt>Running</dt>
            <dd className="mono">{fmt.tag(release?.current_image)}</dd>
            <dt>Rollback target</dt>
            <dd className="mono">{fmt.tag(release?.last_good_image)}</dd>
          </dl>
          <div className="actions">
            <button disabled title="Approval-based recovery workflow is not enabled yet">
              Roll back to last good
            </button>
            <button disabled title="Approval-based recovery workflow is not enabled yet">
              Restart service
            </button>
          </div>
          <p className="muted small">
            Recovery actions require operator approval and are followed by an automatic health check. Until the approval
            workflow is enabled, use <span className="mono">/opt/app/appctl.sh rollback</span> on the app host. The
            pipeline also rolls back automatically when post-deploy smoke tests fail.
          </p>
        </Card>
        <Card title="Past recoveries">
          {recoveries.length ? (
            <table>
              <tbody>
                {recoveries.map((r, i) => (
                  <tr key={`${r.ts}-${i}`}>
                    <td className="muted small">{fmt.time(r.ts)}</td>
                    <td>{r.action}</td>
                    <td className="mono small">
                      {fmt.tag(r.from)} → {fmt.tag(r.image)}
                    </td>
                    <td>
                      <Badge value={r.result} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No rollbacks or restarts recorded.</Empty>
          )}
        </Card>
      </div>
    </>
  );
}
