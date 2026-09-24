import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import Calibrate from "./pages/Calibrate";
import Config from "./pages/Config";
import Dashboard from "./pages/Dashboard";
import ImportExport from "./pages/ImportExport";
import Loot from "./pages/Loot";
import Sessions from "./pages/Sessions";
import Status from "./pages/Status";

export default function App() {
  return (
    <BrowserRouter>
      <div style={{ display: "flex", minHeight: "100vh" }}>
        <nav style={navStyle}>
          <h1 style={{ fontSize: "1rem", margin: "0 0 1rem", color: "var(--accent)" }}>gorgon-tracker</h1>
          <NavLink to="/status">Status</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/loot">Loot</NavLink>
          <NavLink to="/sessions">Sessions</NavLink>
          <NavLink to="/config">Config</NavLink>
          <NavLink to="/calibrate">Calibrate</NavLink>
          <NavLink to="/import">Import / Export</NavLink>
        </nav>
        <main style={{ flex: 1, padding: "1.5rem", overflowX: "hidden" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/status" replace />} />
            <Route path="/status" element={<Status />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/loot" element={<Loot />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/config" element={<Config />} />
            <Route path="/calibrate" element={<Calibrate />} />
            <Route path="/import" element={<ImportExport />} />
            <Route path="*" element={<Placeholder title="Not found" />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      style={{
        display: "block",
        padding: "0.5rem 0.75rem",
        marginBottom: "0.25rem",
        borderRadius: 8,
        color: "var(--muted)",
      }}
    >
      {children}
    </Link>
  );
}

function Placeholder({ title }: { title: string }) {
  return <p style={{ color: "var(--muted)" }}>{title} — coming in the next phase.</p>;
}

const navStyle: React.CSSProperties = {
  width: 200,
  padding: "1.5rem 1rem",
  borderRight: "1px solid var(--border)",
  background: "var(--panel)",
  flexShrink: 0,
};