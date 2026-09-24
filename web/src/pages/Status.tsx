import { useState } from "react";
import { api } from "../api/client";
import type { Status } from "../api/types";
import { Page } from "../components/Page";
import { StatusBadge } from "../components/StatusBadge";
import { useStatus } from "../hooks/useApi";

export default function StatusPage() {
  const { data, loading, error, reload } = useStatus();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const status = data as Status | null;

  async function toggle() {
    if (!status) return;
    setBusy(true);
    setActionError(null);
    try {
      if (status.daemon.running) await api.daemonStop();
      else await api.daemonStart();
      reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (loading && !status) return <p>Loading status…</p>;
  if (!status) return <p style={{ color: "var(--red)" }}>Status unavailable: {error ?? "no data"}</p>;

  const counts = status.open_session_counts;

  return (
    <Page
      title="Capture status"
      actions={
        <StatusBadge ok={status.daemon.running} label={status.daemon.running ? "daemon running" : "daemon stopped"} />
      }
    >
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem" }}>
        <button onClick={toggle} disabled={busy} style={btnStyle}>
          {busy ? "…" : status.daemon.running ? "Stop capture" : "Start capture"}
        </button>
        {status.daemon.pid && <span style={{ color: "var(--muted)" }}>pid {status.daemon.pid}</span>}
      </div>
      {actionError && <p style={{ color: "var(--red)" }}>{actionError}</p>}

      {status.warnings.length > 0 && (
        <div
          style={{
            border: "1px solid var(--amber)",
            borderRadius: 8,
            padding: "0.75rem 1rem",
            marginBottom: "1rem",
            color: "var(--amber)",
          }}
        >
          <strong>Setup warnings</strong>
          <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.25rem" }}>
            {status.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div style={grid}>
        <InfoCard label="Database" value={status.db_path} />
        <InfoCard label="Config file" value={status.config_path} />
        <InfoCard label="Total sessions" value={String(status.sessions_total)} />
        <InfoCard label="Open session" value={status.open_session_id != null ? `#${status.open_session_id}` : "none"} />
      </div>

      <h2 style={{ fontSize: "1rem", margin: "1.25rem 0 0.5rem" }}>Open session event counts</h2>
      {counts ? (
        <div style={grid}>
          {Object.entries(counts).map(([name, count]) => (
            <InfoCard key={name} label={name} value={String(count)} />
          ))}
        </div>
      ) : (
        <p style={{ color: "var(--muted)" }}>No session currently open.</p>
      )}
    </Page>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        background: "var(--panel)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "0.75rem 1rem",
      }}
    >
      <div style={{ fontSize: "0.75rem", color: "var(--muted)", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: "0.9rem", wordBreak: "break-all" }}>{value}</div>
    </div>
  );
}

const grid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: "0.6rem",
};

const btnStyle: React.CSSProperties = {
  padding: "0.5rem 1rem",
  borderRadius: 8,
  border: "1px solid var(--accent)",
  background: "var(--accent)",
  color: "#fff",
  cursor: "pointer",
};