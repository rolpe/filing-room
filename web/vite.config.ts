import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm --prefix web run dev` on :5173, API proxied to `./fr ui --no-open` on :8787.
// The Python server checks the Host header, so the proxy rewrites it (changeOrigin).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8787", changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: false },
});
