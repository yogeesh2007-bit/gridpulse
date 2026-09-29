import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In production FastAPI serves web/dist on the same origin as the API (one URL).
// In development `npm run dev` serves the app on :5173 and proxies the API + WebSocket to FastAPI on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true, ws: true },
      "/health": "http://localhost:8000",
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 700 },
});
