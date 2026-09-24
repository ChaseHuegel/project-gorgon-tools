import { useEffect, useState } from "react";

type Status = { db_path: string; daemon: { running: boolean } };

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    fetch("/api/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => undefined);
  }, []);

  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui, sans-serif" }}>
      <h1>gorgon-tracker</h1>
      {status ? (
        <p>
          Serving <code>{status.db_path}</code> · daemon{" "}
          {status.daemon.running ? "running" : "stopped"}
        </p>
      ) : (
        <p>Connecting to API…</p>
      )}
    </main>
  );
}