export const fmt = {
  num(v: number | null | undefined, digits = 2): string {
    return v === null || v === undefined || Number.isNaN(v) ? "–" : v.toFixed(digits);
  },
  pct(v: number | null | undefined, digits = 1): string {
    return v === null || v === undefined || Number.isNaN(v) ? "–" : `${(v * 100).toFixed(digits)}%`;
  },
  ms(seconds: number | null | undefined): string {
    if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
    return seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(2)} s`;
  },
  bytes(v: number | null | undefined): string {
    if (v === null || v === undefined || Number.isNaN(v)) return "–";
    const units = ["B", "KiB", "MiB", "GiB"];
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i++;
    }
    return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
  },
  duration(ms: number | null | undefined): string {
    if (!ms && ms !== 0) return "–";
    const s = Math.round(ms / 1000);
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
  },
  time(iso: string | number | null | undefined): string {
    if (!iso) return "–";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
  },
  ago(iso: string | number | null | undefined): string {
    if (!iso) return "–";
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return String(iso);
    const s = Math.round((Date.now() - t) / 1000);
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  },
  tag(image: string | null | undefined): string {
    if (!image) return "–";
    const i = image.lastIndexOf(":");
    return i > 0 ? image.slice(i + 1) : image;
  },
};

/** Map any status/result/severity word to a badge tone. */
export function tone(value: string | null | undefined): "good" | "bad" | "warn" | "info" | "muted" {
  const v = (value ?? "").toLowerCase();
  if (["success", "passed", "up", "ready", "resolved", "promoted", "approved", "ok", "healthy"].includes(v))
    return "good";
  if (["failure", "failed", "critical", "down", "error", "unhealthy", "aborted_by_failure"].includes(v))
    return "bad";
  if (["warning", "unstable", "waiting", "acknowledged", "running", "in_progress", "started", "rollback"].includes(v))
    return "warn";
  if (["open", "info", "firing", "experiment"].includes(v)) return "info";
  return "muted";
}
