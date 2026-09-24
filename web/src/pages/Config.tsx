import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Config } from "../api/types";
import { FormField, NumberInput, TextInput } from "../components/FormField";
import { Page } from "../components/Page";
import { useApiData } from "../hooks/useApi";

export default function ConfigPage() {
  const { data, reload } = useApiData(() => api.config());
  const [cfg, setCfg] = useState<Config | null>(null);
  const [orig, setOrig] = useState<Config | null>(null);
  const [path, setPath] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (data && !cfg) {
      setCfg(structuredClone(data.config));
      setOrig(data.config);
      setPath(data.path);
    }
  }, [data, cfg]);

  function set<K extends keyof Config>(section: K, value: Config[K]) {
    setCfg((c) => (c ? { ...c, [section]: value } : c));
  }

  async function save() {
    if (!cfg || !orig) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const res = await api.saveConfig(diff(orig as unknown as Record<string, unknown>, cfg as unknown as Record<string, unknown>));
      setOrig(res.config);
      setPath(res.path);
      setSaved("Saved " + res.path);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!cfg) return <p>Loading config…</p>;

  return (
    <Page
      title="Configuration"
      actions={
        <button onClick={save} disabled={busy} style={saveBtn}>
          {busy ? "Saving…" : "Save changes"}
        </button>
      }
    >
      <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: 0 }}>Editing {path}</p>
      {saved && <p style={{ color: "var(--green)" }}>{saved}</p>}
      {error && <p style={{ color: "var(--red)" }}>{error}</p>}

      <Section title="Database">
        <FormField label="DB path">
          <TextInput value={cfg.db.path} onChange={(e) => set("db", { path: e.target.value })} />
        </FormField>
      </Section>

      <Section title="Capture (packet) ">
        <Toggle label="Enabled" checked={cfg.capture.enabled} onChange={(v) => set("capture", { ...cfg.capture, enabled: v })} />
        <FormField label="tshark path">
          <TextInput value={cfg.capture.tshark_path} onChange={(e) => set("capture", { ...cfg.capture, tshark_path: e.target.value })} />
        </FormField>
        <FormField label="Interface">
          <TextInput value={cfg.capture.interface} onChange={(e) => set("capture", { ...cfg.capture, interface: e.target.value })} />
        </FormField>
        <FormField label="Ports (comma-separated)" hint="Set automagically from 'find-ports' on the Import/Export page.">
          <TextInput value={cfg.capture.ports.join(", ")} onChange={(e) => set("capture", { ...cfg.capture, ports: numList(e.target.value) })} />
        </FormField>
        <FormField label="BPF filter">
          <TextInput value={cfg.capture.bpf} onChange={(e) => set("capture", { ...cfg.capture, bpf: e.target.value })} />
        </FormField>
      </Section>

      <Section title="Chat">
        <Toggle label="Tail chat logs" checked={cfg.chat.tail} onChange={(v) => set("chat", { ...cfg.chat, tail: v })} />
        <FormField label="Log directory">
          <TextInput value={cfg.chat.log_dir} onChange={(e) => set("chat", { ...cfg.chat, log_dir: e.target.value })} />
        </FormField>
        <FormField label="Poll interval (s)">
          <NumberInput value={cfg.chat.poll_interval_s} onChange={(e) => set("chat", { ...cfg.chat, poll_interval_s: num(e.target.value) })} />
        </FormField>
        <Toggle label="Tail from start" checked={cfg.chat.tail_from_start} onChange={(v) => set("chat", { ...cfg.chat, tail_from_start: v })} />
      </Section>

      <Section title="OCR">
        <Toggle label="Enabled" checked={cfg.ocr.enabled} onChange={(v) => set("ocr", { ...cfg.ocr, enabled: v })} />
        <FormField label="Tesseract path">
          <TextInput value={cfg.ocr.tesseract_path} onChange={(e) => set("ocr", { ...cfg.ocr, tesseract_path: e.target.value })} />
        </FormField>
        <FormField label="Language">
          <TextInput value={cfg.ocr.lang} onChange={(e) => set("ocr", { ...cfg.ocr, lang: e.target.value })} />
        </FormField>
        <SubSection label="Zones region (x, y, w, h)" hint="Tune on the Calibrate page.">
          <TextInput value={cfg.ocr.zones.region.join(", ")} onChange={(e) => set("ocr", { ...cfg.ocr, zones: { ...cfg.ocr.zones, region: numList(e.target.value) } })} />
        </SubSection>
        <FormField label="SubSection zones interval (s)">
          <NumberInput value={cfg.ocr.zones.interval_s} onChange={(e) => set("ocr", { ...cfg.ocr, zones: { ...cfg.ocr.zones, interval_s: num(e.target.value) } })} />
        </FormField>
        <SubSection label="Targets region (x, y, w, h)">
          <TextInput value={cfg.ocr.targets.region.join(", ")} onChange={(e) => set("ocr", { ...cfg.ocr, targets: { ...cfg.ocr.targets, region: numList(e.target.value) } })} />
        </SubSection>
        <FormField label="Targets interval (s)">
          <NumberInput value={cfg.ocr.targets.interval_s} onChange={(e) => set("ocr", { ...cfg.ocr, targets: { ...cfg.ocr.targets, interval_s: num(e.target.value) } })} />
        </FormField>
      </Section>

      <Section title="Correlation">
        <FormField label="Buffer (s)">
          <NumberInput value={cfg.correlate.buffer_seconds} onChange={(e) => set("correlate", { ...cfg.correlate, buffer_seconds: num(e.target.value) })} />
        </FormField>
        <FormField label="Session timeout (s)">
          <NumberInput value={cfg.correlate.session_timeout} onChange={(e) => set("correlate", { ...cfg.correlate, session_timeout: num(e.target.value) })} />
        </FormField>
        <FormField label="Retroactive threshold (s)">
          <NumberInput value={cfg.correlate.retroactive_threshold} onChange={(e) => set("correlate", { ...cfg.correlate, retroactive_threshold: num(e.target.value) })} />
        </FormField>
      </Section>

      <button onClick={save} disabled={busy} style={saveBtn}>
        {busy ? "Saving…" : "Save changes"}
      </button>
      <button onClick={reload} style={resetBtn}>
        Reset (reload)
      </button>
    </Page>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset style={sectionStyle}>
      <legend style={{ padding: "0 0.5rem", color: "var(--accent)", fontSize: "0.95rem" }}>{title}</legend>
      {children}
    </fieldset>
  );
}

