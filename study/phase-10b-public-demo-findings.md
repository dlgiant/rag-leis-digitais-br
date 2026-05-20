# Phase 10b — Public demo (findings)

**Date:** 2026-05-20
**Predecessor:** [Phase 10 entry plan](phase-10-ui-entry-plan.md), [Phase 10.0 streaming endpoint](phase-10.0-streaming-endpoint-findings.md).
**Cost:** ~$10/mo recurring (1 always-warm UI machine $5/mo + 1 always-warm backend machine $5/mo).
**Status:** Phase 10b SHIPPED end-to-end. Demo URL: **https://rag-leis-ui.fly.dev**

Note: Phase 10a (local-only Astro UI) was effectively done IN-LINE with 10b's implementation — built locally first, smoke-tested via `npm run dev`, then deployed as 10b once working. No separate 10a deliverable.

## Pre-locked criteria — result

| # | Criterion | Status |
|---|---|:-:|
| 1 | Public URL serves the chat UI | ✅ https://rag-leis-ui.fly.dev/ — 11.3 KB HTML, < 0.5s GET |
| 2 | Demo key is rate-limited tighter than operator key | ⚠️ shipped at backend's default 60 req/min (no UI-side per-IP cap in v1); demo key is in the backend allowlist with same per-key limit. Tighter limit deferred to Phase 11+ since v1 traffic is low. |
| 3 | Privacy notice visible above the input field | ✅ rendered above the form: "Demo: consultas processadas mas não associadas a contas; não envie dados pessoais reais; verifique cada citação." |
| 4 | No persistent session storage | ✅ no cookies, no DB; Astro `@astrojs/node` defaults to in-memory session store; UI doesn't use sessions at all. Every page refresh = fresh state. |
| 5 | No PII retention beyond Phase 4.2's audit log path | ✅ UI logs nothing locally; backend's Phase 4.2 PII-redaction + audit log path unchanged. |

## What ships

- **`ui/` directory** with Astro 5 + Node SSR adapter:
  - `ui/src/pages/index.astro` — single chat page, vanilla JS, Brazilian Portuguese
  - `ui/src/pages/api/ask/stream.ts` — server-side proxy POST /api/ask/stream → backend /v1/ask/stream
  - `ui/src/layouts/Layout.astro` — base layout with CSS reset, dark-mode-aware variables
  - `ui/astro.config.mjs` — `output: "server"`, `adapter: node({ mode: "standalone" })`
  - `ui/Dockerfile` — two-stage build, node:20-slim runtime, 99 MB final image
  - `ui/fly.toml` — separate Fly app `rag-leis-ui`, region `gru`, **`min_machines_running = 1`** (always one warm machine), 512 MB RAM
- **New demo API key** (`rag_demo_*`): added to backend's `RAG_API_KEYS` allowlist; set as `DEMO_API_KEY` on the UI app. The browser **never** sees this key — the Astro server-side proxy holds it.
- **Backend `fly.toml` update**: `min_machines_running` raised from 0 → 1 to eliminate the cold-start UX surprise. UI is no good if the backend underneath is asleep.

## The UI architecture

```
Browser (POST /api/ask/stream)
  │
  ↓ same-origin, no API key visible
Astro Node SSR (ui/src/pages/api/ask/stream.ts)
  │ inserts X-API-Key: DEMO_API_KEY header
  ↓
Backend (POST /v1/ask/stream) at rag-leis-digitais-br.fly.dev
  │ Phase 10.0 SSE stream
  ↓
Astro Node SSR passes ReadableStream through (no buffering)
  │
  ↓
Browser EventSource-equivalent (fetch + ReadableStream + TextDecoder)
  │ JS parses `data: <json>\n\n` frames
  ↓
DOM updates incrementally (stage progress + final answer + citations)
```

Same-origin from the browser's perspective → no CORS configuration needed. The proxy validates body shape (query exists, non-empty, ≤ 2000 chars) before forwarding to avoid burning backend round-trips on garbage requests.

## UI features

- **Single page** — input box (textarea, 2000 char max), send button, character counter
- **Stage progress indicator** — five-step list showing pipeline stages (classify, retrieve, generate, verify, relevance_judge). Each stage shows ○ pending → ◐ running → ● done as events arrive
- **Streaming-aware answer area** — appears once events arrive; shows elapsed time
- **Citations** — rendered as clickable links to LexML URN resolver (`https://www.lexml.gov.br/urn/<urn>`)
- **Refusal handling** — when `refused=true`, shows a sympathetic Portuguese message based on refusal reason (cosine fast-path, llm-self-refusal, empty-citations, irrelevant-citations) instead of a generic error
- **Example queries** — collapsible `<details>` block with 4 pre-canned queries the user can click to fill the input
- **Privacy notice** — visible above the form with explicit "demo" framing and "don't send real personal data" warning
- **Mobile-responsive** — max-width 760px, padding scales, textarea is resizable
- **Dark mode** — auto-detected via `prefers-color-scheme`
- **No tracking** — `noindex, nofollow` meta tag, no analytics, no third-party fonts, no cookies

## Smoke test results

**GET / (HTML page)** — 11,336 bytes, HTTP 200, 0.535s total.

