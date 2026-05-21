// Phase 11.1 — Clerk-authenticated proxy to the backend `/v1/admin/*`.
//
// Astro catches `/api/admin/<rest>` and forwards to
// `${RAG_BACKEND_URL}/v1/admin/<rest>` with the Clerk session JWT
// attached. The JWT NEVER reaches the browser — Astro server fetches
// it from Clerk's session via Astro.locals.auth().getToken() then
// adds it as a Bearer header.
//
// Request method, query string, and body all pass through; the
// backend's response status + body stream straight back.

import type { APIRoute } from "astro";

export const prerender = false;

const BACKEND_URL =
  process.env.RAG_BACKEND_URL || "https://rag-leis-digitais-br.fly.dev";

const handler: APIRoute = async ({ params, request, locals }) => {
  // Clerk middleware ensures auth before this handler; double-check
  // defensively in case someone wires the route differently later.
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

  // params.path is what came after /api/admin/. Re-prefix with
  // /v1/admin/ when calling the backend.
  const subpath = (params as { path?: string }).path ?? "";
  const url = new URL(request.url);
  const target = `${BACKEND_URL}/v1/admin/${subpath}${url.search}`;

  // Forward method + body. For GET/HEAD, no body. For others,
  // re-stream the request body to avoid buffering large payloads.
  const init: RequestInit = {
    method: request.method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(request.headers.get("content-type")
        ? { "Content-Type": request.headers.get("content-type") as string }
        : {}),
    },
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  const backendResp = await fetch(target, init);
  // Stream the backend response straight back — same status, same
  // body, only strip per-hop headers (Connection, Transfer-Encoding).
  const headers = new Headers();
  const contentType = backendResp.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);

  return new Response(backendResp.body, {
    status: backendResp.status,
    headers,
  });
};

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const DELETE = handler;
export const PATCH = handler;
