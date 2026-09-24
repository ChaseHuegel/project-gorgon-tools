import { useMemo, useRef, useState } from "react";
import { api, exportUrl, streamUrl } from "../api/client";
import type { LootOverride, LootRow } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DataTable, fmtTime } from "../components/DataTable";
import { Page } from "../components/Page";
import { useApiData } from "../hooks/useApi";
import { useSse } from "../hooks/useSse";

export default function LootPage() {
  const { data, error, loading, reload } = useApiData(() => api.loot(1000));
  const [live, setLive] = useState<LootRow[]>([]);
  const [edits, setEdits] = useState<Record<number, LootRow>>({});
  const [monster, setMonster] = useState("");
  const [item, setItem] = useState("");
  const [activity, setActivity] = useState("");
  const [status, setStatus] = useState("");
  const [confidence, setConfidence] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [confirmDelete, setConfirmDelete] = useState<number[] | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
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
    let list = [...live, ...(data ?? [])].map((r) => edits[r.id] ?? r);
    if (monster) list = list.filter((r) => r.source.includes(monster));
    if (item) list = list.filter((r) => r.item.toLowerCase().includes(item.toLowerCase()));
    if (activity) list = list.filter((r) => r.activity === activity);
    if (status) list = list.filter((r) => r.status === status);
    if (confidence === "high") list = list.filter((r) => r.linked_via === "monster");
    if (confidence === "uncertain") list = list.filter((r) => r.linked_via !== "monster");
    return list;
  }, [live, data, monster, item, activity, status, confidence, edits]);

  const distinct = (pick: (r: LootRow) => string) => [
    ...new Set([...(live ?? []), ...(data ?? [])].map(pick).filter(Boolean)),
  ].sort();

  const applyOverride = async (row: LootRow, payload: LootOverride) => {
    const updated = await api.overrideLoot(row.id, payload);
    setEdits((prev) => ({ ...prev, [updated.id]: updated }));
    setEditingId(null);
  };

  const revertOverride = async (row: LootRow) => {
    await api.revertLoot(row.id);
    const fresh = await api.loot(1000);
    const updated = fresh.find((r) => r.id === row.id);
    if (updated) {
      setEdits((prev) => ({ ...prev, [updated.id]: updated }));
    } else {
      setEdits((prev) => {
        const next = { ...prev };
        delete next[row.id];
        return next;
      });
    }
    setEditingId(null);
  };

  const toggleSelect = (id: number) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const visibleIds = useMemo(() => rows.map((r) => r.id), [rows]);
  const allSelected = rows.length > 0 && visibleIds.every((id) => selected.includes(id));
  const someSelected = selected.some((id) => visibleIds.includes(id));

  const toggleSelectAll = () =>
    setSelected((prev) =>
      allSelected ? prev.filter((id) => !visibleIds.includes(id)) : [...new Set([...prev, ...visibleIds])],
    );

  const requestDelete = (ids: number[]) => {
    setDeleteError(null);
    setConfirmDelete(ids);
  };

  const confirmDeleteRows = async () => {
    if (!confirmDelete || confirmDelete.length === 0) return;
    const ids = confirmDelete;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteLootRows(ids);
      setLive((prev) => prev.filter((r) => !ids.includes(r.id)));
      setEdits((prev) => {
        const next = { ...prev };
        ids.forEach((id) => delete next[id]);
        return next;
      });
      setSelected((prev) => prev.filter((id) => !ids.includes(id)));
      if (editingId != null && ids.includes(editingId)) setEditingId(null);
      reload();
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleting(false);
      setConfirmDelete(null);
    }
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
      <div
        style={{
          display: "flex",
          gap: "0.6rem",
          alignItems: "center",
          marginBottom: "0.75rem",
        }}
      >
        {selected.length > 0 && (
          <button onClick={() => requestDelete(selected)} disabled={deleting} style={dangerBtnStyle}>
            Delete selected ({selected.length})
          </button>
        )}
        {deleteError && <span style={{ color: "var(--red)", fontSize: "0.85rem" }}>{deleteError}</span>}
      </div>
      <DataTable<LootRow>
        rows={rows}
        columns={[
          {
            key: "select",
            header: "",
            headerRender: () => (
              <input
                type="checkbox"
                ref={(el) => {
                  if (el) el.indeterminate = someSelected && !allSelected;
                }}
                checked={allSelected}
                onChange={toggleSelectAll}
                title={allSelected ? "Clear selection" : "Select all"}
                aria-label={allSelected ? "Clear selection" : "Select all visible rows"}
              />
            ),
            render: (r) => (
              <input
                type="checkbox"
                checked={selected.includes(r.id)}
                onChange={() => toggleSelect(r.id)}
                aria-label={`Select row ${r.id}`}
              />
            ),
          },
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
              <div style={{ display: "flex", gap: "0.35rem" }}>
                <button onClick={() => setEditingId(editingId === r.id ? null : r.id)} style={buttonStyle}>
                  {editingId === r.id ? "Cancel" : "Fix"}
                </button>
                <button onClick={() => requestDelete([r.id])} disabled={deleting} style={dangerBtnStyle}>
                  Delete
                </button>
              </div>
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
      {confirmDelete && (
        <ConfirmDialog
          title={confirmDelete.length === 1 ? "Delete loot row?" : `Delete ${confirmDelete.length} loot rows?`}
          message={
            confirmDelete.length === 1
              ? "This permanently removes the row from the database and cannot be undone."
              : `This permanently removes ${confirmDelete.length} selected rows from the database and cannot be undone.`
          }
          confirmLabel="Delete"
          danger
          busy={deleting}
          onConfirm={confirmDeleteRows}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
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

const dangerBtnStyle: React.CSSProperties = {
  border: "1px solid var(--red)",
  background: "transparent",
  color: "var(--red)",
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