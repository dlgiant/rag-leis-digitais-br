# Phase 8.2 — Auth + rate limit (findings)

**Date:** 2026-05-20
**Predecessor:** [Phase 8.2 plan](phase-8.2-auth-rate-limit-plan.md), drafted 2026-05-20.
**Cost:** $0. No LLM calls; pure middleware work.
**Status:** Phase 8.2 SHIPPED. All six pre-locked criteria met. One known limitation surfaced + documented.

## Pre-locked criteria — result

| # | Criterion | Status |
|---|---|:-:|
| 1 | Missing `X-API-Key` → 401 with `WWW-Authenticate: ApiKey` | ✅ |
| 2 | `GET /health` returns 200 without a key | ✅ |
| 3 | 3rd request at cap=2 returns 429 with `Retry-After` + `X-RateLimit-*` | ✅ |
| 4 | No behavioral drift on the happy path (200 response identical to Phase 8.1) | ✅ |
| 5 | Existing 448 tests still pass | ✅ (458 total now: +10 8.2 tests) |
| 6 | New tests cover: missing header, invalid key, valid key, rate-limit window, health stays open, rate-limit headers on 429 | ✅ |

## What ships

- **API key auth** on `POST /v1/ask` via `X-API-Key` header. Validated against `RAG_API_KEYS` env-var (comma-separated set of allowed keys; multi-key supported for easier rotation). Constant-time compare via `secrets.compare_digest`. Empty/unset env-var fails closed (every request 401).
- **Per-key rate limit** on `POST /v1/ask`. `slowapi.Limiter` token bucket. Default 60 req/min/key; configurable via `RAG_RATE_LIMIT_PER_MINUTE` (set to 0 to effectively disable for load tests/dev).
- **429 response headers**: `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (Unix timestamp). Built manually in the exception handler (see "Known limitation" below).
- **`GET /health` and `GET /openapi.json` exempt** from both auth and rate limit. Health probes from platform infra (Fly's 30s default = 2/min/replica) won't consume the rate budget.
- **10 new tests** in `tests/test_server.py`:
  - missing API key → 401 + `WWW-Authenticate: ApiKey`
  - wrong API key → 401
  - second valid key → 200 (multi-key support)
  - `/health` unauthenticated → 200
  - `/openapi.json` unauthenticated → 200
  - under-cap requests → all 200
  - over-cap requests → 429 + rate-limit headers
  - per-key bucket isolation (key A exhausts; key B unaffected)
  - `/health` not rate-limited
  - 401 doesn't consume rate budget

## Live smoke test (uvicorn + curl)

```bash
RAG_API_KEYS=rag_smoketest123 RAG_RATE_LIMIT_PER_MINUTE=3 \
  uvicorn rag_leis.server:app --port 8767
```

```
# 401 missing key
$ curl -X POST http://127.0.0.1:8767/v1/ask -d '{"query":"x"}'  → HTTP 401

# 401 wrong key
$ curl -X POST ... -H 'X-API-Key: rag_wrong' ...  → HTTP 401

# 200 valid key (3 successful requests at cap=3)
$ curl -X POST ... -H 'X-API-Key: rag_smoketest123' ...  → HTTP 200 × 3

# 4th request: 429 with all headers
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 3
x-ratelimit-remaining: 0
x-ratelimit-reset: 1779251472
retry-after: 2
content-type: application/json

