export type FieldProps = {
  label: string;
  hint?: string;
};

export function FormField({
  label,
  hint,
  children,
}: FieldProps & { children: React.ReactNode }) {
  return (
    <label style={{ display: "block", marginBottom: "0.75rem" }}>
      <div style={{ fontSize: "0.8rem", color: "var(--muted)", marginBottom: "0.2rem" }}>{label}</div>
      {children}
      {hint && <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.15rem" }}>{hint}</div>}
    </label>
  );
}

export const fieldStyle: React.CSSProperties = {
  width: "100%",
  padding: "0.45rem 0.6rem",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel)",
  color: "var(--text)",
  fontSize: "0.9rem",
};

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} style={{ ...fieldStyle, ...props.style }} />;
}

export function NumberInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} type="number" style={{ ...fieldStyle, ...props.style }} />;
}