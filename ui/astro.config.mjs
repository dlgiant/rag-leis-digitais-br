// @ts-check
import { defineConfig } from "astro/config";
import vercel from "@astrojs/vercel";
import clerk from "@clerk/astro";

// Phase 10b — Astro on Vercel.
// Phase 14.6 — Clerk auth added (mirrors ui-review/). Same Clerk app
// as revisa.aferida.com.br; aferida.com.br is configured as a satellite
// domain in the Clerk Dashboard so the session cookie is scoped to
// `.aferida.com.br` and signed-in users on one surface stay signed in
// on the other.
//
// SSR is required for:
//   - /api/ask/stream proxy: extracts Clerk JWT from the session +
//     forwards to the backend's /v1/ask/stream as Bearer.
//   - Astro.locals.auth(): Clerk SDK lives on the server.
export default defineConfig({
  output: "server",
  integrations: [clerk()],
  adapter: vercel({
    // Defaults are fine — SSR via Vercel Serverless Functions (Node
    // runtime). Edge runtime would be faster but doesn't support
    // long-lived ReadableStream proxying as cleanly.
  }),
});
