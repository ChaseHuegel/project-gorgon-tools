import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { DropRateRow } from "../api/types";
import { DataTable, fmtTime } from "../components/DataTable";
import { Page } from "../components/Page";
import { useApiData } from "../hooks/useApi";

interface MonsterAgg {
  monster: string;
  drops: number;
  quantity: number;
  encounters: number;
  droprate: number;
}

function aggregate(rates: DropRateRow[]): MonsterAgg[] {
  const map = new Map<string, MonsterAgg>();
  for (const r of rates) {
    const cur = map.get(r.monster) ?? { monster: r.monster, drops: 0, quantity: 0, encounters: 0, droprate: 0 };
    cur.drops += r.drops;
    cur.quantity += r.quantity;
    cur.encounters = Math.max(cur.encounters, r.encounters);
    map.set(r.monster, cur);
  }
  const list = [...map.values()];
  for (const m of list) m.droprate = m.encounters ? Math.round((m.drops / m.encounters) * 100000) / 100000 : 0;
  return list.sort((a, b) => b.drops - a.drops);
}

export default function DashboardPage() {
  const { data: summary, error: sErr } = useApiData(() => api.summary());
  const { data: rates, error: rErr } = useApiData(() => api.dropRates());

  const totals = aggregate(rates ?? []).slice(0, 20);

  return (
    <Page title="Drop-rate dashboard">
      {rErr && <p style={{ color: "var(--red)" }}>{rErr}</p>}
      <h2 style={{ fontSize: "1rem", margin: "0.5rem 0" }}>Total drops by monster (top 20)</h2>
      <div style={{ width: "100%", height: 320 }}>
        <ResponsiveContainer>
          <BarChart data={totals} margin={{ bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="monster" tick={{ fill: "var(--muted)", fontSize: 12 }} angle={-35} textAnchor="end" />
            <YAxis tick={{ fill: "var(--muted)", fontSize: 12 }} />
            <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)" }} />
            <Legend />
            <Bar dataKey="drops" name="Drops" fill="var(--accent)" />
            <Bar dataKey="quantity" name="Quantity" fill="var(--green)" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <h2 style={{ fontSize: "1rem", margin: "1.5rem 0 0.5rem" }}>Drop rates by monster and item</h2>
      <DataTable<DropRateRow>
        rows={rates ?? []}
        empty={sErr ? sErr : "No drop-rate data yet."}
        columns={[
          { key: "monster", header: "Monster", render: (r) => r.monster },
          { key: "item", header: "Item", render: (r) => r.item },
          { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right" },
          { key: "quantity", header: "Qty", render: (r) => String(r.quantity), align: "right" },
          { key: "encounters", header: "Encounters", render: (r) => String(r.encounters), align: "right" },
          {
            key: "rate",
            header: "Rate",
            render: (r) => (r.drop_rate * 100).toFixed(2) + "%",
            align: "right",
          },
        ]}
      />

      <h2 style={{ fontSize: "1rem", margin: "1.5rem 0 0.5rem" }}>Summary</h2>
      <DataTable
        rows={summary ?? []}
        columns={[
          { key: "zone", header: "Zone", render: (r) => r.zone },
          { key: "monster", header: "Monster", render: (r) => r.monster },
          { key: "activity", header: "Activity", render: (r) => r.activity },
          { key: "item", header: "Item", render: (r) => r.item },
          { key: "count", header: "Drops", render: (r) => String(r.drop_count), align: "right" },
          { key: "qty", header: "Qty", render: (r) => String(r.total_quantity), align: "right" },
        ]}
      />

      <p style={{ color: "var(--muted)", fontSize: "0.8rem" }}>Rates measured at {fmtTime(Date.now())}</p>
    </Page>
  );
}