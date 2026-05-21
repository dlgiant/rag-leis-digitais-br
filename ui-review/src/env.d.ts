/// <reference path="../.astro/types.d.ts" />
/// <reference types="astro/client" />

// Phase 11.1 — runtime env vars (set in .env locally + Vercel
// project env in production). All consumed via `process.env.X`
// in server-side code; never via `import.meta.env.X` (which is
// build-time replaced and won't see Vercel runtime env).
interface ImportMetaEnv {
  // Backend URL the proxy forwards to (e.g., https://rag-leis-digitais-br.fly.dev)
  readonly RAG_BACKEND_URL?: string;
  // Clerk publishable key — also exposed to client code via PUBLIC_ prefix
  readonly PUBLIC_CLERK_PUBLISHABLE_KEY?: string;
  // Clerk secret key — server-only
  readonly CLERK_SECRET_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