function SubSection({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ margin: "0.5rem 0 0.75rem 1rem", padding: "0.5rem 0.75rem", border: "1px dashed var(--border)", borderRadius: 6 }}>
      <div style={{ fontSize: "0.8rem", color: "var(--muted)", marginBottom: "0.25rem" }}>{label}</div>
      {children}
      {hint && <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{hint}</div>}
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.6rem", fontSize: "0.9rem" }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function num(v: string): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function numList(v: string): number[] {
  return v.split(",").map(s => Number(s.trim())).filter(Number.isFinite);
}

function diff(
  orig: Record<string, unknown>,
  next: Record<string, unknown>,
  prefix = "",
  out: Record<string, unknown> = {},
): Record<string, unknown> {
  for (const k of Object.keys(next)) {
    const path = prefix ? `${prefix}.${k}` : k;
    const a = orig?.[k];
    const b = next[k];
    const aObj = a != null && typeof a === "object" && !Array.isArray(a);
    const bObj = b != null && typeof b === "object" && !Array.isArray(b);
    if (aObj && bObj) diff(a as Record<string, unknown>, b as Record<string, unknown>, path, out);
    else if (JSON.stringify(a) !== JSON.stringify(b)) out[path] = b;
  }
  return out;
}

const sectionStyle: React.CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "0.75rem 1rem 1rem",
  marginBottom: "1rem",
  background: "var(--panel)",
};

const saveBtn: React.CSSProperties = {
  padding: "0.5rem 1rem",
  borderRadius: 8,
  border: "1px solid var(--green)",
  background: "var(--green)",
  color: "#08110c",
  cursor: "pointer",
  marginRight: "0.5rem",
};

const resetBtn: React.CSSProperties = {
  padding: "0.5rem 1rem",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "transparent",
  color: "var(--muted)",
  cursor: "pointer",
};