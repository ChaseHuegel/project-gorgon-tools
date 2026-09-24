import { api } from "../api/client";
import type { Session } from "../api/types";
import { DataTable, fmtTime } from "../components/DataTable";
import { Page } from "../components/Page";
import { useApiData } from "../hooks/useApi";

export default function SessionsPage() {
  const { data, error } = useApiData(() => api.sessions());

  return (
    <Page title="Sessions">
      {error && <p style={{ color: "var(--red)" }}>{error}</p>}
      <DataTable<Session>
        rows={data ?? []}
        empty="No sessions yet."
        columns={[
          { key: "id", header: "ID", render: (r) => String(r.id), align: "right" },
          { key: "uuid", header: "UUID", render: (r) => <code>{r.uuid}</code> },
          { key: "started", header: "Started", render: (r) => fmtTime(r.started_at) },
          { key: "ended", header: "Ended", render: (r) => (r.ended_at != null ? fmtTime(r.ended_at) : <StatusOpen />) },
          { key: "platform", header: "Platform", render: (r) => r.platform },
          {
            key: "duration",
            header: "Duration",
            render: (r) =>
              r.ended_at != null
                ? fmtDuration(r.ended_at - r.started_at)
                : "—",
          },
        ]}
      />
    </Page>
  );
}

function StatusOpen() {
  return <span style={{ color: "var(--green)" }}>open</span>;
}

function fmtDuration(ms: number): string {
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h}h ${m}m ${sec}s`;
}