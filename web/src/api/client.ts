import type {
  ChatTail,
  ConfigResponse,
  DaemonInfo,
  DropRateRow,
  LootRow,
  MigrateResult,
  NamesInfo,
  NamesUpdateResult,
  PortsDiscover,
  ReplayResult,
  Session,
  Status,
  SummaryRow,
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

function query(params: Record<string, string | number | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export const exportUrl = (since?: string): string => `/export${query({ since })}`;

export const streamUrl = (kind: "loot" | "events" | "status", since?: number): string =>
  `/api/stream/${kind}${query({ since })}`;

export const api = {
  status: () => request<Status>("/api/status"),

  config: () => request<ConfigResponse>("/api/config"),
  saveConfig: (updates: Record<string, unknown>) =>
    request<ConfigResponse>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates }),
    }),

  sessions: () => request<Session[]>("/sessions"),
  summary: (params: { monster?: string; zone?: string } = {}) =>
    request<SummaryRow[]>(`/summary${query(params)}`),
  dropRates: (params: { monster?: string; item?: string } = {}) =>
    request<DropRateRow[]>(`/drop-rates${query(params)}`),
  loot: (limit = 300) => request<LootRow[]>(`/loot?limit_rows=${limit}`),

  chatTail: (limit = 500) => request<ChatTail>(`/api/chat/tail${query({ limit })}`),

  daemonStart: () => request<DaemonInfo>("/api/daemon/start", { method: "POST" }),
  daemonStop: () => request<DaemonInfo>("/api/daemon/stop", { method: "POST" }),

  names: () => request<NamesInfo>("/api/names"),
  updateNames: () => request<NamesUpdateResult>("/api/names/update", { method: "POST" }),

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