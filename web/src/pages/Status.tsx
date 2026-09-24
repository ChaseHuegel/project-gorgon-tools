import { useEffect, useRef, useState } from "react";
import { api, streamUrl } from "../api/client";
import type { ChatLine, Status, StatusStreamPayload } from "../api/types";
import { Page } from "../components/Page";
import { StatusBadge } from "../components/StatusBadge";
import { useApiData, useStatus } from "../hooks/useApi";
import { useSse } from "../hooks/useSse";

export default function StatusPage() {
  const { data, loading, error, reload } = useStatus();
  const [liveCounts, setLiveCounts] = useState<Record<string, number> | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const chatState = useApiData(() => api.chatTail(500), [], 1500);
  const chat = chatState.data;
  const [follow, setFollow] = useState(true);
  const chatBoxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (follow && chatBoxRef.current) {
      chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight;
    }
  }, [chat, follow]);

  const status = (data as Status) ?? null;

  useSse<StatusStreamPayload>({
    url: streamUrl("status"),
    event: "status",
    enabled: Boolean(status?.open_session_id),
    onEvent: (p) => setLiveCounts(p.open_session_counts),
  });

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

  const counts = liveCounts !== undefined ? liveCounts : status.open_session_counts;

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

      <h2 style={{ fontSize: "1rem", margin: "1.25rem 0 0.5rem" }}>
        Tailed chat log
        {chat?.found && chat.file && (
          <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: "0.5rem" }}>{chat.file}</span>
        )}
      </h2>
      {chat?.found ? (
        <>
          <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", marginBottom: "0.5rem" }}>
            <label style={{ color: "var(--muted)", fontSize: "0.85rem", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={follow}
                onChange={(e) => setFollow(e.target.checked)}
                style={{ marginRight: "0.3rem", verticalAlign: "middle" }}
              />
              Follow
            </label>
            <span style={{ color: "var(--muted)", fontSize: "0.8rem" }}>{chat.lines.length} line(s)</span>
          </div>
          <div ref={chatBoxRef} style={chatBoxStyle}>
            {chat.lines.map((line, i) => (
              <div key={i} style={{ color: kindColor(line) }}>
                {line.text}
              </div>
            ))}
          </div>
        </>
      ) : (
        <p style={{ color: "var(--muted)" }}>
          {chat ? `${chat.reason} — ${chat.log_dir ?? "no chat log directory"}` : "Loading chat log…"}
        </p>
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

function kindColor(line: ChatLine): string | undefined {
  if (line.kind === "loot") return "var(--green)";
  if (line.kind === "bury") return "var(--amber)";
  return undefined;
}

const chatBoxStyle: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "0.75rem 1rem",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: "0.8rem",
  lineHeight: 1.45,
  maxHeight: "24rem",
  overflowY: "auto",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
};

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