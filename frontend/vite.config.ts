import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the REST API to a locally running backend (uvicorn backend.app.main:app), so the browser stays
// same-origin and the backend needs no CORS configuration. Override the target with NETSCOPE_API_TARGET.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": process.env.NETSCOPE_API_TARGET ?? "http://127.0.0.1:8000",
    },
  },
});
