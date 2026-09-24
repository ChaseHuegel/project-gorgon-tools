export function StatusBadge({ ok, label }: { ok: boolean; label?: string }) {
  const text = label ?? (ok ? "ok" : "down");
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.35rem",
        padding: "0.15rem 0.6rem",
        borderRadius: 999,
        fontSize: "0.8rem",
        border: `1px solid ${ok ? "var(--green)" : "var(--red)"}`,
        color: ok ? "var(--green)" : "var(--red)",
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: ok ? "var(--green)" : "var(--red)",
        }}
      />
      {text}
    </span>
  );
}