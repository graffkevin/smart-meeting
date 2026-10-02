import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies the API (HTTP + WebSocket) to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", ws: true },
    },
  },
});
