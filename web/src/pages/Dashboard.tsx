import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, DropRateParams } from "../api/client";
import type {
  ActivityDetail,
  DropRateRow,
  ItemDetail,
  SearchResults,
  SourceDetail,
  SummaryRow,
} from "../api/types";
import { DataTable, fmtTime } from "../components/DataTable";
import { Page } from "../components/Page";
import { useApiData } from "../hooks/useApi";

const EMPTY_SEARCH: SearchResults = { sources: [], items: [], activities: [] };

type DetailKind = "source" | "item" | "activity";

const STATUS_OPTIONS = ["Linked", "Orphaned"];
const PIE_COLORS = [
  "var(--accent)",
  "var(--green)",
  "var(--amber)",
  "var(--red)",
  "#61a0ff",
  "#b489ff",
  "#ff9ec7",
  "#7fd0b0",
];

export default function DashboardPage() {
  const [source, setSource] = useState("");
  const [item, setItem] = useState("");
  const [zone, setZone] = useState("");
  const [activity, setActivity] = useState("");
  const [status, setStatus] = useState("Linked");

  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [detail, setDetail] = useState<{ kind: DetailKind; name: string } | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  const distinct = useApiData(() => api.distinct());

  const search = useApiData(
    () => (debounced ? api.search(debounced) : Promise.resolve(EMPTY_SEARCH)),
    [debounced],
  );

  const rateFilters = useMemo<DropRateParams>(
    () => ({
      monster: source || undefined,
      item: item || undefined,
      zone: zone || undefined,
      activity: activity || undefined,
      status,
    }),
    [source, item, zone, activity, status],
  );
  const axisFilters = useMemo(
    () => ({
      source: source || undefined,
      item: item || undefined,
      zone: zone || undefined,
      activity: activity || undefined,
      status,
    }),
    [source, item, zone, activity, status],
  );

  const rates = useApiData(() => api.dropRates(rateFilters), [source, item, zone, activity, status]);
  const summary = useApiData(
    () => api.summary({ source: source || undefined, item: item || undefined, zone: zone || undefined, activity: activity || undefined }),
    [source, item, zone, activity],
  );
  const sources = useApiData(() => api.analysisSources({ ...axisFilters, limit: 50 }), [source, item, zone, activity, status]);
  const zones = useApiData(() => api.analysisZones(axisFilters), [source, item, zone, activity, status]);
  const topItems = useApiData(() => api.analysisItems(axisFilters), [source, item, zone, activity, status]);

  const detailData = useApiData<SourceDetail | ItemDetail | ActivityDetail | null>(
    () => {
      if (!detail) return Promise.resolve(null);
      if (detail.kind === "source") return api.sourceDetail(detail.name);
      if (detail.kind === "item") return api.itemDetail(detail.name);
      return api.activityDetail(detail.name);
    },
    [detail?.kind, detail?.name],
  );

  return (
    <Page title="Drop-rate dashboard">
      <FilterBar
        query={query}
        onQuery={setQuery}
        distinct={distinct.data}
        values={{ source, item, zone, activity, status }}
        onValues={{ setSource, setItem, setZone, setActivity, setStatus }}
        onClear={() => {
          setSource("");
          setItem("");
          setZone("");
          setActivity("");
          setStatus("Linked");
          setQuery("");
          setDetail(null);
        }}
        hasFilters={Boolean(source || item || zone || activity)}
      />

      {search.data && debounced && (
        <SearchResultsPanel
          results={search.data}
          onSelect={(kind: DetailKind, name: string) => {
            setDetail({ kind, name });
            setDebounced("");
            setQuery("");
          }}
          loading={search.loading}
        />
      )}

      {detailData.data ? (
        <DrillDown kind={detail!.kind} name={detail!.name} data={detailData.data} onClose={() => setDetail(null)} />
      ) : null}

      <Charts sources={sources.data} zones={zones.data} items={topItems.data} />

      <h2 style={{ fontSize: "1rem", margin: "0" }}>Drop rates by monster and item</h2>
      <DataTable<DropRateRow>
        rows={rates.data ?? []}
        empty={rates.error ?? "No drop-rate data yet."}
        columns={[
          { key: "monster", header: "Monster", render: (r) => r.monster, sortValue: (r) => r.monster },
          { key: "item", header: "Item", render: (r) => r.item, sortValue: (r) => r.item },
          { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
          { key: "quantity", header: "Qty", render: (r) => String(r.quantity), align: "right", sortValue: (r) => r.quantity },
          { key: "encounters", header: "Encounters", render: (r) => String(r.encounters), align: "right", sortValue: (r) => r.encounters },
          {
            key: "rate",
            header: "Rate",
            render: (r) => (r.drop_rate * 100).toFixed(2) + "%",
            align: "right",
            sortValue: (r) => r.drop_rate,
          },
        ]}
      />

      <h2 style={{ fontSize: "1rem", margin: "1.5rem 0 0.5rem" }}>Summary by zone / monster / item</h2>
      <DataTable<SummaryRow>
        rows={summary.data ?? []}
        empty={summary.error ?? "No summary data yet."}
        columns={[
          { key: "zone", header: "Zone", render: (r) => r.zone, sortValue: (r) => r.zone },
          { key: "monster", header: "Monster", render: (r) => r.monster, sortValue: (r) => r.monster },
          { key: "activity", header: "Activity", render: (r) => r.activity, sortValue: (r) => r.activity },
          { key: "item", header: "Item", render: (r) => r.item, sortValue: (r) => r.item },
          { key: "count", header: "Drops", render: (r) => String(r.drop_count), align: "right", sortValue: (r) => r.drop_count },
          { key: "qty", header: "Qty", render: (r) => String(r.total_quantity), align: "right", sortValue: (r) => r.total_quantity },
        ]}
      />

      <p style={{ color: "var(--muted)", fontSize: "0.8rem" }}>Rates measured at {fmtTime(Date.now())}</p>
    </Page>
  );
}

function FilterBar({
  query,
  onQuery,
  distinct,
  values,
  onValues,
  onClear,
  hasFilters,
}: {
  query: string;
  onQuery: (v: string) => void;
  distinct: { sources: string[]; zones: string[]; items: string[]; activities: string[] } | null;
  values: { source: string; item: string; zone: string; activity: string; status: string };
  onValues: {
    setSource: (v: string) => void;
    setItem: (v: string) => void;
    setZone: (v: string) => void;
    setActivity: (v: string) => void;
    setStatus: (v: string) => void;
  };
  onClear: () => void;
  hasFilters: boolean;
}) {
  return (
    <div style={barStyle}>
      <input
        placeholder="Search source, item, or activity…"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        style={{ ...inputStyle, flex: "1 1 240px", minWidth: 220 }}
        aria-label="Search"
      />
      <Select label="Source" value={values.source} onChange={onValues.setSource} options={distinct?.sources ?? []} />
      <Select label="Item" value={values.item} onChange={onValues.setItem} options={distinct?.items ?? []} />
      <Select label="Zone" value={values.zone} onChange={onValues.setZone} options={distinct?.zones ?? []} />
      <Select label="Activity" value={values.activity} onChange={onValues.setActivity} options={distinct?.activities ?? []} />
      <Select label="Status" value={values.status} onChange={onValues.setStatus} options={STATUS_OPTIONS} />
      {hasFilters && (
        <button onClick={onClear} style={clearStyle}>
          Clear
        </button>
      )}
    </div>
  );
}

function SearchResultsPanel({
  results,
  onSelect,
  loading,
}: {
  results: SearchResults;
  onSelect: (kind: DetailKind, name: string) => void;
  loading: boolean;
}) {
  const total = results.sources.length + results.items.length + results.activities.length;
  if (loading && total === 0) return null;
  if (total === 0) return <p style={resultNoteStyle}>No matches.</p>;
  return (
    <div style={{ ...panelStyle, marginBottom: "1rem" }}>
      <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>Matches — click to drill down</p>
      <div style={resultGridStyle}>
        {results.sources.length > 0 && (
          <div>
            <p style={groupLabel}>Sources</p>
            {results.sources.map((s) => (
              <button key={"src" + s.name} style={resultBtnStyle} onClick={() => onSelect("source", s.name)}>
                {s.name} <Muted>({s.drops} drops)</Muted>
              </button>
            ))}
          </div>
        )}
        {results.items.length > 0 && (
          <div>
            <p style={groupLabel}>Items / drops</p>
            {results.items.map((s) => (
              <button key={"itm" + s.name} style={resultBtnStyle} onClick={() => onSelect("item", s.name)}>
                {s.name} <Muted>({s.drops} drops)</Muted>
              </button>
            ))}
          </div>
        )}
        {results.activities.length > 0 && (
          <div>
            <p style={groupLabel}>Activities</p>
            {results.activities.map((s) => (
              <button key={"act" + s.name} style={resultBtnStyle} onClick={() => onSelect("activity", s.name)}>
                {s.name} <Muted>({s.drops} drops)</Muted>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DrillDown({
  kind,
  name,
  data,
  onClose,
}: {
  kind: DetailKind;
  name: string;
  data: SourceDetail | ItemDetail | ActivityDetail | null;
  onClose: () => void;
}) {
  return (
    <div style={{ ...panelStyle, marginBottom: "1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontSize: "1rem", margin: 0 }}>{kindLabel(kind)}: {name}</h2>
        <button onClick={onClose} style={clearStyle}>
          Close
        </button>
      </div>
      {data && <DetailTables kind={kind} data={data} />}
    </div>
  );
}

function DetailTables({ kind, data }: { kind: DetailKind; data: SourceDetail | ItemDetail | ActivityDetail }) {
  const zones =
    kind === "activity" ? (data as ActivityDetail).zones : kind === "source" ? (data as SourceDetail).zones : (data as ItemDetail).zones;
  return (
    <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", marginTop: "0.75rem" }}>
      {kind === "source" && (
        <DataTable
          empty="No items."
          rows={(data as SourceDetail).items}
          columns={[
            { key: "item", header: "Item", render: (r: DropRateRow) => r.item },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
            { key: "qty", header: "Qty", render: (r) => String(r.quantity), align: "right" },
            { key: "enc", header: "Encounters", render: (r) => String(r.encounters), align: "right" },
            { key: "rate", header: "Rate", render: (r) => (r.drop_rate * 100).toFixed(2) + "%", align: "right", sortValue: (r) => r.drop_rate },
          ]}
        />
      )}
      {kind === "item" && (
        <DataTable
          empty="No sources."
          rows={(data as ItemDetail).sources}
          columns={[
            { key: "monster", header: "Source", render: (r: DropRateRow) => r.monster },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
            { key: "enc", header: "Encounters", render: (r) => String(r.encounters), align: "right" },
            { key: "rate", header: "Rate", render: (r) => (r.drop_rate * 100).toFixed(2) + "%", align: "right", sortValue: (r) => r.drop_rate },
          ]}
        />
      )}
      {kind === "activity" && (
        <DataTable
          empty="No sources."
          rows={(data as ActivityDetail).sources}
          columns={[
            { key: "monster", header: "Source", render: (r) => r.monster },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
            { key: "enc", header: "Encounters", render: (r) => String(r.encounters), align: "right", sortValue: (r) => r.encounters },
          ]}
        />
      )}
      <DataTable
        empty="No zones."
        rows={zones}
        columns={[
          { key: "zone", header: "Zone", render: (r) => r.zone },
          { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
          { key: "sources", header: "Sources", render: (r) => (r.sources == null ? "—" : String(r.sources)), align: "right" },
        ]}
      />
      {kind === "activity" && (
        <DataTable
          empty="No items."
          rows={(data as ActivityDetail).items}
          columns={[
            { key: "item", header: "Item", render: (r) => r.item },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
          ]}
        />
      )}
    </div>
  );
}

function Charts({
  sources,
  zones,
  items,
}: {
  sources: (import("../api/types").SourceAgg)[] | null;
  zones: (import("../api/types").ZoneCount)[] | null;
  items: (import("../api/types").ItemCount)[] | null;
}) {
  return (
    <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", marginBottom: "1.5rem" }}>
      <ChartCard title="Total drops by source">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={sources ?? []} margin={{ bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="monster" tick={{ fill: "var(--muted)", fontSize: 11 }} angle={-35} textAnchor="end" height={70} />
            <YAxis tick={{ fill: "var(--muted)", fontSize: 12 }} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend />
            <Bar dataKey="drops" name="Drops" fill="var(--accent)" />
            <Bar dataKey="quantity" name="Quantity" fill="var(--green)" />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="Drop share by zone">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={zones ?? []}
              dataKey="drops"
              nameKey="zone"
              innerRadius={45}
              outerRadius={80}
              label={(e) => e.zone}
            >
              {(zones ?? []).map((_, i) => (
                <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} />
          </PieChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="Most-dropped items">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={items ?? []} margin={{ bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="item" tick={{ fill: "var(--muted)", fontSize: 11 }} angle={-35} textAnchor="end" height={70} />
            <YAxis tick={{ fill: "var(--muted)", fontSize: 12 }} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend />
            <Bar dataKey="drops" name="Drops" fill="var(--amber)" />
            <Bar dataKey="sources" name="Sources" fill="var(--green)" />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ ...panelStyle, height: 300 }}>
      <h3 style={{ fontSize: "0.9rem", margin: "0 0 0.5rem" }}>{title}</h3>
      {children}
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle} title={label} aria-label={label}>
      <option value="">{label}: all</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

function kindLabel(kind: DetailKind): string {
  if (kind === "source") return "Source";
  if (kind === "item") return "Item / drop";
  return "Activity";
}

function Muted({ children }: { children: React.ReactNode }) {
  return <span style={{ color: "var(--muted)" }}>{children}</span>;
}

const barStyle: React.CSSProperties = {
  display: "flex",
  gap: "0.6rem",
  flexWrap: "wrap",
  marginBottom: "1rem",
  alignItems: "center",
};
const inputStyle: React.CSSProperties = {
  padding: "0.4rem 0.6rem",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel)",
  color: "var(--text)",
};
const clearStyle: React.CSSProperties = {
  padding: "0.4rem 0.85rem",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "var(--panel)",
  color: "var(--text)",
  cursor: "pointer",
};
const panelStyle: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "0.75rem",
};
const resultNoteStyle: React.CSSProperties = {
  color: "var(--muted)",
  margin: "0 0 1rem",
};
const resultGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: "0.5rem",
};
const groupLabel: React.CSSProperties = {
  margin: "0 0 0.35rem",
  fontSize: "0.8rem",
  fontWeight: 600,
  color: "var(--muted)",
};
const resultBtnStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  textAlign: "left",
  marginBottom: "0.25rem",
  padding: "0.35rem 0.6rem",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "transparent",
  color: "var(--accent)",
  cursor: "pointer",
};
const tooltipStyle: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "0.5rem",
  fontSize: "0.8rem",
  color: "var(--text)",
};