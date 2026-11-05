import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  define: { CESIUM_BASE_URL: JSON.stringify("/cesium/") },
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8000", ws: true } },
  },
});
