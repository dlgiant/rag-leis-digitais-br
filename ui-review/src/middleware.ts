// Phase 11.1 — Clerk middleware. Gates everything except `/sign-in`
// and `/sign-up`; unauthenticated users get redirected to sign-in.
//
// The Clerk SDK wires session lookup + JWT verification into
// `Astro.locals.auth()` so downstream pages + API routes can use
// `Astro.locals.auth().userId` and `Astro.locals.auth().getToken()`
// without any per-route boilerplate.

import { clerkMiddleware, createRouteMatcher } from "@clerk/astro/server";

// Anything NOT matched by this is public (sign-in / sign-up / Clerk
// callbacks). Everything else requires auth.
const isPublicRoute = createRouteMatcher([
  "/sign-in(.*)",
  "/sign-up(.*)",
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
