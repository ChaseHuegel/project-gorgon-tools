import { useEffect, useState } from "react";
import { api, type Monitor } from "../api/client";
import type { Config } from "../api/types";
import { Page } from "../components/Page";
import { RegionPicker } from "../components/RegionPicker";
import { useApiData } from "../hooks/useApi";

export default function CalibratePage() {
  const { data: cfgResp, reload } = useApiData(() => api.config());
  const cfg = cfgResp?.config as Config | undefined;
  const cfgPath = cfgResp?.path ?? "";

  const [kind, setKind] = useState<"zones" | "targets">("zones");
  const [region, setRegion] = useState<number[]>([0, 0, 320, 120]);
  const [screens, setScreens] = useState<Monitor[]>([]);
  const [preview, setPreview] = useState<{ text: string; raw: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  useEffect(() => {
    if (cfg) setRegion([...cfg.ocr[kind].region]);
  }, [cfg, kind]);

  useEffect(() => {
    api
      .calibrateScreens()
      .then((res) => setScreens(res.monitors))
      .catch(() => setScreens([]));
  }, []);

  async function previewOcr() {
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.calibratePreview(region);
      setPreview(res);
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : String(e), ok: false });
    } finally {
      setBusy(false);
    }
  }

  async function saveRegion() {
    setBusy(true);
    setMsg(null);
    try {
      await api.calibrateRegion(kind, region);
      setMsg({ text: `Saved ${kind} region to ${cfgPath}`, ok: true });
      reload();
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : String(e), ok: false });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page title="Calibrate OCR regions">
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        {(["zones", "targets"] as const).map((k) => (
          <label key={k} style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <input type="radio" checked={kind === k} onChange={() => setKind(k)} />
            {k}
          </label>
        ))}
      </div>

      {!cfg ? (
        <p>Loading config…</p>
      ) : (
        <div>
          <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
            The full screen is shown as a background; drag on it to mark the region OCR reads for{" "}
            <strong>{kind}</strong>. A green box shows the current region (X/Y/W/H), and the crop on the right is
            exactly what those coordinates grab. Use the fields to fine-tune, then preview OCR and save.
          </p>
          <RegionPicker screens={screens} value={region} onChange={setRegion} />
          <div style={{ margin: "0.75rem 0", display: "flex", gap: "0.5rem" }}>
            <button onClick={previewOcr} disabled={busy} style={btnStyle}>{busy ? "…" : "Preview OCR"}</button>
            <button onClick={saveRegion} disabled={busy} style={saveBtn}>Save region</button>
          </div>
          {preview !== null && (
            <div style={{ color: "var(--green)" }}>
              <p style={{ margin: "0 0 0.25rem" }}>OCR: {preview.text || "(empty)"}</p>
              <p style={{ margin: 0, color: "var(--muted)", fontSize: "0.85rem", wordBreak: "break-word" }}>
                Raw: {preview.raw || "(empty)"}
              </p>
            </div>
          )}
          {msg && <p style={{ color: msg.ok ? "var(--green)" : "var(--red)" }}>{msg.text}</p>}
        </div>
      )}
    </Page>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "0.5rem 1rem",
  borderRadius: 8,
  border: "1px solid var(--accent)",
  background: "transparent",
  color: "var(--accent)",
  cursor: "pointer",
};

const saveBtn: React.CSSProperties = { ...btnStyle, borderColor: "var(--green)", color: "var(--green)" };