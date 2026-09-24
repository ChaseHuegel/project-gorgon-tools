interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  align?: "left" | "right";
}

export function DataTable<T>({
  columns,
  rows,
  empty = "No rows.",
}: {
  columns: Column<T>[];
  rows: T[];
  empty?: string;
}) {
  if (rows.length === 0) return <p style={{ color: "var(--muted)" }}>{empty}</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "0.85rem",
          border: "1px solid var(--border)",
        }}
      >
        <thead>
          <tr style={{ background: "var(--panel)" }}>
            {columns.map((c) => (
              <th
                key={c.key}
                style={{
                  textAlign: c.align ?? "left",
                  padding: "0.5rem 0.75rem",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
              {columns.map((c) => (
                <td
                  key={c.key}
                  style={{
                    textAlign: c.align ?? "left",
                    padding: "0.4rem 0.75rem",
                    whiteSpace: "nowrap",
                  }}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function fmtTime(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return new Date(ms).toISOString().slice(0, 19).replace("T", " ");
}