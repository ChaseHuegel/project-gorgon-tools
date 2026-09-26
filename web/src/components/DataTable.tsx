import { Fragment, useState } from "react";

interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  headerRender?: () => React.ReactNode;
  align?: "left" | "right";
  sortValue?: (row: T) => string | number;
}

type SortDir = "asc" | "desc";

export function DataTable<T>({
  columns,
  rows,
  empty = "No rows.",
  detail,
  pageSize,
}: {
  columns: Column<T>[];
  rows: T[];
  empty?: string;
  detail?: (row: T) => React.ReactNode;
  pageSize?: number;
}) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [page, setPage] = useState(1);

  const sorted = useSortedRows(rows, columns, sortKey, sortDir);
  const pageCount = pageSize && pageSize > 0 ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1;
  const current = Math.min(page, pageCount);
  const visible = pageSize && pageSize > 0 ? sorted.slice((current - 1) * pageSize, current * pageSize) : sorted;

  function toggleSort(col: Column<T>) {
    if (!col.sortValue) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col.key);
      setSortDir("asc");
    }
    setPage(1);
  }

  if (rows.length === 0) return <p style={{ color: "var(--muted)" }}>{empty}</p>;
  return (
    <div style={{ overflowX: "auto", minWidth: 0 }}>
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
            {columns.map((c) => {
              const active = sortKey === c.key;
              const canSort = Boolean(c.sortValue);
              return (
                <th
                  key={c.key}
                  style={{
                    textAlign: c.align ?? "left",
                    padding: "0.5rem 0.75rem",
                    borderBottom: "1px solid var(--border)",
                    cursor: canSort ? "pointer" : undefined,
                    userSelect: canSort ? "none" : undefined,
                    color: active ? "var(--accent)" : undefined,
                  }}
                  onClick={canSort ? () => toggleSort(c) : undefined}
                  title={canSort ? "Sort" : undefined}
                >
                  {c.headerRender ? c.headerRender() : c.header}
                  {active && (
                    <span style={{ marginLeft: "0.3rem" }}>{sortDir === "asc" ? "▲" : "▼"}</span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {visible.map((row, i) => (
            <Fragment key={i}>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
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
              {detail?.(row) != null && (
                <tr style={{ borderBottom: "1px solid var(--border)", background: "var(--panel)" }}>
                  <td colSpan={columns.length} style={{ padding: "0.5rem 0.75rem" }}>
                    {detail(row)}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {columns.some((c) => c.sortValue) && (
        <p style={{ color: "var(--muted)", fontSize: "0.75rem", marginTop: "0.35rem" }}>
          Click a column header to sort.
        </p>
      )}
      {pageSize && pageSize > 0 && pageCount > 1 && (
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", marginTop: "0.5rem" }}>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={current <= 1}
            style={pageBtnStyle}
          >
            Prev
          </button>
          <span style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
            Page {current} of {pageCount} · {sorted.length} rows
          </span>
          <button
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            disabled={current >= pageCount}
            style={pageBtnStyle}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

const pageBtnStyle: React.CSSProperties = {
  border: "1px solid var(--border)",
  background: "var(--panel)",
  color: "var(--text)",
  borderRadius: 6,
  padding: "0.25rem 0.6rem",
  cursor: "pointer",
};

function useSortedRows<T>(
  rows: T[],
  columns: Column<T>[],
  sortKey: string | null,
  sortDir: SortDir,
): T[] {
  const col = columns.find((c) => c.key === sortKey);
  if (!col?.sortValue) return rows;
  const val = (r: T) => col.sortValue!(r);
  const sign = sortDir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = val(a);
    const bv = val(b);
    if (av === bv) return 0;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * sign;
    return String(av).localeCompare(String(bv)) * sign;
  });
}

export function fmtTime(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return new Date(ms).toISOString().slice(0, 19).replace("T", " ");
}