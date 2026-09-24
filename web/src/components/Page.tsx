export function Page({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.25rem" }}>{title}</h1>
        {actions}
      </div>
      {children}
    </section>
  );
}