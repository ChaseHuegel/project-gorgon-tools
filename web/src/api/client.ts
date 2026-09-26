import type {
  ActivityDetail,
  CatalogInfo,
  CatalogUpdateResult,
  ChatTail,
  ConfigResponse,
  DaemonInfo,
  DistinctValues,
  DropRateRow,
  ItemCount,
  ItemDetail,
  LootOverride,
  LootRow,
  MigrateResult,
  NamesInfo,
  NamesUpdateResult,
  PortsDiscover,
  ReplayResult,
  SearchResults,
  Session,
  SourceAgg,
  SourceDetail,
  Stats,
  Status,
  SummaryRow,
  ZoneCount,
  ZoneDetail,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && body.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function query(params: object): string {
  const parts = Object.entries(params as Record<string, unknown>)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export const exportUrl = (since?: string): string => `/api/export${query({ since })}`;

export const exportAnalysisUrl = (params: ExportAnalysisParams = {}): string =>
  `/api/export/analysis${query(params)}`;

export const streamUrl = (kind: "loot" | "events" | "status", since?: number): string =>
  `/api/stream/${kind}${query({ since })}`;

export interface DropRateParams {
  monster?: string;
  item?: string;
  zone?: string;
  activity?: string;
  status?: string;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
  since?: number;
  until?: number;
  monsters?: string;
  items?: string;
}

export interface AnalysisSourceParams {
  source?: string;
  item?: string;
  zone?: string;
  activity?: string;
  status?: string;
  limit?: number;
  since?: number;
  until?: number;
}

export interface StatsParams {
  source?: string;
  item?: string;
  zone?: string;
  activity?: string;
  since?: number;
  until?: number;
}

export interface ExportAnalysisParams {
  source?: string;
  item?: string;
  zone?: string;
  activity?: string;
  status?: string;
  since?: string;
  until?: string;
  sort?: string;
  order?: "asc" | "desc";
}

export const api = {
  status: () => request<Status>("/api/status"),

  config: () => request<ConfigResponse>("/api/config"),
  saveConfig: (updates: Record<string, unknown>) =>
    request<ConfigResponse>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates }),
    }),

  sessions: () => request<Session[]>("/api/sessions"),
  summary: (
    params: { source?: string; item?: string; zone?: string; activity?: string; since?: number; until?: number } = {},
  ) => request<SummaryRow[]>(`/api/summary${query(params)}`),
  dropRates: (params: DropRateParams = {}) =>
    request<DropRateRow[]>(`/api/drop-rates${query(params)}`),
  loot: (
    limit = 300,
    params: { linkedVia?: string; confidence?: string } = {},
  ) => request<LootRow[]>(`/api/loot?limit_rows=${limit}${query(params)}`),
  overrideLoot: (id: number, payload: LootOverride) =>
    request<LootRow>(`/api/loot/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  revertLoot: (id: number) =>
    request<{ ok: boolean }>(`/api/loot/${id}`, { method: "DELETE" }),
  deleteLootRows: (ids: number[]) =>
    request<{ deleted: number }>("/api/loot/rows/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    }),
  clearData: () => request<{ ok: boolean; cleared: Record<string, number> }>("/api/data/clear", { method: "POST" }),

  distinct: () => request<DistinctValues>("/api/distinct"),
  search: (q: string, since?: number, until?: number) =>
    request<SearchResults>(`/api/search${query({ q, since, until })}`),
  sourceDetail: (name: string, since?: number) =>
    request<SourceDetail>(`/api/source/${encodeURIComponent(name)}${query({ since })}`),
  itemDetail: (name: string, since?: number) =>
    request<ItemDetail>(`/api/item/${encodeURIComponent(name)}${query({ since })}`),
  activityDetail: (name: string, since?: number) =>
    request<ActivityDetail>(`/api/activity/${encodeURIComponent(name)}${query({ since })}`),
  zoneDetail: (name: string, since?: number) =>
    request<ZoneDetail>(`/api/zone/${encodeURIComponent(name)}${query({ since })}`),

  stats: (params: StatsParams = {}) => request<Stats>(`/api/stats${query(params)}`),

  analysisSources: (
    params: AnalysisSourceParams = {},
  ) => request<SourceAgg[]>(`/api/analysis/sources${query(params)}`),
  analysisZones: (
    params: {
      source?: string;
      item?: string;
      activity?: string;
      status?: string;
      limit?: number;
    } = {},
  ) => request<ZoneCount[]>(`/api/analysis/zones${query(params)}`),
  analysisItems: (
    params: {
      source?: string;
      zone?: string;
      activity?: string;
      status?: string;
      limit?: number;
    } = {},
  ) => request<ItemCount[]>(`/api/analysis/items${query(params)}`),

  chatTail: (limit = 500) => request<ChatTail>(`/api/chat/tail${query({ limit })}`),

  daemonStart: () => request<DaemonInfo>("/api/daemon/start", { method: "POST" }),
  daemonStop: () => request<DaemonInfo>("/api/daemon/stop", { method: "POST" }),

  names: () => request<NamesInfo>("/api/names"),
  updateNames: () => request<NamesUpdateResult>("/api/names/update", { method: "POST" }),

  catalog: () => request<CatalogInfo>("/api/catalog"),
  updateCatalog: () => request<CatalogUpdateResult>("/api/catalog/update", { method: "POST" }),

  discoverPorts: (writeConfig = false) =>
    request<PortsDiscover>("/api/ports/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ write_config: writeConfig }),
    }),

  replay: (form: FormData) =>
    request<ReplayResult>("/api/replay", { method: "POST", body: form }),
  migrate: (form: FormData, kind?: string) =>
    request<MigrateResult>("/api/migrate", {
      method: "POST",
      body: buildMigrateForm(form, kind),
    }),

  files: (path: string) => request<FileListing>(`/api/files?path=${encodeURIComponent(path)}`),

  calibrateRegion: (kind: string, region: number[]) =>
    request<ConfigResponse>("/api/calibrate/region", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, region }),
    }),

  calibrateScreens: () => request<{ monitors: Monitor[] }>("/api/calibrate/screens"),

  calibratePreview: (region: number[]) =>
    request<{ text: string; raw: string }>(`/api/calibrate/preview${query({ x: region[0], y: region[1], w: region[2], h: region[3] })}`),

  calibrateSnapshotUrl: (
    region: number[],
    opts: { color?: boolean; t?: number } = {},
  ): string =>
    `/api/calibrate/snapshot${query({
      x: region[0],
      y: region[1],
      w: region[2],
      h: region[3],
      color: opts.color ? 1 : undefined,
      t: opts.t,
    })}`,
};

function buildMigrateForm(base: FormData, kind?: string): FormData {
  const form = new FormData();
  base.forEach((value, key) => form.append(key, value));
  if (kind) form.append("kind", kind);
  return form;
}

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
}
export interface FileListing {
  path: string;
  entries: FileEntry[];
}
export interface Monitor {
  left: number;
  top: number;
  width: number;
  height: number;
}