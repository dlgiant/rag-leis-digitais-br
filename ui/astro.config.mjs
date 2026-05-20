// @ts-check
import { defineConfig } from "astro/config";
import vercel from "@astrojs/vercel";

// Phase 10b — Astro on Vercel.
// Was Fly+Node SSR; switched to Vercel because the operator already
// has Vercel and prefers it. LGPD residency preserved by pinning the
// serverless function region to `gru1` (São Paulo) via vercel.json.
//
// SSR is required for the /api/ask/stream proxy endpoint that keeps
// the backend API key server-side (never reaches the browser).
export default defineConfig({
  output: "server",
  adapter: vercel({
    // Defaults are fine — SSR via Vercel Serverless Functions (Node
    // runtime). Edge runtime would be faster but doesn't support
    // long-lived ReadableStream proxying as cleanly.
  }),
});
