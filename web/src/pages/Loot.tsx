import { useMemo, useRef, useState } from "react";
import { api, exportUrl, streamUrl } from "../api/client";
import type { LootOverride, LootRow } from "../api/types";
import { DataTable, fmtTime } from "../components/DataTable";
import { Page } from "../components/Page";
import { useApiData } from "../hooks/useApi";
import { useSse } from "../hooks/useSse";

export default function LootPage() {
  const { data, error, loading } = useApiData(() => api.loot(1000));
  const [live, setLive] = useState<LootRow[]>([]);
  const [monster, setMonster] = useState("");
  const [item, setItem] = useState("");
  const [activity, setActivity] = useState("");
  const [status, setStatus] = useState("");
  const [confidence, setConfidence] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const lastIdRef = useRef(0);

  const maxId = useMemo(() => {
    const ids = [lastIdRef.current, ...(data ?? []).map((r) => r.id)];
    return Math.max(...ids);
  }, [data]);

  useSse<LootRow>({
    url: streamUrl("loot", maxId),
    event: "loot",
    enabled: maxId > 0,
    onEvent: (row) =>
      setLive((prev) => {
        lastIdRef.current = Math.max(lastIdRef.current, row.id);
        if (prev.some((r) => r.id === row.id)) return prev;
        return [row, ...prev];
      }),
  });

  const rows = useMemo(() => {
    let list = [...live, ...(data ?? [])];
    if (monster) list = list.filter((r) => r.source.includes(monster));
    if (item) list = list.filter((r) => r.item.toLowerCase().includes(item.toLowerCase()));
    if (activity) list = list.filter((r) => r.activity === activity);
    if (status) list = list.filter((r) => r.status === status);
    if (confidence === "high") list = list.filter((r) => r.linked_via === "monster");
    if (confidence === "uncertain") list = list.filter((r) => r.linked_via !== "monster");
    return list;
  }, [live, data, monster, item, activity, status, confidence]);

  const distinct = (pick: (r: LootRow) => string) => [
    ...new Set([...(live ?? []), ...(data ?? [])].map(pick).filter(Boolean)),
  ].sort();

  const applyOverride = async (row: LootRow, payload: LootOverride) => {
    const updated = await api.overrideLoot(row.id, payload);
    setLive((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    setEditingId(null);
  };

  const revertOverride = async (row: LootRow) => {
    await api.revertLoot(row.id);
    const fresh = await api.loot(1000);
    const updated = fresh.find((r) => r.id === row.id);
    if (updated) {
      setLive((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    }
    setEditingId(null);
  };

  return (
    <Page
      title="Loot stream"
      actions={
        <a href={exportUrl()} style={linkStyle}>
          Export CSV
        </a>
      }
    >
      {error && <p style={{ color: "var(--red)" }}>{error}</p>}
      {loading && !data && <p>Loading…</p>}

      <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        <Select value={monster} onChange={setMonster} options={distinct((r) => r.source)} label="Monster" />
        <Select value={activity} onChange={setActivity} options={distinct((r) => r.activity)} label="Activity" />
        <Select value={status} onChange={setStatus} options={distinct((r) => r.status)} label="Status" />
        <Select
          value={confidence}
          onChange={setConfidence}
          options={["high", "uncertain"]}
          label="Confidence"
        />
        <input
          placeholder="Item…"
          value={item}
          onChange={(e) => setItem(e.target.value)}
          style={inputStyle}
        />
      </div>

      <p style={{ color: "var(--muted)" }}>{rows.length} row(s)</p>
      <DataTable<LootRow>
        rows={rows}
        columns={[
          { key: "time", header: "Time", render: (r) => fmtTime(r.captured_at) },
          {
            key: "source",
            header: "Source",
            render: (r) => (
              <div>
                <div>{r.source}</div>
                <LinkBadge row={r} />
              </div>
            ),
          },
          { key: "item", header: "Item", render: (r) => r.item },
          { key: "amount", header: "Amount", render: (r) => String(r.amount), align: "right" },
          { key: "activity", header: "Activity", render: (r) => r.activity },
          { key: "zone", header: "Zone", render: (r) => r.zone },
          {
            key: "evidence",
            header: "Evidence",
            render: (r) => <Evidence row={r} />,
          },
          {
            key: "status",
            header: "Status",
            render: (r) => (
              <span style={{ color: r.status === "Linked" ? "var(--green)" : "var(--amber)" }}>
                {r.status}
                {r.overridden ? " (overridden)" : ""}
              </span>
            ),
          },
          {
            key: "edit",
            header: "",
            render: (r) => (
              <button onClick={() => setEditingId(editingId === r.id ? null : r.id)} style={buttonStyle}>
                {editingId === r.id ? "Cancel" : "Fix"}
              </button>
            ),
          },
        ]}
        detail={(r) =>
          editingId === r.id ? (
            <EditRow
              row={r}
              options={distinct((x) => x.source)}
              onSave={applyOverride}
              onRevert={r.overridden ? revertOverride : undefined}
            />
          ) : null
        }
      />
    </Page>
  );
}

function LinkBadge({ row }: { row: LootRow }) {
  if (row.linked_via === "monster") {
    return <Badge tone="green">monster</Badge>;
  }
  if (row.linked_via === "target") {
    return <Badge tone={row.corroborated_by_search ? "blue" : "amber"}>target</Badge>;
  }
  return <Badge tone="amber">orphan</Badge>;
}

function Evidence({ row }: { row: LootRow }) {
  const bits: string[] = [];
  if (row.monster_name && row.monster_name !== row.source) {
    bits.push(`monster "${row.monster_name}"${row.monster_lag_ms != null ? ` -${row.monster_lag_ms}ms` : ""}`);
  } else if (row.monster_lag_ms != null && row.linked_via === "monster") {
    bits.push(`search -${row.monster_lag_ms}ms`);
  }
  if (row.target_name && row.target_name !== row.source) {
    bits.push(`target "${row.target_name}"${row.target_lag_ms != null ? ` -${row.target_lag_ms}ms` : ""}`);
  }
  if (row.linked_via === "target" && row.corroborated_by_search) {
    bits.push("corroborated by corpse search");
  }
  if (!bits.length) return <span style={{ color: "var(--muted)" }}>—</span>;
  return (
    <span style={{ fontSize: "0.85em", color: "var(--muted)" }} title={row.note ?? undefined}>
      {bits.join("; ")}
    </span>
  );
}

function EditRow({
  row,
  options,
  onSave,
  onRevert,
}: {
  row: LootRow;
  options: string[];
  onSave: (row: LootRow, payload: LootOverride) => Promise<void>;
  onRevert?: (row: LootRow) => Promise<void>;
}) {
  const [source, setSource] = useState(row.source);
  const [activity, setActivity] = useState(row.activity);
  const [status, setStatus] = useState(row.status);
  const [note, setNote] = useState(row.note ?? "");

  return (
    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center", padding: "0.4rem 0" }}>
      <input
        list="monster-names"
        placeholder="Source"
        value={source}
        onChange={(e) => setSource(e.target.value)}
        style={inputStyle}
      />
      <datalist id="monster-names">
        {options.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <select value={activity} onChange={(e) => setActivity(e.target.value)} style={inputStyle}>
        {["Looting", "Skinning", "Butchering", "Extracting", "Harvesting"].map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>
      <select value={status} onChange={(e) => setStatus(e.target.value)} style={inputStyle}>
        <option value="Linked">Linked</option>
        <option value="Orphaned">Orphaned</option>
      </select>
      <input
        placeholder="Note…"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        style={inputStyle}
      />
      <button onClick={() => onSave(row, { source, activity, status, note })} style={buttonStyle}>
        Save
      </button>
      {onRevert && (
        <button onClick={() => onRevert(row)} style={{ ...buttonStyle, color: "var(--amber)" }}>
          Revert
        </button>
      )}
    </div>
  );
}

function Badge({ tone, children }: { tone: "green" | "amber" | "blue"; children: React.ReactNode }) {
  const colors: Record<string, string> = {
    green: "var(--green)",
    amber: "var(--amber)",
    blue: "#6ab0ff",
  };
  return (
    <span
      style={{
        fontSize: "0.75em",
        border: `1px solid ${colors[tone]}`,
        color: colors[tone],
        borderRadius: 4,
        padding: "0 0.35rem",
      }}
    >
      {children}
    </span>
  );
}

function Select({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  label: string;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle} title={label}>
      <option value="">{label}: all</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "0.4rem 0.6rem",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel)",
  color: "var(--text)",
};

const buttonStyle: React.CSSProperties = {
  border: "1px solid var(--border)",
  background: "var(--panel)",
  color: "var(--text)",
  borderRadius: 6,
  padding: "0.3rem 0.6rem",
  cursor: "pointer",
};

const linkStyle: React.CSSProperties = {
  border: "1px solid var(--accent)",
  padding: "0.4rem 0.85rem",
  borderRadius: 8,
  color: "var(--accent)",
};