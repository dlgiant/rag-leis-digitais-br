// Phase 10b + Phase 14.6 — server-side proxy for POST /api/ask/stream.
//
// The browser POSTs here; this handler forwards to the production
// backend's POST /v1/ask/stream with the Clerk session JWT attached
// server-side as a Bearer header. The JWT never reaches the browser
// payload (it's already in the user's Clerk session cookie); the
// proxy just lifts it via Astro.locals.auth().getToken() and forwards.
//
// Required env vars (set as Vercel project env vars):
//   RAG_BACKEND_URL    — defaults to https://rag-leis-digitais-br.fly.dev
//   CLERK_PUBLISHABLE_KEY / CLERK_SECRET_KEY / CLERK_JWT_KEY — Clerk
//                        config; see ui-review/'s vars (same Clerk app)
//
// Phase 14.6 removed DEMO_API_KEY from this proxy. Programmatic
// callers (CI smoke tests, MCP) still hit the backend directly with
// X-API-Key on /v1/ask; this proxy is browser-only and uses Clerk.
//
// The response is streamed back to the browser as text/event-stream
// without re-buffering; the backend's SSE format passes through.

import type { APIRoute } from "astro";

export const prerender = false;

const BACKEND_URL =
  process.env.RAG_BACKEND_URL || "https://rag-leis-digitais-br.fly.dev";

export const POST: APIRoute = async ({ request, locals }) => {
  // Clerk middleware already gates everything; if we got here, the
  // session is valid. Double-check defensively + grab the JWT.
  const auth = locals.auth();
  if (!auth.userId) {
    return new Response(
      JSON.stringify({ error: "not authenticated" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
  }
  const token = await auth.getToken();
  if (!token) {
    return new Response(
      JSON.stringify({ error: "no session token available" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
  }

  // Forward the request body as-is. Per-user rate limiting happens
  // on the backend (60 req/min/JWT) — no extra cap here in v1.
  const body = await request.text();

  // Minimal body validation — reject empty / non-JSON early without
  // burning a backend round-trip.
  try {
    const parsed = JSON.parse(body);
    if (!parsed.query || typeof parsed.query !== "string" || parsed.query.length === 0) {
      return new Response(
        JSON.stringify({ error: "missing or empty 'query' field" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }
    if (parsed.query.length > 2000) {
      return new Response(
        JSON.stringify({ error: "query too long (max 2000 chars)" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }
  } catch {
    return new Response(
      JSON.stringify({ error: "invalid JSON body" }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }

  const backend = await fetch(`${BACKEND_URL}/v1/ask/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
      "Accept": "text/event-stream",
    },
    body,
  });

  if (!backend.ok || !backend.body) {
    // Backend rejected before stream started (401, 429, 500, etc.).
    // Pass through the status + body so the UI can render the error.
    const text = await backend.text().catch(() => "");
    return new Response(text || JSON.stringify({ error: "backend unavailable" }), {
      status: backend.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Stream the backend's SSE response straight through. The
  // ReadableStream is consumed lazily as the browser pulls chunks,
  // so we don't buffer the whole response in this proxy.
  return new Response(backend.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
};
