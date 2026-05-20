# Phase 8.2 — Auth + rate limiting (planning, NOT YET BUILT)

**Date:** 2026-05-20
**Status:** Planning. No code yet; no pre-locked criteria committed yet.
**Predecessors:**
- [Phase 8.1](phase-8-entry-plan.md#81--http-harness-1-session) — FastAPI harness with `POST /v1/ask` + `GET /health` shipped 2026-05-19. Sub-phase 8.2 layers auth + rate limiting ON TOP of the harness.
- [Phase 8 entry plan](phase-8-entry-plan.md) — original 8.2 line-item: "API key auth (header-based, single shared key for v1 — multi-tenant is a Phase 9 problem) + per-key rate limiting (token bucket, configurable cap, default 60 req/min)."

## Why this sub-phase blocks 8.3+

The Phase 8.1 harness is currently an **open relay**: anyone who finds
the URL can hit `POST /v1/ask` for free, consuming our Maritaca +
Voyage budget without authorization. Sub-phase 8.3 (structured
observability) would be measuring traffic that's a mix of legitimate
+ adversarial, and sub-phase 8.4 (load testing) would be running
against an endpoint that has no abuse mitigation. So **8.2 must land
before 8.3 and 8.4**.

The Phase 8 entry plan's exact wording: *"This must happen before
observability gets meaningful; otherwise load tests will be against
an open-relay endpoint."*

## What 8.2 ships

Three concrete deliverables, ordered by dependency:

1. **API key authentication** on every request to `POST /v1/ask`.
   `GET /health` and `GET /openapi.json` stay unauthenticated (readiness
   probes from platform infra; OpenAPI for dev convenience). Missing
   or wrong key returns 401.
2. **Per-key rate limiting** on `POST /v1/ask`. Configurable cap;
   default 60 req/min/key. 61st request in window returns 429 with
   `Retry-After` header and `X-RateLimit-*` response headers.
3. **Tests covering both**, including rate-limit window enforcement.

## Auth design

### Mechanism

| Option | Trade-off |
|---|---|
| **A. Static API key in header `X-API-Key` (Recommended)** | Simplest. Single shared key for v1. Plain HTTP header, no signing. Rotating = process restart with new env var. v1-appropriate per the entry plan. |
| B. JWT (HS256) | More flexible (claims, expiry). Overkill for v1 single-tenant. |
| C. OAuth client_credentials | Production-grade but heavyweight to set up. Defer to Phase 9 multi-tenant work. |

**Choice: A.** The entry plan already committed to header-based shared
key for v1 ("multi-tenant is a Phase 9 problem"). No reason to deviate.

### Key storage + format

- Single key for v1. Multiple keys (key set) makes revocation easier;
  trade-off is config complexity. **Recommendation: support a list of
  valid keys from env var** `RAG_API_KEYS` (comma-separated) — easier
  to rotate (add new, drain old, remove old) without a restart window
  where no key is valid.
- Format: `rag_<32-char-base64url>` — prefix tells anyone reading a log
  what this string is; base64url because it's URL-safe and copy-pasteable.
- Generation: documented as `python -c "import secrets; print('rag_' + secrets.token_urlsafe(24))"`.
- Constant-time comparison via `secrets.compare_digest` against the
  allowed set to prevent timing attacks (overkill for v1 but trivial
  to do right).

### Auth response semantics

- **No `X-API-Key` header** → 401 with `WWW-Authenticate: ApiKey` and
  body `{"detail": "missing API key"}`.
- **Key not in valid set** → 401 with body `{"detail": "invalid API key"}`.
- **Valid key** → pass-through; handler runs normally.
- Distinct 401 vs 403: this is unauthenticated (401), not authorization
  failure (403). Standard HTTP semantics.

### Endpoints exempt from auth

- `GET /health` — readiness probe; platforms (Fly, Railway, k8s) hit
  this without credentials.
- `GET /openapi.json` — dev convenience for now; **revisit when /docs
  comes online** in Phase 8.3 (might want to gate the docs UI behind
  a separate dev-only token).

## Rate-limit design

### Algorithm

| Option | Trade-off |
|---|---|
| **A. In-process token bucket (Recommended)** | Simple; ~30 lines hand-rolled OR `slowapi` (FastAPI-friendly wrapper around `limits`). Works for single-instance hosting (the Phase 8 entry default). Lost on restart — acceptable for v1. |
| B. Redis-backed sliding window | Survives restarts; multi-instance ready. Adds Redis dep + ops surface. **Not needed for single-instance v1.** Defer to Phase 9 if/when horizontal scaling lands. |
| C. Hand-rolled fixed window | Simplest but allows 2× burst at window edges. Token bucket is barely more code with better behavior. |

**Choice: A with `slowapi`.** It's the standard FastAPI rate-limit
library, integrates with `Depends`, automatic 429 + `Retry-After`,
adds `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
headers. Single dependency add to `pyproject.toml` server extra.

### Limit parameters

| Knob | Default | Rationale |
|---|---|---|
| Per-key cap | **60 req/min** | Matches Maritaca's typical per-account ceiling per the Phase 8 entry plan. Conservative enough that legitimate use never hits it. |
| Burst | 60 (= per-min cap) | Token bucket at cap=60 means you can spend all 60 in one burst, then wait a full minute. Reasonable for interactive UX. |
| Window | 60s sliding | Smoother than fixed-window edges. |
| Exempt from limit | `GET /health`, `GET /openapi.json` | Health probes are continuous; not rate-limit-relevant. |

Configurable via env var `RAG_RATE_LIMIT_PER_MINUTE` (default 60).
Setting to 0 disables (for tests, load tests, dev).

### What counts against the limit

- **Every `POST /v1/ask` request, regardless of outcome.** This
  includes:
  - Successful answers (~5s, ~$0.005)
  - OOS refusals via cosine fast-path (~0.3s, $0)
  - Validation errors (422)
  - Pipeline errors (500)
- Rationale: rate limit protects against pathological clients hammering
  the endpoint, regardless of whether each hit hits the LLM. CPU + disk
  I/O still cost the host machine.
- **Auth failures (401) do NOT count.** They're rejected before reaching
  the rate-limited handler. (Means rate limit doesn't double-protect
  against unauthenticated abuse, but that's the auth layer's job.)

### Headers + body

429 response:
```
HTTP/1.1 429 Too Many Requests
Retry-After: 47
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1716170400
Content-Type: application/json

{"detail": "rate limit exceeded: 60 requests/minute"}
```

200 response (rate-limit headers always present on `/v1/ask`):
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 42
X-RateLimit-Reset: 1716170400
```

## Pre-locked criteria (commit when sub-phase starts)

> Phase 8.2 ships iff:
> 1. **Auth**: requests without `X-API-Key` header to `POST /v1/ask`
>    get 401 with `WWW-Authenticate: ApiKey`. Requests with a key
>    not in `RAG_API_KEYS` get 401. Requests with a valid key pass
>    through and produce the same `RAGAnswer` JSON as Phase 8.1.
> 2. **Health stays open**: `GET /health` returns 200 without a key.
> 3. **Rate limit**: with cap=2/min for testability, the 3rd request
>    in 60s returns 429 with `Retry-After` and `X-RateLimit-*` headers.
>    All 200 responses also carry `X-RateLimit-*` headers.
> 4. **No behavioral drift on the happy path**: a successful
>    authenticated, under-cap request produces byte-equivalent
>    `RAGAnswer` JSON to Phase 8.1.
> 5. **Existing 448 tests still pass.**
> 6. **New tests cover**: missing header, invalid key, valid key,
>    rate-limit window enforcement (3 requests at cap=2 → 1×200,
>    1×200, 1×429), health stays open, rate-limit headers on 200.

## Out of scope (explicit non-goals)

- **Multi-tenant accounts / quotas / billing.** Single shared key. Per-
  user accounts are Phase 9 work.
- **OAuth / JWT.** Static key only.
- **Audit logs of auth attempts.** Will be folded into Phase 8.3
  structured logging.
- **DDoS protection at the application layer.** That's CDN/Cloudflare/
  Fly's job. Application rate-limit handles single-key abuse, not
  large-scale floods.
- **IP-based rate limiting fallback.** Per-key only. IP-based becomes
  load-bearing when the key set grows (Phase 9).
- **Auth on `/v1/ask` query telemetry tied to a user.** No "user" yet.
- **Hot-reload of the key set.** Process restart to rotate keys is
  acceptable for v1; the multi-key-list pattern keeps the disruption
  window small.

## Open design questions to resolve at sub-phase start

1. **Should `GET /openapi.json` be gated?** Currently leaning toward
   "open for dev convenience." If the API key surface is sensitive
   (it isn't, for v1 single-tenant), gating the OpenAPI spec hides
   endpoint shape from casual scanners. Lean toward "open" until a
   Phase 9 multi-tenant concern surfaces.

2. **Library: `slowapi` vs hand-rolled token bucket?** `slowapi` adds
   one dependency but ~10 lines of integration code; hand-rolled is
   ~30 lines of well-trodden territory. **Recommendation: `slowapi`**
   — well-maintained, FastAPI-native, comes with the headers for free.
   Switch to hand-rolled only if a maintainability concern surfaces.

3. **Default cap of 60/min — too tight or too loose?** Maritaca's
   ceiling is the lower bound (we can't serve faster than the
   upstream allows). 60/min is the entry plan's recommended starting
   point. Re-tune in Phase 8.4 when load test data is in.

4. **Health probe interval vs rate limit interaction.** Fly's default
   health-check interval is 30s, which would be 2 probes/min. If
   `/health` were rate-limited, that'd consume 2 of the 60 budget per
   minute per key for every replica that monitors. **Solution
   already chosen**: exempt `/health` from rate limit (and from auth).

5. **Should 422 validation errors count against rate limit?** Phase 8
   entry plan didn't specify. The plan above says yes (CPU still
   consumed). Cleaner answer: yes; if a client is sending 60 malformed
   requests/min, they're misbehaving and shouldn't get unlimited
   passes just because they're broken.

## Risk + tradeoff analysis

| Risk | Severity | Mitigation |
|---|---|---|
| Single-process rate limit lost on restart | Low | v1 single-instance; restarts are infrequent. Phase 9 introduces Redis if needed. |
| Static key leaks (logs, screenshots, git) | Medium | Document rotation; multi-key list eases revoke; future: tie to secrets manager (Phase 8.5 deploy work). |
| `RAG_API_KEYS` empty → endpoint locks itself | Low | Refuse to start if env var empty AND we're in production mode. Tests use a fixture key. |
| 60/min too tight for legitimate UI traffic | Medium | Configurable via env. Phase 8.4 load test reveals if this needs adjusting. |
| `slowapi` adds maintenance surface | Low | One dep; widely used; well-maintained. |

## Cost estimate

- **API spend**: $0. No LLM calls; pure middleware work.
- **Wall time**: ½ session (~2-3h) for implementation + tests +
  smoke + plan-doc-to-findings-doc.
- **New deps**: `slowapi >= 0.1.9` added to `server` optional-extra
  (alongside the existing `fastapi`, `uvicorn[standard]`).

## Sequencing within 8.2

1. **Add `slowapi` dep + bump `pyproject.toml`** server extra.
2. **Auth middleware**: dependency `verify_api_key()` that reads
   `X-API-Key` and validates against `RAG_API_KEYS` env-var set.
   Wire into `POST /v1/ask` via `Depends`.
3. **Rate-limit middleware**: configure `slowapi.Limiter` keyed on the
   validated API key (use the key string as the bucket identifier).
   Decorate `POST /v1/ask`. Skip on `/health` and `/openapi.json`.
4. **Tests** (10-12 new):
   - missing header → 401
   - invalid key → 401
   - valid key → 200 + rate-limit headers
   - valid key under cap → all 200
   - over cap → 429 + `Retry-After`
   - `/health` no auth needed → 200
   - `/health` not rate-limited (10 rapid calls → all 200)
5. **Smoke run**: start server with `RAG_API_KEYS=rag_test123
   RAG_RATE_LIMIT_PER_MINUTE=2`; curl variants to confirm 401, 200,
   429.
6. **Findings doc**: `phase-8.2-auth-rate-limit-findings.md` with the
   measured behavior + any surprises.

## What we'll learn that's not in this plan

- Whether `slowapi`'s `X-RateLimit-*` header format matches the
  industry-standard naming (some libs use `X-Rate-Limit-*` or
  `RateLimit-*`). Will validate via smoke test, document the exact
  format the API emits.
- Whether the FastAPI lifespan handles the `RAG_API_KEYS` validation
  cleanly (refuse-to-start if empty) without breaking the test fixtures
  that previously skipped lifespan.
- Whether the `secrets.compare_digest` adds measurable latency at the
  per-request level (probably not — microsecond-scale).

## Cross-references

- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — the parent plan;
  this doc decomposes the original 8.2 line into a full design
- [Phase 8.1 commit (`921f58a`)](../../../commit/921f58a) — the HTTP
  harness this layers onto
- [Phase 8.0.1 findings](phase-8-0-1-sabia-3.1-vs-4-findings.md) —
  cost/latency baseline that the rate-limit cap is partially calibrated
  against
- `rag_leis/server.py` — file we'll be modifying
- `tests/test_server.py` — file we'll be extending
