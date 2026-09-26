import type { LootRow } from "../api/types";

export function Badge({ tone, children }: { tone: "green" | "amber" | "blue"; children: React.ReactNode }) {
  const colors: Record<string, string> = {
    green: "var(--green)",
    amber: "var(--amber)",
    blue: "#6ab0ff",
  };
  return (
    <span
      style={{
        fontSize: "0.75em",
        border: `1px solid ${colors[tone]}`,
        color: colors[tone],
        borderRadius: 4,
        padding: "0 0.35rem",
      }}
    >
      {children}
    </span>
  );
}

export function LinkBadge({ row }: { row: LootRow }) {
  if (row.linked_via === "monster") {
    return <Badge tone="green">monster</Badge>;
  }
  if (row.linked_via === "target") {
    return <Badge tone={row.corroborated_by_search ? "blue" : "amber"}>target</Badge>;
  }
  return <Badge tone="amber">orphan</Badge>;
}

export function Evidence({ row }: { row: LootRow }) {
  const bits: string[] = [];
  if (row.monster_name && row.monster_name !== row.source) {
    bits.push(`monster "${row.monster_name}"${row.monster_lag_ms != null ? ` -${row.monster_lag_ms}ms` : ""}`);
  } else if (row.monster_lag_ms != null && row.linked_via === "monster") {
    bits.push(`search -${row.monster_lag_ms}ms`);
  }
  if (row.target_name && row.target_name !== row.source) {
    bits.push(`target "${row.target_name}"${row.target_lag_ms != null ? ` -${row.target_lag_ms}ms` : ""}`);
  }
  if (row.linked_via === "target" && row.corroborated_by_search) {
    bits.push("corroborated by corpse search");
  }
  if (!bits.length) return <span style={{ color: "var(--muted)" }}>—</span>;
  return (
    <span style={{ fontSize: "0.85em", color: "var(--muted)" }} title={row.note ?? undefined}>
      {bits.join("; ")}
    </span>
  );
}