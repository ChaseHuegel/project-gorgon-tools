import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
import { api, DropRateParams, exportAnalysisUrl, StatsParams } from "../api/client";
import type {
  ActivityDetail,
  DropRateRow,
  ItemDetail,
  SearchResults,
  SourceAgg,
  SourceDetail,
  Stats,
  SummaryRow,
  ZoneDetail,
  ZoneCount,
  ItemCount,
} from "../api/types";
import { DataTable, fmtTime } from "../components/DataTable";
import { Page } from "../components/Page";
import { useApiData } from "../hooks/useApi";

const EMPTY_SEARCH: SearchResults = { sources: [], items: [], activities: [] };

type DetailKind = "source" | "item" | "activity" | "zone";
type DetailData = SourceDetail | ItemDetail | ActivityDetail | ZoneDetail | null;

const STATUS_OPTIONS = ["Linked", "Orphaned"];
const TIME_OPTIONS = [
  { key: "", label: "All time" },
  { key: "7", label: "Last 7 days" },
  { key: "30", label: "Last 30 days" },
  { key: "90", label: "Last 90 days" },
];
const TABS = ["overview", "rates", "find", "matrix"] as const;
type Tab = (typeof TABS)[number];

const DAY_MS = 86_400_000;

const PIE_COLORS = [
  "var(--accent)",
  "var(--green)",
  "var(--amber)",
  "var(--red)",
  "#61a0ff",
  "#b489ff",
  "#ff9ec7",
  "#7fd0b0",
  "#f3a55a",
  "#8ed0ff",
  "#c9a0ff",
  "#ffd17a",
];

const TAB_LABEL: Record<Tab, string> = {
  overview: "Overview",
  rates: "Rates & summary",
  find: "Find drops",
  matrix: "Rate matrix",
};

export default function DashboardPage() {
  const [params, setParams] = useSearchParams();

  const tab: Tab = (TABS as readonly string[]).includes(params.get("tab") ?? "")
    ? (params.get("tab") as Tab)
    : "overview";
  const source = params.get("source") ?? "";
  const item = params.get("item") ?? "";
  const zone = params.get("zone") ?? "";
  const activity = params.get("activity") ?? "";
  const status = params.get("status") || "Linked";
  const sinceKey = params.get("since") ?? "";

  const sinceMs = useMemo(
    () => (sinceKey ? Date.now() - Number(sinceKey) * DAY_MS : undefined),
    [sinceKey],
  );

  const [detail, setDetail] = useState<{ kind: DetailKind; name: string } | null>(null);

  function setFilter(key: string, value: string, defaultValue = "") {
    const next = new URLSearchParams(params);
    if (value && value !== defaultValue) next.set(key, value);
    else next.delete(key);
    setParams(next);
  }

  function setTab(next: Tab) {
    const copy = new URLSearchParams(params);
    if (next === "overview") copy.delete("tab");
    else copy.set("tab", next);
    setParams(copy);
  }

  function clearAll() {
    setParams(new URLSearchParams());
    setDetail(null);
  }

  const openDetail = (kind: DetailKind, name: string) => setDetail({ kind, name });

  const distinct = useApiData(() => api.distinct());

  const axis = useMemo<StatsParams>(
    () => ({
      source: source || undefined,
      item: item || undefined,
      zone: zone || undefined,
      activity: activity || undefined,
      since: sinceMs,
    }),
    [source, item, zone, activity, sinceMs],
  );

  const rateFilters = useMemo<DropRateParams>(() => ({ ...axis, status }), [axis, status]);

  const stats = useApiData(() => api.stats(axis), [axis]);
  const rates = useApiData(() => api.dropRates(rateFilters), [rateFilters]);
  const summary = useApiData(() => api.summary(axis), [axis]);
  const analysisSources = useApiData(
    () => api.analysisSources({ ...axis, status, limit: 50 }),
    [axis, status],
  );
  const analysisZones = useApiData(
    () => api.analysisZones({ ...axis, status, limit: 50 }),
    [axis, status],
  );
  const analysisItems = useApiData(
    () => api.analysisItems({ ...axis, status, limit: 50 }),
    [axis, status],
  );
  const orphanZones = useApiData(
    () =>
      tab === "overview"
        ? api.analysisZones({ ...axis, status: "Orphaned", limit: 50 })
        : Promise.resolve<ZoneCount[]>([]),
    [axis, tab],
  );

  // Matrix tab: explicit source/item selection drives one targeted query.
  const [matrixSources, setMatrixSources] = useState<string[]>([]);
  const [matrixItems, setMatrixItems] = useState<string[]>([]);
  const matrixDeps = `${matrixSources.join(",")}\u0000${matrixItems.join(",")}`;
  const matrix = useApiData(
    () =>
      matrixSources.length || matrixItems.length
        ? api.dropRates({ ...rateFilters, monsters: matrixSources.join(","), items: matrixItems.join(","), limit: 5000 })
        : Promise.resolve<DropRateRow[]>([]),
    [rateFilters, matrixDeps],
  );

  const detailData = useApiData<DetailData>(() => {
    if (!detail) return Promise.resolve(null);
    if (detail.kind === "source") return api.sourceDetail(detail.name, sinceMs);
    if (detail.kind === "item") return api.itemDetail(detail.name, sinceMs);
    if (detail.kind === "activity") return api.activityDetail(detail.name, sinceMs);
    return api.zoneDetail(detail.name, sinceMs);
  }, [detail?.kind, detail?.name, sinceMs]);

  const hasFilters = Boolean(source || item || zone || activity || sinceMs);

  return (
    <Page
      title="Drop-rate dashboard"
      actions={
        <a
          href={exportAnalysisUrl({
            source: source || undefined,
            item: item || undefined,
            zone: zone || undefined,
            activity: activity || undefined,
            status,
            since: sinceMs ? new Date(sinceMs).toISOString() : undefined,
          })}
          style={linkBtnStyle}
        >
          Export analysis CSV
        </a>
      }
    >
      <Tabs active={tab} onSelect={setTab} />

      <FilterBar
        values={{ source, item, zone, activity, status, sinceKey }}
        onValues={{
          setSource: (v) => setFilter("source", v),
          setItem: (v) => setFilter("item", v),
          setZone: (v) => setFilter("zone", v),
          setActivity: (v) => setFilter("activity", v),
          setStatus: (v) => setFilter("status", v, "Linked"),
          setSinceKey: (v) => setFilter("since", v),
        }}
        distinct={distinct.data}
        onClear={clearAll}
        hasFilters={hasFilters}
      />

      {detail && detailData.data ? (
        <DrillDown
          kind={detail.kind}
          name={detail.name}
          data={detailData.data}
          loading={detailData.loading}
          onClose={() => setDetail(null)}
          onOpen={openDetail}
        />
      ) : null}

      {tab === "overview" && (
        <Overview
          stats={stats.data}
          sources={analysisSources.data}
          zones={analysisZones.data}
          items={analysisItems.data}
          orphanZones={orphanZones.data}
          onOpen={openDetail}
          showOrphans={stats.data?.orphaned !== 0}
        />
      )}
      {tab === "rates" && (
        <Rates rates={rates.data ?? []} summary={summary.data ?? []} onOpen={openDetail} />
      )}
      {tab === "find" && (
        <FindPanel onOpen={openDetail} sinceMs={sinceMs} axis={axis} />
      )}
      {tab === "matrix" && (
        <MatrixPanel
          rows={matrix.data ?? []}
          loading={matrix.loading}
          sources={matrixSources}
          items={matrixItems}
          topSources={(analysisSources.data ?? []).slice(0, 12).map((s) => s.monster)}
          topItems={(analysisItems.data ?? []).slice(0, 12).map((i) => i.item)}
          onSetSources={setMatrixSources}
          onSetItems={setMatrixItems}
          onOpen={openDetail}
        />
      )}
    </Page>
  );
}

