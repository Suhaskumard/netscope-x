import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Minimal Phase 06 dev config. Proxying to the backend API and any
// production build tuning are added once the real API (Phase 09) and
// frontend pages (Phase 12+) exist.
export default defineConfig({
  plugins: [react()],
});
