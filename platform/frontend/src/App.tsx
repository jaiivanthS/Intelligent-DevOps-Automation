import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { usePoll } from "./api";
import Dashboard from "./pages/Dashboard";
import Deployments from "./pages/Deployments";
import Incidents from "./pages/Incidents";
import Logs from "./pages/Logs";
import Monitoring from "./pages/Monitoring";
import Pipeline from "./pages/Pipeline";
import Recovery from "./pages/Recovery";

const NAV = [
  { to: "/", label: "Dashboard", icon: "▦" },
  { to: "/pipeline", label: "Pipeline", icon: "⟳" },
  { to: "/deployments", label: "Deployments", icon: "⇪" },
  { to: "/monitoring", label: "Monitoring", icon: "∿" },
  { to: "/logs", label: "Logs", icon: "≡" },
  { to: "/incidents", label: "Incidents", icon: "⚠" },
  { to: "/recovery", label: "Recovery", icon: "↺" },
];

type Config = Record<string, boolean | string | null>;

export default function App() {
  const { data: config } = usePoll<Config>("/api/config", 0);
  const integrations = ["jenkins", "prometheus", "loki", "alertmanager", "app", "release_state"];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">✓</span>
          <div>
            <div className="brand-name">DevOps Platform</div>
            <div className="brand-sub">{(config?.service as string) ?? "demo-app"}</div>
          </div>
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="nav-icon" aria-hidden>
                {n.icon}
              </span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="integrations">
          <div className="integrations-title">Integrations</div>
          {integrations.map((k) => (
            <div key={k} className="integration">
              <span className={`dot ${config?.[k] ? "dot-on" : "dot-off"}`} />
              {k.replace("_", " ")}
            </div>
          ))}
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
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
    </div>
  );
}
