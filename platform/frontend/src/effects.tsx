import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

const BOOT_KEY = "platform.booted";

/** Terminal-style boot sequence, shown once per browser session (click to skip). */
export function Boot() {
  const [show, setShow] = useState(() => {
    try {
      return !sessionStorage.getItem(BOOT_KEY);
    } catch {
      return false;
    }
  });
  useEffect(() => {
    if (!show) return;
    try {
      sessionStorage.setItem(BOOT_KEY, "1");
    } catch {
      /* private mode: boot just shows again next time */
    }
    const id = window.setTimeout(() => setShow(false), 3100);
    return () => window.clearTimeout(id);
  }, [show]);
  if (!show) return null;

  const lines: [string, string][] = [
    ["> mounting telemetry bus", "OK"],
    ["> linking jenkins // ci-cd engine", "OK"],
    ["> attaching prometheus · loki · alertmanager", "OK"],
    ["> loading rca model // random_forest + iforest", "OK"],
    ["> verifying release state", "OK"],
  ];
  return (
    <div className="boot" onClick={() => setShow(false)} role="presentation">
      <div className="boot-inner">
        {lines.map(([text, ok], i) => (
          <div key={text} className="boot-line" style={{ animationDelay: `${0.15 + i * 0.3}s` }}>
            {text} <span className="muted">{".".repeat(Math.max(2, 44 - text.length))}</span> <span className="ok">[{ok}]</span>
          </div>
        ))}
        <div className="boot-bar">
          <span />
        </div>
        <div className="boot-granted">ACCESS GRANTED_</div>
      </div>
      <div className="boot-skip">CLICK TO SKIP</div>
    </div>
  );
}

export function LogoMark({ dark = true }: { dark?: boolean }) {
  return (
    <span className="logo-mark" aria-hidden>
      {Array.from({ length: 9 }, (_, i) => (
        <i key={i} style={dark ? undefined : { background: "var(--lime)" }} />
      ))}
    </span>
  );
}

/** Section title with index (/01), kicker and periodic glitch. */
export function PageHeader(props: { index: number; kicker: string; title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <div className="section-label">
          <span className="num">/{String(props.index).padStart(2, "0")}</span> {props.kicker}
        </div>
        <h1 className="glitch" data-text={props.title}>
          {props.title}
        </h1>
        {props.sub && <div className="page-sub">{props.sub}</div>}
      </div>
      {props.children && <div className="card-actions">{props.children}</div>}
    </div>
  );
}

/** Animates numeric changes (count-up). Non-numbers render as-is. */
export function CountUp({ value, format, duration = 900 }: { value: number | null | undefined; format: (v: number) => string; duration?: number }) {
  const [shown, setShown] = useState<number | null>(value ?? null);
  const from = useRef<number>(0);
  useEffect(() => {
    if (value === null || value === undefined || Number.isNaN(value)) {
      setShown(null);
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(a + (value - a) * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return <>{shown === null ? "–" : format(shown)}</>;
}

/** Infinite horizontal ticker. Items are duplicated for a seamless loop. */
export function Ticker({ label, items, speed = 45 }: { label: string; items: ReactNode[]; speed?: number }) {
  if (!items.length) return null;
  return (
    <div className="ticker" aria-label={label}>
      <div className="ticker-label">
        <i /> {label}
      </div>
      <div className="ticker-track" style={{ "--speed": `${speed}s` } as CSSProperties}>
        {[...items, ...items].map((item, i) => (
          <span className="ticker-item" key={i} aria-hidden={i >= items.length}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Segmented status bar like the "SYSTEM STATUS" readout. ratio is 0..1. */
export function Meter({ label, ratio, value, tone = "good" }: { label: string; ratio: number | null; value: ReactNode; tone?: "good" | "warn" | "bad" }) {
  const pct = ratio === null ? 0 : Math.max(2, Math.min(100, ratio * 100));
  return (
    <div className="meter-row">
      <span className="label">{label}</span>
      <span className={`meter ${tone === "good" ? "" : tone}`}>
        <span style={{ width: `${pct}%` }} />
      </span>
      <span className="val">{value}</span>
    </div>
  );
}

/** Typewriter line (CSS steps animation). */
export function Typed({ text, delay = 0, last = false }: { text: string; delay?: number; last?: boolean }) {
  return (
    <span
      className={`type ${last ? "last" : ""}`}
      style={{ "--n": text.length, "--delay": `${delay}s`, "--dur": `${Math.max(0.6, text.length * 0.035)}s` } as CSSProperties}
    >
      {text}
    </span>
  );
}
