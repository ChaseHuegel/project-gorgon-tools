import { useEffect, useState } from "react";
import { api, exportUrl } from "../api/client";
import type { NamesInfo } from "../api/types";
import { FilePicker } from "../components/FilePicker";
import { FormField, TextInput } from "../components/FormField";
import { Page } from "../components/Page";
import { StatusBadge } from "../components/StatusBadge";

type Kind = "zones" | "targets" | "loot" | "chat-json" | "packets-json";

export default function ImportExportPage() {
  const [ports, setPorts] = useState<{ found: boolean; bpf: string; persisted?: boolean } | null>(null);
  const [portBusy, setPortBusy] = useState(false);
  const [namesInfo, setNamesInfo] = useState<NamesInfo | null>(null);
  const [namesBusy, setNamesBusy] = useState(false);
  const [log, setLog] = useState<Array<{ kind: string; text: string; ok: boolean }>>([]);
  const [bytes, setBytes] = useState<File[]>([]);
  const [paths, setPaths] = useState<string[]>([]);
  const [chatDir, setChatDir] = useState("");
  const [migBytes, setMigBytes] = useState<File[]>([]);
  const [migPaths, setMigPaths] = useState<string[]>([]);
  const [kind, setKind] = useState<Kind>("loot");
  const [busy, setBusy] = useState(false);

  function push(kind: string, text: string, ok = true) {
    setLog((l) => [{ kind, text, ok }, ...l].slice(0, 12));
  }

  async function discover(persist: boolean) {
    setPortBusy(true);
    try {
      const res = await api.discoverPorts(persist);
      setPorts(res);
      if (!res.found) push("ports", "No game process found. Start the game and retry.", false);
    } catch (e) {
      push("ports", e instanceof Error ? e.message : String(e), false);
    } finally {
      setPortBusy(false);
    }
  }

  useEffect(() => {
    api
      .names()
      .then(setNamesInfo)
      .catch(() => undefined);
  }, []);

  async function updateNames() {
    setNamesBusy(true);
    try {
      const res = await api.updateNames();
      setNamesInfo(await api.names());
      push("names", `Updated: ${res.zones} zones, ${res.monsters} monsters -> ${res.path}`);
    } catch (e) {
      push("names", e instanceof Error ? e.message : String(e), false);
    } finally {
      setNamesBusy(false);
    }
  }

  async function runReplay() {
    setBusy(true);
    try {
      const form = new FormData();
      bytes.forEach((f) => form.append("files", f));
      paths.forEach((p) => form.append("paths", p));
      if (chatDir) form.append("chat_dir", chatDir);
      const res = await api.replay(form);
      push("replay", `Replay: ${res.drops} drops (session #${res.session_id})`);
    } catch (e) {
      push("replay", e instanceof Error ? e.message : String(e), false);
    } finally {
      setBusy(false);
    }
  }

  async function runMigrate() {
    setBusy(true);
    try {
      const form = new FormData();
      migBytes.forEach((f) => form.append("files", f));
      migPaths.forEach((p) => form.append("paths", p));
      const res = await api.migrate(form, kind);
      for (const item of res.imported) push("migrate", `${item.file}: ${item.imported} rows (session #${item.session_id})`);
    } catch (e) {
      push("migrate", e instanceof Error ? e.message : String(e), false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page
      title="Import / Export"
      actions={
        <a href={exportUrl()} style={linkStyle}>
          Export CSV
        </a>
      }
    >
      <Card title="Find game ports">
        <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
          Detect the running game's ephemeral ports and build a capture BPF filter.
        </p>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button onClick={() => discover(false)} disabled={portBusy} style={btnStyle}>{portBusy ? "…" : "Discover"}</button>
          <button onClick={() => discover(true)} disabled={portBusy} style={ghostBtn}>Discover & write to config</button>
        </div>
        {ports && (
          <p style={{ marginTop: "0.5rem" }}>
            <StatusBadge ok={ports.found} label={ports.found ? "game found" : "no game"} />
            {ports.bpf && <code style={{ display: "block", marginTop: "0.4rem" }}>{ports.bpf}</code>}
          </p>
        )}
      </Card>

      <Card title="Name data">
        <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
          Canonical zone and monster names used to correct OCR reads. Fetch the latest lists from the
          Project Gorgon wiki; the capture daemon picks up changes automatically.
        </p>
        {namesInfo ? (
          <p style={{ marginTop: "0.5rem", fontSize: "0.9rem" }}>
            <strong>{namesInfo.zones_count} zones</strong> · <strong>{namesInfo.monsters_count} monsters</strong>
            <span style={{ color: "var(--muted)" }}> — </span>
            {namesInfo.zones_source === "user" || namesInfo.monsters_source === "user" ? (
              <StatusBadge ok label="user overrides" />
            ) : (
              <span style={{ color: "var(--muted)" }}>bundled snapshot</span>
            )}
            <code style={{ display: "block", marginTop: "0.4rem", fontSize: "0.8rem" }}>{namesInfo.zones_path}</code>
            <code style={{ display: "block", marginTop: "0.15rem", fontSize: "0.8rem" }}>{namesInfo.monsters_path}</code>
          </p>
        ) : (
          <p style={{ color: "var(--muted)" }}>Loading name data…</p>
        )}
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
          <button onClick={updateNames} disabled={namesBusy} style={btnStyle}>
            {namesBusy ? "…" : "Update names from wiki"}
          </button>
        </div>
      </Card>

      <Card title="Replay historical captures">
        <FilePicker accept=".pcapng,.pcap,.json,.log,.txt,.csv" multiple paths={paths} onFiles={setBytes} onPaths={setPaths} />
        <FormField label="Chat directory (optional)">
          <TextInput value={chatDir} onChange={(e) => setChatDir(e.target.value)} placeholder="/path/to/ChatLogs" />
        </FormField>
        <p style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
          {bytes.length} uploaded file(s) · {paths.length} server path(s)
        </p>
        <button onClick={runReplay} disabled={busy} style={btnStyle}>{busy ? "…" : "Run replay"}</button>
      </Card>

      <Card title="Migrate legacy outputs">
        <FilePicker accept=".csv,.json" multiple paths={migPaths} onFiles={setMigBytes} onPaths={setMigPaths} />
        <div style={{ marginTop: "0.5rem" }}>
          <label style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
            Kind&nbsp;
            <select value={kind} onChange={(e) => setKind(e.target.value as Kind)} style={inputStyle}>
              <option value="loot">loot</option>
              <option value="zones">zones</option>
              <option value="targets">targets</option>
              <option value="chat-json">chat-json</option>
              <option value="packets-json">packets-json</option>
            </select>
          </label>
        </div>
        <p style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
          {migBytes.length} uploaded file(s) · {migPaths.length} server path(s)
        </p>
        <button onClick={runMigrate} disabled={busy} style={btnStyle}>{busy ? "…" : "Run migrate"}</button>
      </Card>

      <Card title="Activity log">
        {log.length === 0 && <p style={{ color: "var(--muted)" }}>Nothing yet.</p>}
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {log.map((item, i) => (
            <li key={i} style={{ color: item.ok ? "var(--text)" : "var(--red)", fontSize: "0.85rem", padding: "0.2rem 0" }}>
              <strong>[{item.kind}]</strong> {item.text}
            </li>
          ))}
        </ul>
      </Card>
    </Page>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={cardStyle}>
      <h2 style={cardTitle}>{title}</h2>
      {children}
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 10,
  padding: "1rem 1.25rem",
  marginBottom: "1rem",
};

const cardTitle: React.CSSProperties = { margin: "0 0 0.75rem", fontSize: "1rem" };

const btnStyle: React.CSSProperties = {
  padding: "0.5rem 1rem",
  borderRadius: 8,
  border: "1px solid var(--accent)",
  background: "var(--accent)",
  color: "#fff",
  cursor: "pointer",
};

const ghostBtn: React.CSSProperties = { ...btnStyle, background: "transparent", color: "var(--accent)" };

const linkStyle: React.CSSProperties = {
  border: "1px solid var(--accent)",
  padding: "0.4rem 0.85rem",
  borderRadius: 8,
  color: "var(--accent)",
};

const inputStyle: React.CSSProperties = {
  marginLeft: "0.4rem",
  padding: "0.3rem 0.5rem",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--bg)",
  color: "var(--text)",
};