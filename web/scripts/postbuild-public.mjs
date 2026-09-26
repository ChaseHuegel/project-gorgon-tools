// Vite names HTML output entries after their source filename. The public SPA
// builds from index.public.html; FastAPI's SPA mount reads index.html, so rename
// the emitted file after each public build.
import { existsSync, renameSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const outDir = join(dirname(fileURLToPath(import.meta.url)), "../..", "src", "gorgon_tracker", "static", "public");
const from = join(outDir, "index.public.html");
const to = join(outDir, "index.html");
if (!existsSync(from)) {
  console.error("expected index.public.html in public build output");
  process.exit(1);
}
renameSync(from, to);
console.log("renamed public entry to index.html");