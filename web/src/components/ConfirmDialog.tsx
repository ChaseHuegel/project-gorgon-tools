import { useEffect } from "react";

export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Confirm",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message?: React.ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const confirmColor = danger ? "var(--red)" : "var(--accent)";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onCancel}
      style={overlayStyle}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={dialogStyle}
      >
        <h2 style={{ margin: "0 0 0.6rem", fontSize: "1rem" }}>{title}</h2>
        {message != null && (
          <div style={{ color: "var(--muted)", fontSize: "0.9rem", marginBottom: "1rem" }}>{message}</div>
        )}
        <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
          <button onClick={onCancel} disabled={busy} style={cancelStyle}>
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            style={{ ...confirmStyle, background: confirmColor, borderColor: confirmColor }}
          >
            {busy ? "…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

const overlayStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 50,
  background: "rgba(0, 0, 0, 0.55)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

const dialogStyle: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 10,
  padding: "1.25rem 1.5rem",
  maxWidth: "28rem",
  width: "90%",
  boxShadow: "0 12px 40px rgba(0, 0, 0, 0.5)",
};

const cancelStyle: React.CSSProperties = {
  padding: "0.45rem 0.9rem",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "transparent",
  color: "var(--text)",
  cursor: "pointer",
};

const confirmStyle: React.CSSProperties = {
  padding: "0.45rem 0.9rem",
  borderRadius: 8,
  border: "1px solid var(--accent)",
  color: "#fff",
  cursor: "pointer",
};