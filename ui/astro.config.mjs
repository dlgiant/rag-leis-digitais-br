// @ts-check
import { defineConfig } from "astro/config";
import node from "@astrojs/node";

// Phase 10b — Astro with Node SSR adapter. SSR is required for the
// /api/ask/stream proxy endpoint that keeps the backend API key
// server-side (never reaches the browser). Static-only Astro would
// have to bake the key into the JS bundle, which is a leak.
export default defineConfig({
  output: "server",
  adapter: node({ mode: "standalone" }),
  server: {
    host: "0.0.0.0",
    port: 4321,
  },
});
