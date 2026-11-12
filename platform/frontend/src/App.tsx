import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { usePoll } from "./api";
import { Boot, LogoMark } from "./effects";
import Dashboard from "./pages/Dashboard";
import Deployments from "./pages/Deployments";
import Incidents from "./pages/Incidents";
import Logs from "./pages/Logs";
import Monitoring from "./pages/Monitoring";
import Pipeline from "./pages/Pipeline";
import Recovery from "./pages/Recovery";

export const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/deployments", label: "Deploys" },
  { to: "/monitoring", label: "Monitoring" },
  { to: "/logs", label: "Logs" },
  { to: "/incidents", label: "Incidents" },
  { to: "/recovery", label: "Recovery" },
];

export type Config = Record<string, boolean | string | null>;
const INTEGRATIONS = ["jenkins", "prometheus", "loki", "alertmanager", "app", "release_state"];

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

/** Cursor-following spotlight: writes the pointer position to CSS variables. */
function useSpotlight() {
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      document.documentElement.style.setProperty("--mx", `${e.clientX}px`);
      document.documentElement.style.setProperty("--my", `${e.clientY}px`);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);
}

export default function App() {
  const { data: config } = usePoll<Config>("/api/config", 30_000);
  const now = useClock();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  useSpotlight();
  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  const online = INTEGRATIONS.filter((k) => config?.[k]).length;
  const time = now.toISOString().slice(11, 19);

  return (
    <div className="shell">
      <Boot />
      <div className="fx fx-grid" aria-hidden />
      <div className="fx fx-spot" aria-hidden />
      <div className="fx fx-scan" aria-hidden />
      <div className="fx fx-noise" aria-hidden />

      <header className="topbar">
        <Link to="/" className="logo" aria-label="DevOps Platform home">
          <LogoMark />
          DEVOPS<span className="caret">_</span>
        </Link>
        <nav className={`mainnav ${menuOpen ? "open" : ""}`} aria-label="Main">
          {NAV.map((n, i) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="idx">0{i + 1}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sys-time" aria-label="System time">
          SYS_TIME
          <b>{time}</b>
          UTC+0
        </div>
        <div className="top-cta">
          <Link to="/recovery" className="btn primary">
            Recovery console <span className="arrow">↗</span>
          </Link>
        </div>
        <button className="menu-toggle" aria-label="Toggle menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
          {menuOpen ? "✕" : "≡"}
        </button>
      </header>

      <aside className="rail" aria-hidden>
        <div className="rail-dots">
          <i />
          <i />
          <i />
        </div>
        <div className="rail-text lime">Autonomous ops</div>
        <div className="rail-text">{now.getUTCFullYear()}</div>
        <div className="rail-bars" title={`${online}/${INTEGRATIONS.length} integrations online`}>
          {INTEGRATIONS.map((k) => (
            <i key={k} className={config?.[k] ? "on" : ""} />
          ))}
        </div>
      </aside>

      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard config={config} />} />
          <Route path="/pipeline" element={<Pipeline jenkinsUrl={(config?.jenkins_url as string) ?? null} />} />
          <Route path="/deployments" element={<Deployments />} />
          <Route path="/monitoring" element={<Monitoring />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/incidents" element={<Incidents />} />
          <Route path="/incidents/:id" element={<Incidents />} />
          <Route path="/recovery" element={<Recovery />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <footer className="footer">
        <div className="footer-cols">
          <div>
            <div className="logo-inline">
              <LogoMark dark={false} /> DEVOPS_
            </div>
            <div className="muted small">
              Intelligent DevOps Automation Platform
              <br />
              Build · Deploy · Observe · Recover
            </div>
          </div>
          <div>
            <h4>NAVIGATION</h4>
            <ul>
              {NAV.map((n) => (
                <li key={n.to}>
                  <Link to={n.to}>{n.label}</Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4>INTEGRATIONS</h4>
            <ul>
              {INTEGRATIONS.map((k) => (
                <li key={k}>
                  <span className={config?.[k] ? "lime" : "muted"}>{config?.[k] ? "■" : "□"}</span> {k.replace("_", " ")}
                </li>
              ))}
              <li>
                <span className={config?.rca ? "lime" : "muted"}>{config?.rca ? "■" : "□"}</span> rca: {(config?.rca as string) ?? "off"}
              </li>
            </ul>
          </div>
          <div>
            <h4>GLOBAL NODE</h4>
            <div className="muted small" style={{ marginBottom: 8 }}>
              AP-SOUTH-1 · {online}/{INTEGRATIONS.length} LINKS UP
            </div>
            <div className="node-map" aria-hidden>
              <span className="ping" style={{ left: "68%", top: "48%" }} />
              <span className="ping" style={{ left: "22%", top: "36%", animationDelay: "0.7s" }} />
              <span className="ping" style={{ left: "46%", top: "30%", animationDelay: "1.3s" }} />
            </div>
          </div>
        </div>
        <div className="hazard">
          <div className="hazard-label">
            &gt; ACCESS GRANTED<span className="caret">_</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
