import react from "@vitejs/plugin-react";
import { resolve } from "path";
import { defineConfig } from "vite";

// Build profile for the read-only public SPA (served by `gorgon-tracker serve`).
// Shares the source tree with the local UI (web/src) but renders only the
// public pages and bundles into src/gorgon_tracker/static/public.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "../src/gorgon_tracker/static/public"),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, "index.public.html"),
    },
  },
});