**POST /api/ask/stream** — proxy → backend, first request (backend was cold-starting due to backend's then-`min_machines_running=0`):

```
[19.7s] stage  started: classify        ← backend cold-start surcharge
[19.7s] stage finished: classify
[19.7s] stage  started: retrieve
[20.1s] stage finished: retrieve
[21.6s] stage  started: generate
[28.5s] stage finished: generate        ← Sabiá call ~7s
[28.5s] stage  started: verify
[28.5s] stage finished: verify
[28.5s] stage  started: relevance_judge
[33.4s] stage finished: relevance_judge ← Sabiá call ~5s
[33.4s] COMPLETE refused=False n_cites=4 cost=$0.005705
        first citation: urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1
```

After this smoke test, the backend's `min_machines_running` was raised
to 1, so future first-of-day requests will skip the 19s surcharge.
Subsequent warm-state requests stream the first event in ~0.3s (as
measured in Phase 10.0).

## The DEMO_API_KEY runtime env bug (and the fix)

First deploy returned `HTTP 500: DEMO_API_KEY not configured`. Root cause:

```ts
// BROKEN — build-time replaced; runtime Fly secrets don't reach this
const demoKey = import.meta.env.DEMO_API_KEY;

// FIXED — reads the env var at request time
const demoKey = process.env.DEMO_API_KEY;
```

Astro's `import.meta.env.X` is **Vite-style build-time replacement**.
At build time inside the Docker image, `DEMO_API_KEY` isn't set (we
don't bake secrets into images), so the replacement becomes
`undefined`. Runtime env vars from Fly's `flyctl secrets set` are
only visible via `process.env`.

Same rule applies to `RAG_BACKEND_URL` — moved to `process.env` for
consistency, even though it's set via `[env]` in fly.toml (which
becomes process.env at container start either way).

This is a load-bearing Astro footgun: anything that depends on
runtime-injected env vars (Fly secrets, K8s ConfigMap, Docker
runtime env) needs `process.env`. `import.meta.env` is only safe
for build-time constants.

## What 10b does NOT do (deferred to Phase 10b.1 or later)

- **Per-IP rate limiting in the UI proxy.** Backend already enforces
  per-key cap; demo key is the only key used by anonymous traffic.
  v1 ships without per-IP caps; if abuse appears, add via Fly's
  built-in rate-limit middleware or a small Astro middleware.
- **CI-based deploy for the UI app.** Backend has
  `.github/workflows/deploy.yml`. UI doesn't have one yet because
  the existing `FLY_API_TOKEN` is app-scoped to the backend.
  Adding one needs a new app-scoped deploy token via
  `flyctl tokens create deploy --app rag-leis-ui` + a new GHA
  secret `FLY_API_TOKEN_UI`. Phase 10b.1.
- **Conversation history.** Single-turn only.
- **Streaming of generated text token-by-token within `generate`.**
  Phase 10.0.1 follow-up (separate from 10b).
- **A11y deep audit.** Basic keyboard nav + ARIA labels in place;
  full WCAG-AA audit is Phase 11+.

## Three findings worth recording for Phase 11+

1. **Astro 5's `import.meta.env` vs `process.env` is a footgun.**
   First deploy returned a 500 because of this. Astro docs do
   mention it but it's easy to miss when copying patterns from
   client-side Astro code. **For any v1 SSR app on Astro, use
   `process.env` for ALL runtime env reads.** Save `import.meta.env`
   for build-time constants only.

2. **A warm UI doesn't help if the backend is cold.** Phase 10b's
   UI app had `min_machines_running = 1` from day one. Backend had
   `min_machines_running = 0`. The first SSE request still ate 19s
   because the BACKEND woke up, not the UI. Phase 10b's smoke test
   surfaced this → backend updated to `=1` too.

   General rule: in a multi-app deploy, the warm-machine policy
   needs to be consistent end-to-end. The user-facing latency is
   the WORST of all the apps' cold-start times.

3. **The Phase 10.0 stage events give the UI real progressive
   content, but `generate` (~7s blank) and `relevance_judge`
   (~5s blank) are still the load-bearing UX gaps.** The progress
   indicator helps ("Generating answer..." with a clear icon) but
   doesn't solve the staring-at-spinner UX. **Phase 10.0.1
   (token-by-token within generate) would shrink the worst single
   gap by ~half.** If 10b ever sees real-user feedback, that's the
   first thing they'll ask for.

## Cost analysis

| Resource | Per Month |
|---|---:|
| `rag-leis-digitais-br` (backend) — 1 × shared-cpu-1x × 2GB always warm | ~$5 |
| `rag-leis-digitais-br` (backend) — second machine, auto-stopped | ~$1 (occasional minutes) |
| `rag-leis-ui` (UI) — 1 × shared-cpu-1x × 512 MB always warm | ~$3 |
| `rag-leis-ui` (UI) — second machine, auto-stopped | ~$0.50 |
| Fly egress (low traffic) | ~$0 |
| Sabiá API (per query × ~50 queries/day demo cap) | ~$7.50 |
| Voyage API (per query) | ~$2 |
| **Total approx** | **~$19/mo** |

These numbers are estimates; first month of real traffic will
calibrate. Phase 8.6's provider hard caps protect against runaway.

## What changed in the codebase

- **`ui/` directory** (new, ~25 files):
  - `package.json`, `package-lock.json`, `tsconfig.json`, `astro.config.mjs`
  - `Dockerfile`, `fly.toml`
  - `src/layouts/Layout.astro`
  - `src/pages/index.astro`
  - `src/pages/api/ask/stream.ts`
  - `public/favicon.svg`
  - `.gitignore`
- **`fly.toml`** (backend): `min_machines_running` 0 → 1
- **`.env`**: `DEMO_API_KEY` added (gitignored)
- **Backend `RAG_API_KEYS` (on Fly)**: operator key + demo key allowlist

## Cross-references

- [`phase-10-ui-entry-plan.md`](phase-10-ui-entry-plan.md) — parent plan
- [`phase-10.0-streaming-endpoint-findings.md`](phase-10.0-streaming-endpoint-findings.md) — backend SSE the UI consumes; predicted the `min_machines_running` issue
- `ui/` — the new UI subproject
- `fly.toml` — backend now keeps 1 machine warm
