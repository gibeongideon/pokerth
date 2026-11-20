import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API is reached under /api on the app's own origin, so cookies work the
// same in dev (this proxy) and production (Caddy). Run the API with
// PLATFORM_COOKIE_PATH_PREFIX=/api so the refresh cookie path matches.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: { target: "es2020", sourcemap: true },
});