function Tabs({ active, onSelect }: { active: Tab; onSelect: (t: Tab) => void }) {
  return (
    <div style={tabsStyle}>
      {TABS.map((t) => (
        <button
          key={t}
          onClick={() => onSelect(t)}
          style={{ ...tabBtnStyle, ...(active === t ? activeTabStyle : {}) }}
        >
          {TAB_LABEL[t]}
        </button>
      ))}
    </div>
  );
}

function FilterBar({
  values,
  onValues,
  distinct,
  onClear,
  hasFilters,
}: {
  values: { source: string; item: string; zone: string; activity: string; status: string; sinceKey: string };
  onValues: {
    setSource: (v: string) => void;
    setItem: (v: string) => void;
    setZone: (v: string) => void;
    setActivity: (v: string) => void;
    setStatus: (v: string) => void;
    setSinceKey: (v: string) => void;
  };
  distinct: { sources: string[]; zones: string[]; items: string[]; activities: string[] } | null;
  onClear: () => void;
  hasFilters: boolean;
}) {
  return (
    <div style={barStyle}>
      <Select label="Source" value={values.source} onChange={onValues.setSource} options={distinct?.sources ?? []} />
      <Select label="Item" value={values.item} onChange={onValues.setItem} options={distinct?.items ?? []} />
      <Select label="Zone" value={values.zone} onChange={onValues.setZone} options={distinct?.zones ?? []} />
      <Select label="Activity" value={values.activity} onChange={onValues.setActivity} options={distinct?.activities ?? []} />
      <Select label="Status" value={values.status} onChange={onValues.setStatus} options={STATUS_OPTIONS} />
      <Select
        label="Time"
        value={values.sinceKey}
        onChange={onValues.setSinceKey}
        options={TIME_OPTIONS.map((t) => t.key)}
        optionLabels={Object.fromEntries(TIME_OPTIONS.map((t) => [t.key, t.label]))}
      />
      {hasFilters && (
        <button onClick={onClear} style={clearStyle}>
          Clear
        </button>
      )}
    </div>
  );
}

