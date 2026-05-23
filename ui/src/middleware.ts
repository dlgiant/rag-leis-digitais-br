// Phase 14.6 — Clerk middleware for the public RAG UI (aferida.com.br).
//
// Open registration: anyone can sign up. Auth is required to use the
// RAG (replaces the shared DEMO_API_KEY). Cookie is scoped to
// `.aferida.com.br` via Clerk's satellite-domain config so the lawyer's
// session works on both aferida.com.br and revisa.aferida.com.br.
//
// Mirrors the structure of ui-review/src/middleware.ts: gates
// everything except /sign-in (and Clerk callbacks); unauthenticated
// users get redirected to sign-in with returnBackUrl preserving where
// they wanted to go.
//
// /api/ask/stream uses Astro.locals.auth().getToken() to attach the
// Clerk JWT as a Bearer header on the proxy call to the backend.

import { clerkMiddleware, createRouteMatcher } from "@clerk/astro/server";

const isPublicRoute = createRouteMatcher([
  "/sign-in(.*)",
  "/sign-up(.*)",
  // Phase 10c follow-up — /guia is readable without login so a
  // prospect can decide whether to sign up. The guide itself doesn't
  // call any backend endpoints; pure SSR content.
  "/guia(.*)",
]);

export const onRequest = clerkMiddleware((auth, context) => {
  if (isPublicRoute(context.request)) {
    return;
  }
  const { userId, redirectToSignIn } = auth();
  if (!userId) {
    return redirectToSignIn({ returnBackUrl: context.url.href });
  }
});
