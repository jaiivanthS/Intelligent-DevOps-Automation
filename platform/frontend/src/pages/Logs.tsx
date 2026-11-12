import { useState } from "react";
import type { LogLine, Result } from "../api";
import { usePoll } from "../api";
import { Badge, Card, Empty, ErrorBanner, FromResult } from "../components";
import { PageHeader } from "../effects";

const LEVELS = ["ERROR", "WARNING", "INFO"];
const EVENTS = ["", "http_request", "chaos_error", "dependency_error", "chaos_configured", "startup"];

export default function Logs() {
  const [levels, setLevels] = useState<string[]>(["ERROR", "WARNING"]);
  const [event, setEvent] = useState("");
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");
  const [minutes, setMinutes] = useState(60);

  const params = new URLSearchParams({ minutes: String(minutes), limit: "300" });
  if (levels.length && levels.length < LEVELS.length) params.set("level", levels.join(","));
  if (event) params.set("event", event);
  if (applied) params.set("search", applied);
  const { data, error } = usePoll<Result<LogLine[]> & { query: string }>(`/api/logs?${params}`, 15_000);

  const toggle = (lv: string) => setLevels((cur) => (cur.includes(lv) ? cur.filter((l) => l !== lv) : [...cur, lv]));

  return (
    <>
      <PageHeader index={5} kicker="Loki stream" title="Logs" sub="Structured JSON logs from every container. Filters compile to validated LogQL." />
      <ErrorBanner error={error} />
      <Card>
        <form
          className="filters"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied(search.trim());
          }}
        >
          {LEVELS.map((lv) => (
            <label key={lv} className="check">
              <input type="checkbox" checked={levels.includes(lv)} onChange={() => toggle(lv)} /> {lv}
            </label>
          ))}
          <select value={event} onChange={(e) => setEvent(e.target.value)} aria-label="Event type">
            {EVENTS.map((ev) => (
              <option key={ev} value={ev}>
                {ev || "any event"}
              </option>
            ))}
          </select>
          <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Time range">
            <option value={15}>last 15 min</option>
            <option value={60}>last hour</option>
            <option value={360}>last 6 h</option>
            <option value={1440}>last 24 h</option>
          </select>
          <input type="search" placeholder="contains text… (Enter)" value={search} onChange={(e) => setSearch(e.target.value)} />
        </form>
        {data?.query && <div className="muted small mono query">LogQL: {data.query}</div>}
      </Card>
      <Card title={data?.ok ? `${data.data?.length ?? 0} lines` : "Lines"}>
        <FromResult result={data ?? undefined} what="Loki">
          {(lines) =>
            lines.length ? (
              <table className="logs">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Level</th>
                    <th>Message</th>
                    <th>Route</th>
                    <th>Status</th>
                    <th>ms</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => {
                    const j = l.json ?? {};
                    return (
                      <tr key={`${l.ts_ns}-${i}`} title={l.line}>
                        <td className="muted small mono">{new Date(l.ts_ns / 1e6).toLocaleTimeString()}</td>
                        <td>
                          <Badge value={String(j.level ?? "").toLowerCase() === "error" ? "error" : String(j.level ?? "").toLowerCase()} label={String(j.level ?? "–")} />
                        </td>
                        <td>{String(j.msg ?? l.line)}</td>
                        <td className="mono small">{String(j.route ?? "")}</td>
                        <td className="mono small">{String(j.status ?? "")}</td>
                        <td className="mono small">{String(j.duration_ms ?? "")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <Empty>No log lines match these filters.</Empty>
            )
          }
        </FromResult>
      </Card>
    </>
  );
}
