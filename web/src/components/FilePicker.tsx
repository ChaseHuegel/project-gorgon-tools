import { useRef, useState } from "react";

interface PickOptions {
  accept?: string;
  multiple?: boolean;
  paths?: string[];
}

export function FilePicker({
  accept,
  multiple,
  paths,
  onFiles,
  onPaths,
}: PickOptions & {
  onFiles: (files: File[]) => void;
  onPaths?: (paths: string[]) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [serverPaths, setServerPaths] = useState<string[]>(paths ?? []);

  function bridge(files: FileList | null) {
    if (!files) return;
    onFiles([...files].filter((f) => f.size > 0));
    if (ref.current) ref.current.value = "";
  }

  return (
    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
      <input
        type="file"
        ref={ref}
        multiple={multiple}
        accept={accept}
        style={{ display: "none" }}
        onChange={(e) => bridge(e.target.files)}
      />
      <button
        type="button"
        onClick={() => ref.current?.click()}
        style={btnStyle}
      >
        Choose file{multiple ? "s" : ""}
      </button>
      {onPaths && (
        <span style={{ display: "flex", gap: "0.4rem", flex: "1 1 260px" }}>
          <input
            placeholder="or server path"
            style={inputStyle}
            value={serverPaths.join(" ")}
            onChange={(e) => {
              setServerPaths(e.target.value.split(/\s+/).filter(Boolean));
              onPaths(e.target.value.split(/\s+/).filter(Boolean));
            }}
          />
        </span>
      )}
      {multiple && (
        <span style={{ color: "var(--muted)", fontSize: "0.8rem" }}>server paths may also be added above</span>
      )}
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "0.45rem 0.8rem",
  borderRadius: 6,
  border: "1px solid var(--accent)",
  background: "transparent",
  color: "var(--accent)",
  cursor: "pointer",
};

const inputStyle: React.CSSProperties = {
  flex: 1,
  padding: "0.4rem 0.6rem",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel)",
  color: "var(--text)",
};