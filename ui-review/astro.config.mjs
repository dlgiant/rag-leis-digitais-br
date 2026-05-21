// @ts-check
import { defineConfig } from "astro/config";
import vercel from "@astrojs/vercel";
import clerk from "@clerk/astro";

// Phase 11.1 — Internal review UI.
//
// Astro 5 + Vercel serverless adapter + Clerk auth.
// Region pinned to gru1 (São Paulo) via vercel.json for LGPD posture
// (matches the existing ui/ public-demo project).
//
// Output: server (SSR). Required because:
//   - The /api/admin/[...path].ts proxy needs server-side execution
//     to attach the Clerk JWT before forwarding to the backend.
//   - Astro.locals.auth() (Clerk SDK) lives on the server.
export default defineConfig({
  output: "server",
  integrations: [clerk()],
  adapter: vercel(),
});
