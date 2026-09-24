import { useRef, useState } from "react";
import { api } from "../api/client";
import { FormField, NumberInput } from "./FormField";

type Sel = { x1: number; y1: number; x2: number; y2: number } | null;

/**
 * Crosshair + drag-to-select a sub-region of an OCR snapshot. The snapshot is the
 * screen region `base`, so a selected box maps back to absolute screen coords.
 */
export function RegionPicker({
  base,
  value,
  onChange,
}: {
  base: number[];
  value: number[];
  onChange: (region: number[]) => void;
}) {
  const [sel, setSel] = useState<Sel>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [drag, setDrag] = useState(false);

  const snapshotUrl = api.calibrateSnapshotUrl(base);
  const [baseX, baseY] = base;

  function screenPos(e: React.PointerEvent): { x: number; y: number } {
    const img = imgRef.current!;
    const rect = img.getBoundingClientRect();
    const fx = (e.clientX - rect.left) / rect.width;
    const fy = (e.clientY - rect.top) / rect.height;
    return { x: baseX + fx * base[2], y: baseY + fy * base[3] };
  }

  function onStart(e: React.PointerEvent) {
    if (!imgRef.current) return;
    e.preventDefault();
    const p = screenPos(e);
    setDrag(true);
    setSel({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }

  function onMove(e: React.PointerEvent) {
    if (!drag || !sel) return;
    const p = screenPos(e);
    setSel({ ...sel, x2: p.x, y2: p.y });
  }

  function onEnd() {
    if (!drag || !sel) return;
    setDrag(false);
    const x = Math.round(Math.min(sel.x1, sel.x2));
    const y = Math.round(Math.min(sel.y1, sel.y2));
    const w = Math.round(Math.abs(sel.x2 - sel.x1));
    const h = Math.round(Math.abs(sel.y2 - sel.y1));
    const region = [x, y, w, h];
    if (!region.every((v, i) => v === value[i])) onChange(region);
    setSel(null);
  }

  return (
    <div>
      <div style={{ position: "relative", display: "inline-block" }}>
        <img
          ref={imgRef}
          src={snapshotUrl}
          alt="Snapshot"
          style={{
            display: "block",
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
        {sel && (
          <div
            style={{
              position: "absolute",
              border: "2px solid var(--accent)",
              background: "rgba(79,156,249,0.25)",
              pointerEvents: "none",
            }}
          />
        )}
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