function Overview({
  stats,
  sources,
  zones,
  items,
  orphanZones,
  onOpen,
  showOrphans,
}: {
  stats: Stats | null;
  sources: SourceAgg[] | null;
  zones: ZoneCount[] | null;
  items: ItemCount[] | null;
  orphanZones: ZoneCount[] | null;
  onOpen: (kind: DetailKind, name: string) => void;
  showOrphans: boolean;
}) {
  const rateData = useMemo(
    () =>
      (sources ?? [])
        .filter((s) => s.encounters > 0)
        .slice()
        .sort((a, b) => b.encounters - a.encounters)
        .slice(0, 15),
    [sources],
  );
  const recent = useMemo(
    () =>
      (items ?? [])
        .filter((i) => i.last_seen)
        .slice()
        .sort((a, b) => (b.last_seen ?? 0) - (a.last_seen ?? 0))
        .slice(0, 8),
    [items],
  );
  const orphanedTotal = orphanZones?.reduce((sum, z) => sum + z.drops, 0) ?? 0;

  return (
    <div>
      <StatCards stats={stats} />

      {recent.length > 0 && (
        <div style={{ ...panelStyle, marginBottom: "1rem" }}>
          <p style={{ margin: "0 0 0.4rem", fontWeight: 600, fontSize: "0.9rem" }}>Recently found</p>
          <div style={chipRowStyle}>
            {recent.map((i) => (
              <button
                key={i.item}
                style={chipStyle}
                title={`Last seen ${fmtTime(i.last_seen)}`}
                onClick={() => onOpen("item", i.item)}
              >
                {i.item} <Muted>{fmtRel(i.last_seen ?? Date.now())}</Muted>
              </button>
            ))}
          </div>
        </div>
      )}

      <div style={chartGridStyle}>
        <ChartCard title="Top drop-rate sources (by sample size)">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rateData} layout="vertical" margin={{ right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
              <XAxis
                type="number"
                tickFormatter={(v) => `${(Number(v) * 100).toFixed(0)}%`}
                tick={{ fill: "var(--muted)", fontSize: 11 }}
              />
              <YAxis type="category" dataKey="monster" width={130} tick={{ fill: "var(--muted)", fontSize: 11 }} />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="drop_rate" name="Drop rate" fill="var(--accent)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Drop share by zone">
          <ZoneDonut zones={zones ?? []} />
        </ChartCard>

        <ChartCard title="Most-dropped items">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={items ?? []} margin={{ bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="item" tick={{ fill: "var(--muted)", fontSize: 11 }} angle={-35} textAnchor="end" height={70} />
              <YAxis tick={{ fill: "var(--muted)", fontSize: 12 }} />
              <Tooltip content={<ChartTooltip />} />
              <Legend />
              <Bar dataKey="drops" name="Drops" fill="var(--amber)" />
              <Bar dataKey="sources" name="Sources" fill="var(--green)" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {showOrphans && (
        <div style={{ ...panelStyle, marginBottom: "1rem" }}>
          <p style={{ margin: "0 0 0.4rem", fontWeight: 600, fontSize: "0.9rem" }}>
            Unresolved drops
            <Muted> — {orphanedTotal} drops not linked to a killer</Muted>
          </p>
          {orphanZones && orphanZones.length > 0 && (
            <div style={chipRowStyle}>
              {orphanZones.map((z) => (
                <button
                  key={z.zone}
                  style={{ ...chipStyle, borderColor: "var(--amber)" }}
                  title="Open zone drill-down"
                  onClick={() => onOpen("zone", z.zone)}
                >
                  {z.zone} · {z.drops}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <p style={{ color: "var(--muted)", fontSize: "0.8rem" }}>Rates measured at {fmtTime(Date.now())}</p>
    </div>
  );
}

function StatCards({ stats }: { stats: Stats | null }) {
  const cards: Array<{ label: string; value: string | number; tone?: string }> = [
    { label: "Drops", value: stats?.drops ?? "—" },
    { label: "Encounters", value: stats?.encounters ?? "—" },
    { label: "Items discovered", value: stats?.items ?? "—" },
    { label: "Monsters", value: stats?.sources ?? "—" },
    { label: "Zones", value: stats?.zones ?? "—" },
    { label: "Linked", value: stats ? pctOf(stats.linked, stats.drops) : "—", tone: "var(--green)" },
    { label: "Orphaned", value: stats?.orphaned ?? "—", tone: stats && stats.orphaned > 0 ? "var(--amber)" : undefined },
  ];
  return (
    <div style={statGridStyle}>
      {cards.map((c) => (
        <div key={c.label} style={statCardStyle}>
          <div style={{ fontSize: "1.25rem", fontWeight: 700, color: c.tone ?? "var(--text)" }}>{c.value}</div>
          <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function ZoneDonut({ zones }: { zones: ZoneCount[] }) {
  const total = zones.reduce((sum, z) => sum + z.drops, 0);
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <ResponsiveContainer width="100%" height="70%">
        <PieChart>
          <Pie data={zones} dataKey="drops" nameKey="zone" innerRadius={45} outerRadius={80} stroke="none">
            {zones.map((_, i) => (
              <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip content={<ChartTooltip />} />
        </PieChart>
      </ResponsiveContainer>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: "0.2rem 0.6rem", fontSize: "0.75rem" }}>
        {zones.slice(0, 12).map((z, i) => (
          <div key={z.zone} style={{ display: "flex", alignItems: "center", gap: "0.35rem", overflow: "hidden" }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: PIE_COLORS[i % PIE_COLORS.length], flexShrink: 0 }} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{z.zone}</span>
            <Muted>{total ? Math.round((z.drops / total) * 100) : 0}%</Muted>
          </div>
        ))}
      </div>
      {zones.length > 12 && (
        <Muted>+{zones.length - 12} more</Muted>
      )}
    </div>
  );
}

function Rates({
  rates,
  summary,
  onOpen,
}: {
  rates: DropRateRow[];
  summary: SummaryRow[];
  onOpen: (kind: DetailKind, name: string) => void;
}) {
  return (
    <div>
      <h2 style={{ fontSize: "1rem", margin: "0 0 0.5rem" }}>Drop rates by monster and item</h2>
      <DataTable<DropRateRow>
        rows={rates}
        empty="No drop-rate data yet."
        pageSize={25}
        columns={[
          {
            key: "monster",
            header: "Monster",
            render: (r) => <LinkCell kind="source" name={r.monster} onOpen={onOpen}>{r.monster}</LinkCell>,
            sortValue: (r) => r.monster,
          },
          {
            key: "item",
            header: "Item",
            render: (r) => <LinkCell kind="item" name={r.item} onOpen={onOpen}>{r.item}</LinkCell>,
            sortValue: (r) => r.item,
          },
          { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
          { key: "quantity", header: "Qty", render: (r) => String(r.quantity), align: "right", sortValue: (r) => r.quantity },
          { key: "encounters", header: "Encounters", render: (r) => String(r.encounters), align: "right", sortValue: (r) => r.encounters },
          {
            key: "rate",
            header: "Rate",
            render: (r) => (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
                {fmtPct(r.drop_rate)}
                <ConfidenceBadge encounters={r.encounters} />
              </span>
            ),
            align: "right",
            sortValue: (r) => r.drop_rate,
          },
          { key: "last", header: "Last seen", render: (r) => fmtTime(r.last_seen), sortValue: (r) => r.last_seen ?? 0 },
        ]}
      />

      <h2 style={{ fontSize: "1rem", margin: "1.5rem 0 0.5rem" }}>Summary by zone / monster / activity / item</h2>
      <DataTable<SummaryRow>
        rows={summary}
        empty="No summary data yet."
        pageSize={25}
        columns={[
          {
            key: "zone",
            header: "Zone",
            render: (r) => <LinkCell kind="zone" name={r.zone} onOpen={onOpen}>{r.zone}</LinkCell>,
            sortValue: (r) => r.zone,
          },
          {
            key: "monster",
            header: "Monster",
            render: (r) => <LinkCell kind="source" name={r.monster} onOpen={onOpen}>{r.monster}</LinkCell>,
            sortValue: (r) => r.monster,
          },
          {
            key: "activity",
            header: "Activity",
            render: (r) => <LinkCell kind="activity" name={r.activity} onOpen={onOpen}>{r.activity}</LinkCell>,
            sortValue: (r) => r.activity,
          },
          {
            key: "item",
            header: "Item",
            render: (r) => <LinkCell kind="item" name={r.item} onOpen={onOpen}>{r.item}</LinkCell>,
            sortValue: (r) => r.item,
          },
          { key: "count", header: "Drops", render: (r) => String(r.drop_count), align: "right", sortValue: (r) => r.drop_count },
          { key: "qty", header: "Qty", render: (r) => String(r.total_quantity), align: "right", sortValue: (r) => r.total_quantity },
          { key: "last", header: "Last seen", render: (r) => fmtTime(r.last_seen), sortValue: (r) => r.last_seen ?? 0 },
        ]}
      />
    </div>
  );
}

function FindPanel({
  onOpen,
  sinceMs,
  axis,
}: {
  onOpen: (kind: DetailKind, name: string) => void;
  sinceMs?: number;
  axis: StatsParams;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  const search = useApiData(
    () => (debounced ? api.search(debounced, sinceMs) : Promise.resolve(EMPTY_SEARCH)),
    [debounced, sinceMs],
  );

  const flat = useMemo(() => {
    const results = search.data ?? EMPTY_SEARCH;
    return [
      ...results.sources.map((s) => ({ kind: "source" as DetailKind, name: s.name, drops: s.drops, last: s.last_seen })),
      ...results.items.map((s) => ({ kind: "item" as DetailKind, name: s.name, drops: s.drops, last: s.last_seen })),
      ...results.activities.map((s) => ({ kind: "activity" as DetailKind, name: s.name, drops: s.drops, last: s.last_seen })),
    ];
  }, [search.data]);
  const clampedActive = flat.length ? Math.min(active, flat.length - 1) : 0;

  function onKeyDown(e: React.KeyboardEvent) {
    if (!flat.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % flat.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + flat.length) % flat.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      onOpen(flat[clampedActive].kind, flat[clampedActive].name);
    }
  }

  const total = flat.length;

  return (
    <div>
      <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: 0 }}>
        Search sources, items, or activities. Use arrow keys and Enter to jump straight in.
      </p>
      <input
        placeholder="Search source, item, or activity…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
        }}
        onKeyDown={onKeyDown}
        style={{ ...inputStyle, width: "100%", maxWidth: 480, marginBottom: "0.75rem" }}
        aria-label="Search"
        role="combobox"
        aria-expanded={total > 0}
      />

      {search.loading && !total && <p style={{ color: "var(--muted)" }}>Searching…</p>}
      {!search.loading && debounced && total === 0 && <p style={resultNoteStyle}>No matches.</p>}
      {total > 0 && (
        <div style={{ ...panelStyle, marginBottom: "1rem" }}>
          <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>Matches — click or press Enter to drill down</p>
          <div style={resultGridStyle}>
            {search.data!.sources.length > 0 && (
              <div>
                <p style={groupLabel}>Sources</p>
                {search.data!.sources.map((s, i) => (
                  <SearchHit
                    key={"src" + s.name}
                    name={s.name}
                    meta={`${s.drops} drops`}
                    active={flat.findIndex((f) => f.kind === "source" && f.name === s.name) === clampedActive && active === i}
                    onClick={() => onOpen("source", s.name)}
                  />
                ))}
              </div>
            )}
            {search.data!.items.length > 0 && (
              <div>
                <p style={groupLabel}>Items / drops</p>
                {search.data!.items.map((s) => (
                  <SearchHit
                    key={"itm" + s.name}
                    name={s.name}
                    meta={`${s.drops} drops`}
                    active={flat.findIndex((f) => f.kind === "item" && f.name === s.name) === clampedActive}
                    onClick={() => onOpen("item", s.name)}
                  />
                ))}
              </div>
            )}
            {search.data!.activities.length > 0 && (
              <div>
                <p style={groupLabel}>Activities</p>
                {search.data!.activities.map((s) => (
                  <SearchHit
                    key={"act" + s.name}
                    name={s.name}
                    meta={`${s.drops} drops`}
                    active={flat.findIndex((f) => f.kind === "activity" && f.name === s.name) === clampedActive}
                    onClick={() => onOpen("activity", s.name)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {!debounced && (
        <BrowseGrid axis={axis} onOpen={onOpen} />
      )}
    </div>
  );
}

function BrowseGrid({
  axis,
  onOpen,
}: {
  axis: StatsParams;
  onOpen: (kind: DetailKind, name: string) => void;
}) {
  const sources = useApiData(() => api.analysisSources({ ...axis, limit: 30 }), [axis]);
  const items = useApiData(() => api.analysisItems({ ...axis, limit: 30 }), [axis]);
  return (
    <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
      <div style={panelStyle}>
        <p style={groupLabel}>Top sources</p>
        {(sources.data ?? []).map((s) => (
          <div key={s.monster} style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
            <LinkCell kind="source" name={s.monster} onOpen={onOpen}>{s.monster}</LinkCell>
            <Muted>{s.drops} drops</Muted>
          </div>
        ))}
      </div>
      <div style={panelStyle}>
        <p style={groupLabel}>Top items</p>
        {(items.data ?? []).map((i) => (
          <div key={i.item} style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
            <LinkCell kind="item" name={i.item} onOpen={onOpen}>{i.item}</LinkCell>
            <Muted>{i.drops} drops</Muted>
          </div>
        ))}
      </div>
    </div>
  );
}

function SearchHit({
  name,
  meta,
  active,
  onClick,
}: {
  name: string;
  meta: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      style={{ ...resultBtnStyle, ...(active ? activeResultStyle : {}) }}
      onClick={onClick}
    >
      {name} <Muted>({meta})</Muted>
    </button>
  );
}

function MatrixPanel({
  rows,
  loading,
  sources,
  items,
  topSources,
  topItems,
  onSetSources,
  onSetItems,
  onOpen,
}: {
  rows: DropRateRow[];
  loading: boolean;
  sources: string[];
  items: string[];
  topSources: string[];
  topItems: string[];
  onSetSources: (v: string[]) => void;
  onSetItems: (v: string[]) => void;
  onOpen: (kind: DetailKind, name: string) => void;
}) {
  const maxRate = useMemo(() => rows.reduce((m, r) => Math.max(m, r.drop_rate), 0), [rows]);
  const rateBy = useMemo(() => {
    const map = new Map<string, DropRateRow>();
    for (const r of rows) map.set(`${r.monster}\u0000${r.item}`, r);
    return map;
  }, [rows]);

  function toggle(list: string[], value: string, set: (v: string[]) => void) {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  }

  return (
    <div>
      <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: 0 }}>
        Pick monsters (rows) and items (columns) to compare drop rates side by side.
      </p>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
        <PickList
          label={`Monsters (${sources.length})`}
          options={topSources}
          selected={sources}
          onToggle={(v) => toggle(sources, v, onSetSources)}
          onClear={() => onSetSources([])}
          onSetAll={(v) => onSetSources([...v])}
        />
        <PickList
          label={`Items (${items.length})`}
          options={topItems}
          selected={items}
          onToggle={(v) => toggle(items, v, onSetItems)}
          onClear={() => onSetItems([])}
          onSetAll={(v) => onSetItems([...v])}
        />
      </div>
      {sources.length === 0 && items.length === 0 && (
        <p style={resultNoteStyle}>
          Use the quick-picks above: “Top 12” preloads the most-dropped monsters and items.
        </p>
      )}
      {loading && <p style={{ color: "var(--muted)" }}>Loading rates…</p>}

      {rows.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: "0.8rem" }}>
            <thead>
              <tr>
                <th style={heatHeaderStyle} />
                {items.map((col) => (
                  <th key={col} style={heatHeaderStyle}>
                    <button style={heatLinkStyle} onClick={() => onOpen("item", col)} title={col}>
                      {col}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sources.map((src) => (
                <tr key={src}>
                  <th style={{ ...heatHeaderStyle, textAlign: "left", whiteSpace: "nowrap" }}>
                    <button style={heatLinkStyle} onClick={() => onOpen("source", src)} title={src}>
                      {src}
                    </button>
                  </th>
                  {items.map((col) => {
                    const row = rateBy.get(`${src}\u0000${col}`);
                    const intensity = row && maxRate > 0 ? (row.drop_rate / maxRate) * 0.85 : 0;
                    return (
                      <td
                        key={col}
                        style={{
                          ...heatCellStyle,
                          background: row ? `rgba(79, 156, 249, ${intensity})` : "transparent",
                        }}
                        title={
                          row
                            ? `${src} → ${col}: ${fmtPct(row.drop_rate)} (${row.drops} drops / ${row.encounters} encounters)`
                            : `${src} → ${col}: no recorded drops`
                        }
                      >
                        {row ? fmtPct(row.drop_rate) : "—"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PickList({
  label,
  options,
  selected,
  onToggle,
  onClear,
  onSetAll,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (v: string) => void;
  onClear: () => void;
  onSetAll: (v: string[]) => void;
}) {
  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.4rem" }}>
        <span style={{ fontWeight: 600, fontSize: "0.85rem" }}>{label}</span>
        <button style={miniBtnStyle} onClick={() => onSetAll(options)} title="Preload the most-dropped entries">
          Top 12
        </button>
        {selected.length > 0 && (
          <button style={miniBtnStyle} onClick={onClear}>
            Clear
          </button>
        )}
      </div>
      <div style={{ maxHeight: 180, overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.1rem" }}>
        {options.map((o) => (
          <label key={o} style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.8rem" }}>
            <input type="checkbox" checked={selected.includes(o)} onChange={() => onToggle(o)} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{o}</span>
          </label>
        ))}
        {options.length === 0 && <Muted>Nothing to pick yet.</Muted>}
      </div>
    </div>
  );
}

function LinkCell({
  kind,
  name,
  onOpen,
  children,
}: {
  kind: DetailKind;
  name: string;
  onOpen: (kind: DetailKind, name: string) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={() => onOpen(kind, name)}
      style={linkCellStyle}
      title={`Open ${kind} detail`}
    >
      {children}
    </button>
  );
}

function DrillDown({
  kind,
  name,
  data,
  loading,
  onClose,
  onOpen,
}: {
  kind: DetailKind;
  name: string;
  data: DetailData;
  loading: boolean;
  onClose: () => void;
  onOpen: (kind: DetailKind, name: string) => void;
}) {
  return (
    <div style={{ ...panelStyle, marginBottom: "1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem" }}>
        <h2 style={{ fontSize: "1rem", margin: 0 }}>{kindLabel(kind)}: {name}</h2>
        <button onClick={onClose} style={clearStyle}>
          Close
        </button>
      </div>
      {loading && <p style={{ color: "var(--muted)" }}>Loading…</p>}
      {data && <DetailTables kind={kind} data={data} onOpen={onOpen} />}
    </div>
  );
}

function DetailTables({
  kind,
  data,
  onOpen,
}: {
  kind: DetailKind;
  data: NonNullable<DetailData>;
  onOpen: (kind: DetailKind, name: string) => void;
}) {
  const zoneRows =
    kind === "activity"
      ? (data as ActivityDetail).zones
      : kind === "source"
        ? (data as SourceDetail).zones
        : kind === "zone"
          ? null
          : (data as ItemDetail).zones;

  return (
    <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", marginTop: "0.75rem" }}>
      {kind === "source" && (
        <DataTable
          empty="No items."
          rows={(data as SourceDetail).items}
          columns={[
            { key: "item", header: "Item", render: (r: DropRateRow) => <LinkCell kind="item" name={r.item} onOpen={onOpen}>{r.item}</LinkCell> },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
            { key: "enc", header: "Encounters", render: (r) => String(r.encounters), align: "right" },
            { key: "rate", header: "Rate", render: (r) => fmtPct(r.drop_rate), align: "right", sortValue: (r) => r.drop_rate },
          ]}
        />
      )}
      {kind === "item" && (
        <DataTable
          empty="No sources."
          rows={(data as ItemDetail).sources}
          columns={[
            { key: "monster", header: "Source", render: (r: DropRateRow) => <LinkCell kind="source" name={r.monster} onOpen={onOpen}>{r.monster}</LinkCell> },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
            { key: "enc", header: "Encounters", render: (r) => String(r.encounters), align: "right" },
            { key: "rate", header: "Rate", render: (r) => fmtPct(r.drop_rate), align: "right", sortValue: (r) => r.drop_rate },
          ]}
        />
      )}
      {kind === "activity" && (
        <DataTable
          empty="No sources."
          rows={(data as ActivityDetail).sources}
          columns={[
            { key: "monster", header: "Source", render: (r) => <LinkCell kind="source" name={r.monster} onOpen={onOpen}>{r.monster}</LinkCell> },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
            { key: "enc", header: "Encounters", render: (r) => String(r.encounters), align: "right", sortValue: (r) => r.encounters },
          ]}
        />
      )}
      {kind === "zone" && (
        <DataTable
          empty="No sources."
          rows={(data as ZoneDetail).sources}
          columns={[
            { key: "monster", header: "Source", render: (r: DropRateRow) => <LinkCell kind="source" name={r.monster} onOpen={onOpen}>{r.monster}</LinkCell> },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
            { key: "enc", header: "Encounters", render: (r) => String(r.encounters), align: "right", sortValue: (r) => r.encounters },
            { key: "rate", header: "Rate", render: (r) => fmtPct(r.drop_rate), align: "right", sortValue: (r) => r.drop_rate },
          ]}
        />
      )}
      {zoneRows && (
        <DataTable
          empty="No zones."
          rows={zoneRows}
          columns={[
            { key: "zone", header: "Zone", render: (r) => <LinkCell kind="zone" name={r.zone} onOpen={onOpen}>{r.zone}</LinkCell> },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
            { key: "sources", header: "Sources", render: (r) => (r.sources == null ? "—" : String(r.sources)), align: "right" },
          ]}
        />
      )}
      {kind === "activity" && (
        <DataTable
          empty="No items."
          rows={(data as ActivityDetail).items}
          columns={[
            { key: "item", header: "Item", render: (r) => <LinkCell kind="item" name={r.item} onOpen={onOpen}>{r.item}</LinkCell> },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
          ]}
        />
      )}
      {kind === "zone" && (
        <DataTable
          empty="No activities."
          rows={(data as ZoneDetail).activities}
          columns={[
            { key: "activity", header: "Activity", render: (r) => <LinkCell kind="activity" name={r.activity} onOpen={onOpen}>{r.activity}</LinkCell> },
            { key: "drops", header: "Drops", render: (r) => String(r.drops), align: "right", sortValue: (r) => r.drops },
          ]}
        />
      )}
    </div>
  );
}

function ConfidenceBadge({ encounters }: { encounters: number }) {
  if (encounters >= 30) return <Badge tone="green" title={`${encounters} encounters — high confidence`}>High</Badge>;
  if (encounters >= 10) return <Badge tone="blue" title={`${encounters} encounters — moderate confidence`}>Med</Badge>;
  return <Badge tone="amber" title={`${encounters} encounters — small sample, low confidence`}>Low</Badge>;
}

function Badge({ tone, title, children }: { tone: "green" | "amber" | "blue"; title?: string; children: React.ReactNode }) {
  const colors: Record<string, string> = {
    green: "var(--green)",
    amber: "var(--amber)",
    blue: "#6ab0ff",
  };
  return (
    <span
      title={title}
      style={{
        fontSize: "0.7rem",
        lineHeight: 1.2,
        border: `1px solid ${colors[tone]}`,
        color: colors[tone],
        borderRadius: 4,
        padding: "0 0.3rem",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
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

interface TooltipEntry {
  name?: string;
  value?: number | string;
  color?: string;
  payload?: { monster?: string; item?: string; zone?: string; drops?: number; encounters?: number };
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const extra = payload[0].payload;
  return (
    <div style={tooltipStyle}>
      {label != null && String(label) !== "" && (
        <p style={{ margin: "0 0 0.35rem", fontWeight: 600 }}>{label}</p>
      )}
      {extra && extra.monster != null && (
        <p style={{ margin: "0 0 0.25rem", color: "var(--muted)" }}>
          sample: {extra.encounters ?? 0} encounters
        </p>
      )}
      {payload.map((p, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
          {p.color && (
            <span style={{ width: 9, height: 9, borderRadius: 2, background: p.color, flexShrink: 0 }} />
          )}
          <span>{p.name}</span>
          <span style={{ marginLeft: "auto", fontWeight: 600 }}>
            {typeof p.value === "number" && p.name === "Drop rate" ? fmtPct(p.value) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  optionLabels,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  optionLabels?: Record<string, string>;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle} title={label} aria-label={label}>
      <option value="">{label}: {optionLabels?.[""] ?? "all"}</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {optionLabels?.[o] ?? o}
        </option>
      ))}
    </select>
  );
}

function kindLabel(kind: DetailKind): string {
  if (kind === "source") return "Source";
  if (kind === "item") return "Item / drop";
  if (kind === "zone") return "Zone";
  return "Activity";
}

function Muted({ children }: { children: React.ReactNode }) {
  return <span style={{ color: "var(--muted)" }}>{children}</span>;
}

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(2)}%`;
}

function pctOf(part: number, total: number): string {
  if (!total) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

function fmtRel(ms: number): string {
  const diff = Date.now() - ms;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

const tabsStyle: React.CSSProperties = {
  display: "flex",
  gap: "0.35rem",
  flexWrap: "wrap",
  marginBottom: "1rem",
};
const tabBtnStyle: React.CSSProperties = {
  padding: "0.4rem 0.9rem",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "var(--panel)",
  color: "var(--muted)",
  cursor: "pointer",
  fontSize: "0.85rem",
};
const activeTabStyle: React.CSSProperties = {
  color: "var(--accent)",
  borderColor: "var(--accent)",
  background: "rgba(79, 156, 249, 0.12)",
};
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
const linkBtnStyle: React.CSSProperties = {
  border: "1px solid var(--accent)",
  padding: "0.4rem 0.85rem",
  borderRadius: 8,
  color: "var(--accent)",
  fontSize: "0.85rem",
};
const statGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
  gap: "0.6rem",
  marginBottom: "1rem",
};
const statCardStyle: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "0.6rem 0.8rem",
};
const chartGridStyle: React.CSSProperties = {
  display: "grid",
  gap: "1rem",
  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
  marginBottom: "1.5rem",
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
  textTransform: "uppercase",
  letterSpacing: "0.04em",
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
const activeResultStyle: React.CSSProperties = {
  borderColor: "var(--accent)",
  background: "rgba(79, 156, 249, 0.15)",
};
const tooltipStyle: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "0.5rem",
  fontSize: "0.8rem",
  color: "var(--text)",
};
const chipRowStyle: React.CSSProperties = {
  display: "flex",
  gap: "0.4rem",
  flexWrap: "wrap",
};
const chipStyle: React.CSSProperties = {
  padding: "0.3rem 0.6rem",
  borderRadius: 999,
  border: "1px solid var(--border)",
  background: "transparent",
  color: "var(--text)",
  cursor: "pointer",
  fontSize: "0.8rem",
};
const linkCellStyle: React.CSSProperties = {
  border: "none",
  background: "transparent",
  padding: 0,
  color: "var(--accent)",
  cursor: "pointer",
  textAlign: "left",
  font: "inherit",
};
const miniBtnStyle: React.CSSProperties = {
  border: "1px solid var(--border)",
  background: "transparent",
  color: "var(--text)",
  borderRadius: 6,
  padding: "0.15rem 0.45rem",
  cursor: "pointer",
  fontSize: "0.75rem",
};
const heatHeaderStyle: React.CSSProperties = {
  padding: "0.4rem 0.5rem",
  borderBottom: "1px solid var(--border)",
  borderRight: "1px solid var(--border)",
  fontSize: "0.75rem",
  color: "var(--muted)",
};
const heatLinkStyle: React.CSSProperties = {
  border: "none",
  background: "transparent",
  padding: 0,
  color: "var(--accent)",
  cursor: "pointer",
  fontSize: "0.75rem",
  maxWidth: 160,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const heatCellStyle: React.CSSProperties = {
  padding: "0.4rem 0.5rem",
  textAlign: "right",
  borderRight: "1px solid var(--border)",
  borderBottom: "1px solid var(--border)",
  whiteSpace: "nowrap",
  minWidth: 56,
  color: "var(--text)",
};