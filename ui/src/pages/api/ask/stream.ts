// Phase 10b — server-side proxy for POST /api/ask/stream.
//
// The browser POSTs here; this handler forwards to the production
// backend's POST /v1/ask/stream with the demo API key attached
// server-side. The key NEVER reaches the browser. Same-origin from
// the browser's perspective, so no CORS configuration needed.
//
// Required env vars (set as Fly secrets on the UI app):
//   RAG_BACKEND_URL    — defaults to https://rag-leis-digitais-br.fly.dev
//   DEMO_API_KEY       — the demo-only X-API-Key (must also be in
//                        the backend's RAG_API_KEYS env var)
//
// The response is streamed back to the browser as text/event-stream
// without re-buffering; the backend's SSE format passes through.

import type { APIRoute } from "astro";

export const prerender = false;

// IMPORTANT: use process.env for runtime env vars on the server.
// import.meta.env.* is build-time replaced — Fly secrets injected
// at container start don't reach it.
const BACKEND_URL =
  process.env.RAG_BACKEND_URL || "https://rag-leis-digitais-br.fly.dev";

export const POST: APIRoute = async ({ request }) => {
  const demoKey = process.env.DEMO_API_KEY;
  if (!demoKey) {
    return new Response(
      JSON.stringify({ error: "DEMO_API_KEY not configured on UI server" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }

  // Forward the request body as-is. We DON'T add per-IP rate limiting
  // here in v1 — the backend already enforces per-key cap, and the
  // demo key is intentionally tightly capped (see findings doc).
  const body = await request.text();

  // Validate body shape minimally — reject empty / non-JSON early
  // without burning a backend round-trip.
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
      "X-API-Key": demoKey,
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