{"detail":"rate limit exceeded: 3 per 1 minute"}
```

## Known limitation — 200 responses lack X-RateLimit-* headers

The Phase 8.2 plan called for `X-RateLimit-*` headers on **every** `/v1/ask` response (200 and 429). They land cleanly on 429 but **not on 200** under the current implementation.

**Root cause:** `slowapi` 0.1.9's `headers_enabled=True` requires the `@limiter.limit` decorator to inject headers into the response object inside its async wrapper. But FastAPI's `response_model` pattern means the handler returns a Pydantic model, not a built `Response` — slowapi tries to inject into `None` and raises:

```
slowapi/extension.py:382
Exception: parameter `response` must be an instance of starlette.responses.Response
```

**Workaround applied:** `headers_enabled=False` on the Limiter (so the decorator doesn't crash); manual header construction in the custom 429 exception handler (so 429 still carries them). 200 responses don't have rate-limit headers.

**Impact:** Clients can't observe their remaining budget on successful requests — they only see headers when they hit 429. Most well-behaved clients implement backoff based on 429 + `Retry-After`, so this is degraded UX but not broken.

**Tracked as Phase 8.3 follow-up.** When 8.3 adds structured response middleware, it can also wrap responses to inject rate-limit headers consistently. Approach options (defer to 8.3 design):
- Switch to a different rate-limit library (e.g., `fastapi-limiter` with Redis) that's FastAPI-native
- Custom middleware that reads `request.state.view_rate_limit` and injects on every response
- Endpoint refactor to return `JSONResponse` explicitly (loses some response_model benefits)

## Configuration reference

| Env var | Default | Purpose |
|---|---|---|
| `RAG_API_KEYS` | unset (fail-closed) | comma-separated list of allowed API keys |
| `RAG_RATE_LIMIT_PER_MINUTE` | 60 | per-key cap; 0 = effectively unlimited (1M/min) |

Key generation pattern:

```bash
python -c "import secrets; print('rag_' + secrets.token_urlsafe(24))"
```

The `rag_` prefix means anyone reading a log can identify the string as a key for this service.

## Risk + tradeoff observations (from implementation)

1. **In-process rate limit state lost on restart** — by design for v1.
   No Redis. Trade-off explicit in the plan. If a single-replica
   restart happens mid-traffic, every key's bucket resets to full.
   Acceptable for v1; revisit in Phase 9 if horizontal scaling lands.

2. **`secrets.compare_digest` overhead negligible** — measured under
   1ms for the 2-key fixture set. Even at 1000 keys, microsecond
   territory.

3. **Multi-key list rotation works as designed** — `RAG_API_KEYS=k1,k2`
   accepts either; rotating to `k1,k2,k3` adds without disrupting;
   removing `k1` leaves `k2,k3` working. Process restart still required
   for env-var change to take effect, but the window of "no valid key"
   is zero.

4. **`slowapi`'s headers_enabled behavior is FastAPI-incompatible** —
   the known limitation above. This is a real maintenance surface that
   future Phase 8.x work should evaluate ("should we ditch slowapi?").

## What changed in the codebase

### `rag_leis/server.py`
- New module-level: `_allowed_keys()`, `verify_api_key()`,
  `_rate_limit_key()`, `_rate_limit_cap()`, `limiter` instance,
  `_rate_limit_handler` exception handler
- `POST /v1/ask` gained `@limiter.limit(_rate_limit_cap)` decorator +
  `api_key: str = Depends(verify_api_key)` parameter + `request: Request`
  parameter (required by `@limiter.limit`)
- `app.state.limiter = limiter` (slowapi convention; needed by the
  decorator + handler)

### `tests/test_server.py`
- New `_auth_env` autouse fixture sets `RAG_API_KEYS` + generous
  `RAG_RATE_LIMIT_PER_MINUTE` for every test; resets the limiter
  between tests
- Module constants `VALID_KEY`, `OTHER_VALID_KEY`, `AUTH_HEADERS`
- All existing `/v1/ask` test requests updated to pass `AUTH_HEADERS`
- 10 new tests covering auth + rate-limit paths

### `pyproject.toml`
- `server` optional-extra extended: `+ "slowapi>=0.1.9"`
- Install: `uv sync --extra server` (or together with voyage:
  `uv sync --extra voyage --extra server`)

## Suite

448 → **458** passed (+10 new). Test runtime added ~0.3s.

## Cross-references

- [`phase-8.2-auth-rate-limit-plan.md`](phase-8.2-auth-rate-limit-plan.md) — the plan this doc closes
- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — parent plan; sub-phase 8.2 now ✅
- `rag_leis/server.py` — the file built up across 8.1 + 8.2
- `tests/test_server.py` — the test surface
