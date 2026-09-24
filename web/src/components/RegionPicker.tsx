import { useEffect, useRef, useState } from "react";
import { api, type Monitor } from "../api/client";
import { FormField, NumberInput } from "./FormField";

type Sel = { fx1: number; fy1: number; fx2: number; fy2: number } | null;

const REFRESH_MS = 5000;
const clamp01 = (v: number): number => Math.max(0, Math.min(1, v));

function pickScreen(screens: Monitor[], region: number[]): Monitor {
  if (!screens.length) return { left: 0, top: 0, width: 0, height: 0 };
  const cx = region[0] + region[2] / 2;
  const cy = region[1] + region[3] / 2;
  const hit = screens.find(
    (m) => cx >= m.left && cx < m.left + m.width && cy >= m.top && cy < m.top + m.height,
  );
  if (hit) return hit;
  return screens.find((m) => m.left !== 0 || m.top !== 0) ?? screens[0];
}

/**
 * Drag-to-select an OCR region on a full-screen grab of the captured display. The
 * background snapshot refreshes periodically so live changes are visible; the
 * current region and the in-progress drag box are drawn as overlays, and a side
 * crop shows exactly the pixels tesseract will read.
 */
export function RegionPicker({
  screens,
  value,
  onChange,
}: {
  screens: Monitor[];
  value: number[];
  onChange: (region: number[]) => void;
}) {
  const [monitorIdx, setMonitorIdx] = useState(0);
  const [sel, setSel] = useState<Sel>(null);
  const [drag, setDrag] = useState(false);
  const [stamp, setStamp] = useState(() => Date.now());
  const imgRef = useRef<HTMLImageElement>(null);

  const screen = screens[monitorIdx] ?? pickScreen(screens, value);

  useEffect(() => {
    const id = setInterval(() => setStamp(Date.now()), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  // Keep the selected monitor sensible as the list of displays arrives/changes.
  useEffect(() => {
    if (!screens.length) return;
    const active = pickScreen(screens, value);
    const idx = screens.findIndex((m) => m === active);
    setMonitorIdx(idx >= 0 ? idx : 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screens]);

  const bgUrl = api.calibrateSnapshotUrl(
    [screen.left, screen.top, screen.width, screen.height],
    { color: true, t: stamp },
  );
  const cropUrl = value[2] > 0 && value[3] > 0 ? api.calibrateSnapshotUrl(value, { t: stamp }) : "";

  function fracPos(e: React.PointerEvent): { fx: number; fy: number } {
    const rect = imgRef.current!.getBoundingClientRect();
    return {
      fx: (e.clientX - rect.left) / rect.width,
      fy: (e.clientY - rect.top) / rect.height,
    };
  }

  function onStart(e: React.PointerEvent) {
    if (!imgRef.current || !screen.width || !screen.height) return;
    e.preventDefault();
    const p = fracPos(e);
    setDrag(true);
    setSel({ fx1: p.fx, fy1: p.fy, fx2: p.fx, fy2: p.fy });
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }

  function onMove(e: React.PointerEvent) {
    if (!drag || !sel) return;
    const p = fracPos(e);
    setSel({ ...sel, fx2: p.fx, fy2: p.fy });
  }

  function onEnd() {
    if (!drag || !sel) return;
    setDrag(false);
    const fx1 = clamp01(sel.fx1);
    const fx2 = clamp01(sel.fx2);
    const fy1 = clamp01(sel.fy1);
    const fy2 = clamp01(sel.fy2);
    const x0 = Math.min(fx1, fx2);
    const y0 = Math.min(fy1, fy2);
    const x1 = Math.max(fx1, fx2);
    const y1 = Math.max(fy1, fy2);
    let x = Math.round(screen.left + x0 * screen.width);
    let y = Math.round(screen.top + y0 * screen.height);
    const w = Math.max(1, Math.round((x1 - x0) * screen.width));
    const h = Math.max(1, Math.round((y1 - y0) * screen.height));
    x = Math.min(Math.max(x, screen.left), screen.left + screen.width - w);
    y = Math.min(Math.max(y, screen.top), screen.top + screen.height - h);
    const region = [x, y, w, h];
    if (!region.every((v, i) => v === value[i])) onChange(region);
    setSel(null);
  }

  const selStyle = sel
    ? {
        left: `${clamp01(Math.min(sel.fx1, sel.fx2)) * 100}%`,
        top: `${clamp01(Math.min(sel.fy1, sel.fy2)) * 100}%`,
        width: `${Math.abs(sel.fx2 - sel.fx1) * 100}%`,
        height: `${Math.abs(sel.fy2 - sel.fy1) * 100}%`,
      }
    : null;

  const regionStyle = !sel
    ? {
        left: `${clamp01((value[0] - screen.left) / (screen.width || 1)) * 100}%`,
        top: `${clamp01((value[1] - screen.top) / (screen.height || 1)) * 100}%`,
        width: `${Math.max(0, (value[2] / (screen.width || 1))) * 100}%`,
        height: `${Math.max(0, (value[3] / (screen.height || 1))) * 100}%`,
      }
    : null;

  if (!screens.length) {
    return <p style={{ color: "var(--muted)" }}>No displays detected — screen grab unavailable.</p>;
  }

  return (
    <div>
      {screens.length > 1 && (
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.5rem", fontSize: "0.85rem" }}>
          Display
          <select
            value={monitorIdx}
            onChange={(e) => setMonitorIdx(Number(e.target.value))}
            style={{ padding: "0.25rem 0.5rem", borderRadius: 6, border: "1px solid var(--border)", background: "transparent", color: "var(--text)" }}
          >
            {screens.map((m, i) => (
              <option key={i} value={i}>
                {m.width}x{m.height} at ({m.left},{m.top})
              </option>
            ))}
          </select>
        </label>
      )}
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
        <div
          style={{
            position: "relative",
            display: "inline-block",
            maxWidth: "100%",
            overflow: "hidden",
            borderRadius: 6,
          }}
        >
          <img
            ref={imgRef}
            src={bgUrl}
            alt="Screen grab"
            style={{
              display: "block",
              maxWidth: "100%",
              maxHeight: "75vh",
              width: "auto",
              height: "auto",
              border: "1px solid var(--border)",
              borderRadius: 6,
              userSelect: "none",
              cursor: "crosshair",
            }}
            draggable={false}
            onPointerDown={onStart}
            onPointerMove={onMove}
            onPointerUp={onEnd}
            onPointerLeave={onEnd}
          />
          {regionStyle && (
            <div
              style={{
                position: "absolute",
                ...regionStyle,
                border: "2px solid var(--green)",
                boxShadow: "0 0 0 1px rgba(0,0,0,0.5)",
                pointerEvents: "none",
              }}
            />
          )}
          {selStyle && (
            <div
              style={{
                position: "absolute",
                ...selStyle,
                border: "2px solid var(--accent)",
                background: "rgba(79,156,249,0.25)",
                pointerEvents: "none",
              }}
            />
          )}
        </div>
        <div>
          <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: 0 }}>
            What OCR reads from the current region:
          </p>
          {cropUrl ? (
            <img
              src={cropUrl}
              alt="Region crop"
              style={{
                display: "block",
                width: "min(360px, 100%)",
                height: "auto",
                border: "1px solid var(--border)",
                borderRadius: 6,
                imageRendering: "pixelated",
              }}
            />
          ) : (
            <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>Set a non-zero width/height to see the crop.</p>
          )}
        </div>
      </div>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem", alignItems: "end" }}>
        {(["x", "y", "w", "h"] as const).map((k, i) => (
          <FormField key={k} label={k.toUpperCase()}>
            <NumberInput
              style={{ width: 90 }}
              value={value[i]}
              onChange={(e) => {
                const next = [...value];
                next[i] = Number(e.target.value) || 0;
                onChange(next);
              }}
            />
          </FormField>
        ))}
      </div>
    </div>
  );
}