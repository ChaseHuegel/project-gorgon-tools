import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import About from "./pages/About";
import Dashboard from "./pages/Dashboard";
import LootPublic from "./pages/LootPublic";
import Sessions from "./pages/Sessions";

export default function AppPublic() {
  return (
    <BrowserRouter>
      <div style={{ display: "flex", minHeight: "100vh" }}>
        <nav style={navStyle}>
          <h1 style={{ fontSize: "1rem", margin: "0 0 1rem", color: "var(--accent)" }}>
            Project Gorgon loot data
          </h1>
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/loot">Recent loot</NavLink>
          <NavLink to="/sessions">Sessions</NavLink>
          <NavLink to="/about">About</NavLink>
        </nav>
        <main style={{ flex: 1, padding: "1.5rem", overflowX: "hidden" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard showExport={false} />} />
            <Route path="/loot" element={<LootPublic />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/about" element={<About />} />
            <Route path="*" element={<p style={{ color: "var(--muted)" }}>Not found.</p>} />
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

const navStyle: React.CSSProperties = {
  width: 200,
  padding: "1.5rem 1rem",
  borderRight: "1px solid var(--border)",
  background: "var(--panel)",
  flexShrink: 0,
};