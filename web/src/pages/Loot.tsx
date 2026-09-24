import { useMemo, useRef, useState } from "react";
import { api, exportUrl, streamUrl } from "../api/client";
import type { LootRow } from "../api/types";
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
    return list;
  }, [live, data, monster, item, activity, status]);

  const distinct = (pick: (r: LootRow) => string) => [
    ...new Set([...(live ?? []), ...(data ?? [])].map(pick).filter(Boolean)),
  ].sort();

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
          { key: "source", header: "Source", render: (r) => r.source },
          { key: "item", header: "Item", render: (r) => r.item },
          { key: "amount", header: "Amount", render: (r) => String(r.amount), align: "right" },
          { key: "activity", header: "Activity", render: (r) => r.activity },
          { key: "zone", header: "Zone", render: (r) => r.zone },
          {
            key: "status",
            header: "Status",
            render: (r) => (
              <span style={{ color: r.status === "Linked" ? "var(--green)" : "var(--amber)" }}>{r.status}</span>
            ),
          },
        ]}
      />
    </Page>
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

const linkStyle: React.CSSProperties = {
  border: "1px solid var(--accent)",
  padding: "0.4rem 0.85rem",
  borderRadius: 8,
  color: "var(--accent)",
};