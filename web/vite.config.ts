import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Default backend for the Vite dev proxy. Override with BACKEND if the API is
// served elsewhere, e.g. `BACKEND=http://127.0.0.1:9000 npm run dev`.
const backend = process.env.BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": backend,
      "/health": backend,
      "/sessions": backend,
      "/summary": backend,
      "/drop-rates": backend,
      "/loot": backend,
      "/export": backend,
      "/files": backend,
    },
  },
  build: {
    // Ship the bundle inside the Python package so FastAPI serves it at runtime.
    outDir: "../src/gorgon_tracker/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});