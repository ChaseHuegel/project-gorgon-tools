export interface DaemonInfo {
  pid: number | null;
  running: boolean;
  pidfile: string;
}

export interface Status {
  db_path: string;
  config_path: string;
  config_db_path: string;
  sessions_total: number;
  open_session_id: number | null;
  open_session_counts: Record<string, number> | null;
  daemon: DaemonInfo;
  warnings: string[];
}

export interface OcrRegion {
  region: number[];
  interval_s: number;
  heartbeat_s: number | null;
}

export interface Config {
  db: { path: string };
  capture: {
    enabled: boolean;
    tshark_path: string;
    interface: string;
    ports: number[];
    bpf: string;
  };
  chat: {
    log_dir: string;
    tail: boolean;
    poll_interval_s: number;
    tail_from_start: boolean;
  };
  ocr: {
    enabled: boolean;
    tesseract_path: string;
    lang: string;
    zones: OcrRegion;
    targets: OcrRegion;
  };
  correlate: {
    buffer_seconds: number;
    session_timeout: number;
    retroactive_threshold: number;
  };
}

export interface ConfigResponse {
  path: string;
  config: Config;
}

export interface Session {
  id: number;
  uuid: string;
  started_at: number;
  ended_at: number | null;
  platform: string;
}

export interface SummaryRow {
  zone: string;
  monster: string;
  activity: string;
  item: string;
  total_quantity: number;
  drop_count: number;
}

export interface DropRateRow {
  monster: string;
  item: string;
  drops: number;
  quantity: number;
  encounters: number;
  drop_rate: number;
}

export interface LootRow {
  captured_at: number;
  source: string;
  activity: string;
  item: string;
  amount: number;
  zone: string;
  status: string;
  lag_ms: number;
}

export interface PortsDiscover {
  tcp: number[];
  udp: number[];
  bpf: string;
  persisted: boolean;
  found: boolean;
}

export interface ReplayResult {
  inputs: string[];
  drops: number;
  session_id: number;
  parsed_files: number;
  loot_kept: number;
  loot_filtered: number;
}

export interface MigrateResult {
  imported: Array<{ file: string; session_id: number; kind: string; imported: number }>;
}