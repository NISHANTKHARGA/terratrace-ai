import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// TerraTrace AI — dev server config.
// `/api` is proxied to the FastAPI backend so the app works with relative
// URLs in development. Set VITE_API_BASE to override the backend origin
// (e.g. VITE_API_BASE="" to force the relative proxy, or an absolute URL
// when the backend is deployed elsewhere).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8010",
        changeOrigin: true,
      },
    },
  },
});
