import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { LootRow } from "../api/types";
import { DataTable, fmtTime } from "../components/DataTable";
import { Evidence, LinkBadge } from "../components/LootEvidence";
import { Page } from "../components/Page";
import { useApiData } from "../hooks/useApi";

export default function LootPublic() {
  const { data, error, loading } = useApiData(() => api.loot(1000), [], 30000);
  const [monster, setMonster] = useState("");
  const [item, setItem] = useState("");
  const [activity, setActivity] = useState("");

  const rows = useMemo(() => {
    let list = data ?? [];
    if (monster) list = list.filter((r) => r.source.includes(monster));
    if (item) list = list.filter((r) => r.item.toLowerCase().includes(item.toLowerCase()));
    if (activity) list = list.filter((r) => r.activity === activity);
    return list;
  }, [data, monster, item, activity]);

  const distinct = (pick: (r: LootRow) => string) =>
    [...new Set((data ?? []).map(pick).filter(Boolean))].sort();

  return (
    <Page title="Recent loot">
      {error && <p style={{ color: "var(--red)" }}>{error}</p>}
      {loading && !data && <p>Loading…</p>}

      <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        <Select value={monster} onChange={setMonster} options={distinct((r) => r.source)} label="Source" />
        <Select value={activity} onChange={setActivity} options={distinct((r) => r.activity)} label="Activity" />
        <input
          placeholder="Item…"
          value={item}
          onChange={(e) => setItem(e.target.value)}
          style={inputStyle}
          aria-label="Item filter"
        />
      </div>

      <p style={{ color: "var(--muted)" }}>{rows.length} row(s)</p>
      <DataTable<LootRow>
        rows={rows}
        empty="No loot recorded yet."
        pageSize={50}
        columns={[
          { key: "time", header: "Time", render: (r) => fmtTime(r.captured_at), sortValue: (r) => r.captured_at },
          {
            key: "source",
            header: "Source",
            render: (r) => (
              <div>
                <div>{r.source}</div>
                <LinkBadge row={r} />
              </div>
            ),
            sortValue: (r) => r.source,
          },
          { key: "item", header: "Item", render: (r) => r.item, sortValue: (r) => r.item },
          { key: "amount", header: "Amount", render: (r) => String(r.amount), align: "right", sortValue: (r) => r.amount },
          { key: "activity", header: "Activity", render: (r) => r.activity, sortValue: (r) => r.activity },
          { key: "zone", header: "Zone", render: (r) => r.zone, sortValue: (r) => r.zone },
          { key: "evidence", header: "Evidence", render: (r) => <Evidence row={r} /> },
          {
            key: "status",
            header: "Status",
            render: (r) => (
              <span style={{ color: r.status === "Linked" ? "var(--green)" : "var(--amber)" }}>{r.status}</span>
            ),
            sortValue: (r) => r.status,
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