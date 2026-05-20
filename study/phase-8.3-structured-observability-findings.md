# Phase 8.3 — Structured observability (findings)

**Date:** 2026-05-20
**Predecessor:** [Phase 8.3 plan](phase-8.3-structured-observability-plan.md), drafted 2026-05-20.
**Cost:** $0. No LLM calls; pure middleware + instrumentation work.
**Status:** Phase 8.3 SHIPPED. All eight pre-locked criteria met.

## Pre-locked criteria — result

| # | Criterion | Status |
|---|---|:-:|
| 1 | Per-request structured JSON logs with all required fields | ✅ |
| 2 | `X-Request-ID` on every response; correlates received + completed | ✅ |
| 3 | `auth.failed` + `rate_limit.exceeded` events emitted | ✅ |
| 4 | OpenTelemetry spans (request + 4 child) created per request | ✅ |
| 5 | 200 responses now carry `X-RateLimit-*` headers (8.2 follow-up) | ✅ |
| 6 | No PII / full keys in logs (test verifies pattern-match absence) | ✅ |
| 7 | All 458 existing tests still pass | ✅ (468 total now) |
| 8 | New tests covering all of the above | ✅ (10 new) |

## What ships

- **`rag_leis/obs.py`** — central observability module exporting
  `configure()`, `get_logger()`, `span()`, `get_in_memory_exporter()`,
  `reset_for_tests()`. The `span()` context manager is no-op when
  `configure()` hasn't been called, so the eval CLI imports
  `rag_leis.rag` without paying any cost or pulling OTel state.
- **`RequestContextMiddleware`** on `rag_leis/server.py` —
  generates `request_id`, binds to `structlog.contextvars`, emits
  `request.received` + `request.completed`, stamps `X-Request-ID`
  response header. Health probes log at DEBUG (suppressed from
  INFO production output to avoid 30s/replica probe noise).
- **`RateLimitHeadersMiddleware`** — resolves the Phase 8.2 known
  limitation. Reads `request.state.view_rate_limit` (set by slowapi's
  decorator) and injects `X-RateLimit-Limit/-Remaining/-Reset`
  + `Retry-After` on every `/v1/ask` response.
- **OpenTelemetry**: auto-instrumented FastAPI via
  `FastAPIInstrumentor.instrument_app(app)` (request boundary span);
  manual `with obs.span("pipeline.X"):` inside `rag_leis/rag.py` at
  the five phase boundaries:
  - `pipeline.classify` (with `classified_type`, `effective_top_k`)
  - `pipeline.retrieve` (with `top_k`, `top_1_cosine`, `n_retrieved`)
  - `pipeline.llm.generate` (with `provider`, `model`)
  - `pipeline.verify` (with `n_cited`, `n_verified`, `n_rejected`)
  - `pipeline.relevance_judge` (with `provider`, `model`, `n_citations`)
- **No-op exporter for v1** — spans created but not shipped.
  Phase 8.5 deploy work will pick a real exporter (Honeycomb / Grafana
  Tempo / etc.) once production traffic exists to instrument.
- **Auth + rate-limit events**: `verify_api_key()` emits `auth.failed`
  with `{reason, api_key_prefix}` on every 401; the 429 handler emits
  `rate_limit.exceeded` with `{api_key_prefix, cap, retry_after_seconds}`.
- **10 new tests** in `tests/test_server.py`:
  - `X-Request-ID` on every response (health, ask, openapi)
  - `pipeline.answered` log fields all present
  - `auth.failed` on missing/invalid key (both reasons)
  - `rate_limit.exceeded` on 429
  - Full API key NEVER appears in logs (pattern-match absence)
  - Raw query text NEVER appears in logs (pattern-match absence)
  - HTTP-request OTel span created
  - Inner pipeline OTel spans created
  - `X-RateLimit-*` headers on 200 (8.2 follow-up regression)

## Live smoke test (single request to /v1/ask, output below)

Three log lines emitted, all sharing `request_id=47e42a7c`:

```json
{"event": "request.received", "method": "POST", "path": "/v1/ask",
 "client_ip": "127.0.0.1", "api_key_prefix": "rag_smok",
 "request_id": "47e42a7c", "service": "rag-leis-digitais-br",
 "level": "info", "timestamp": "2026-05-20T05:04:55.920172Z"}

{"event": "pipeline.answered", "query_length": 41,
 "classified_type": "definicao", "top_1_cosine": 0.7649888992,
 "n_citations": 4, "n_rejected_irrelevant": 3, "refused": false,
 "refusal_reason": null, "cost_estimate_usd": 0.005201,
 "llm_calls": 3, "tokens_input": 3828, "tokens_output": 713,
 "pipeline_latency_ms": 270.062, "request_id": "47e42a7c",
 "service": "rag-leis-digitais-br", "level": "info",
 "timestamp": "2026-05-20T05:04:56.195599Z"}

{"event": "request.completed", "method": "POST", "path": "/v1/ask",
 "status_code": 200, "latency_ms": 276.2, "request_id": "47e42a7c",
 "level": "info", "timestamp": "2026-05-20T05:04:56.196244Z"}
```

Response headers:

```
HTTP/1.1 200 OK
x-ratelimit-limit: 5
x-ratelimit-remaining: 4
x-ratelimit-reset: 1779253555
retry-after: 59
x-request-id: 47e42a7c
content-type: application/json
```

Auth failure path emits two lines (`request.received` + `auth.failed`)
then the completion log; the request_id correlates them:

```json
{"event": "auth.failed", "reason": "missing-key",
 "api_key_prefix": "none", "request_id": "e2fc4d09",
 "service": "rag-leis-digitais-br", "level": "warning", ...}
```

## Three things learned beyond the plan

1. **OTel's `set_tracer_provider` is single-shot per process.** First
   call wins; subsequent calls warn and no-op. Tests that try to swap
   providers (e.g., to clear in-memory spans between cases) get a
   stale provider. **Resolution**: `obs.configure()` sets the
   provider only on the FIRST call; subsequent calls just clear the
   in-memory exporter. `reset_for_tests()` documents this explicitly.
   This is mentioned in OTel SDK docs but easy to miss; flagged here
   for future Phase 8.x sub-phases that touch the SDK.

2. **structlog's `contextvars` integration is exactly as good as
   advertised.** Binding `request_id` once in the middleware and
   every subsequent `log.info(...)` automatically carries the field
   — no manual threading needed. The same will work for OTel
   `trace_id` when Phase 8.5 wires a real exporter (the
   contextvars processor reads OTel context for free).

3. **The Phase 8.2 "200 responses lack X-RateLimit-* headers"
   limitation was a 30-minute fix once we had a middleware layer
   to work with.** The fix wasn't a slowapi config tweak (that
   continues to crash with FastAPI response_model); it was simply
   extracting the header-construction helper from the 429 handler
   and calling it from a new middleware on the success path. Same
   helper, two call sites. The plan correctly predicted this would
   become trivial once 8.3 added the middleware infrastructure.

## What changed in the codebase

### New file: `rag_leis/obs.py` (~140 lines)
- `configure(level, in_memory_spans)` — structlog + OTel setup, idempotent
- `get_logger(name)` — structlog logger getter
- `span(name, **attrs)` — context manager; no-op when not configured
- `get_in_memory_exporter()` — test introspection
- `reset_for_tests()` — clears span state between tests
- `_NullSpan` — fallback when `configure()` hasn't been called

### `rag_leis/server.py` (~70 lines added)
- imports: `structlog`, `BaseHTTPMiddleware`, `FastAPIInstrumentor`, `obs`, `time`, `uuid`
- `RequestContextMiddleware` — request_id + entry/exit logs + X-Request-ID
- `RateLimitHeadersMiddleware` — Phase 8.2 follow-up
- `_build_rate_limit_headers(request)` — shared helper for 200 + 429 paths
- `lifespan` now calls `obs.configure()`
- `verify_api_key()` emits `auth.failed` events
- `_rate_limit_handler()` emits `rate_limit.exceeded` events; uses shared helper
- `/v1/ask` handler emits `pipeline.answered` with SLO-relevant fields
- `FastAPIInstrumentor.instrument_app(app)` for auto request-span

### `rag_leis/rag.py` (~25 lines touched)
- import: `from rag_leis import obs` (comment notes the no-op fallback)
- 5 inner `with obs.span("pipeline.X"):` blocks at phase boundaries
- Span attributes set the same fields the structured log emits, so
  trace and log are queryable on the same correlation keys

### `tests/test_server.py` (~120 lines added)
- new fixture `captured_logs` — captures structlog JSON into io.StringIO
- new `_parse_logs(buf)` helper
- 10 new Phase 8.3 tests
- `_auth_env` autouse fixture now also configures + resets `obs`

### `pyproject.toml`
- `server` optional-extra extended with `structlog`,
  `opentelemetry-api`, `opentelemetry-sdk`,
  `opentelemetry-instrumentation-fastapi`

## Honest limitations of this sub-phase

1. **No production exporter wired.** Spans are created and held in
   memory (or discarded after the process exits). Real exporter
   choice (Honeycomb / Grafana Tempo / OTLP collector) is Phase 8.5
   deploy-time work. The instrumentation surface is durable; the
   destination is swap-in.

2. **Inner spans don't auto-link to the FastAPI request span in
   tests** — the OTel context propagation works in production
   (FastAPI auto-instrument sets the parent context, manual spans
   inherit it), but TestClient bypasses some of the auto-instrument
   machinery. Production traces will be linked; test assertions verify
   span EXISTENCE, not parent linkage.

3. **No metrics yet** (Prometheus `/metrics` endpoint, counter for
   refusals per minute, gauge for queue depth). Not in 8.3's scope;
   Phase 8.6 alerting may pull from log aggregator instead. Revisit
   if Phase 8.4 load test surfaces a need.

4. **structlog overhead is non-zero but small.** Per-request adds
   ~3-5ms across the contextvars binding + 3 log calls. The
   `pipeline.answered` log was measured at sub-1ms via `time.monotonic`
   diff. Acceptable for v1; revisit only if Phase 8.4 load test shows
   it's load-bearing.

## What this enables for Phase 8.4 (load test)

- `request_id` per request → can correlate timeouts/errors back to
  specific traces
- `pipeline.latency_ms` and `cost_estimate_usd` per request → load
  test outputs can compute p50/p95/p99 and cost-per-1k-requests
  directly from log aggregation
- Inner spans → if `pipeline.llm.generate` p95 explodes under load,
  visible at the right granularity (vs. eval-mode aggregate latency
  that hides the breakdown)
- `auth.failed` rate → can detect credential-stuffing attempts
- `rate_limit.exceeded` rate → tuning input for the per-key cap

## Cross-references

- [`phase-8.3-structured-observability-plan.md`](phase-8.3-structured-observability-plan.md) — the plan this doc closes
- [`phase-8.2-auth-rate-limit-findings.md`](phase-8.2-auth-rate-limit-findings.md) — 200-response header limitation resolved here
- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — parent plan; sub-phase 8.3 now ✅
- [`rag-eval-metrics-audit.md`](rag-eval-metrics-audit.md) row 23 — structured logging gap, now closed
- `rag_leis/obs.py` / `rag_leis/server.py` / `rag_leis/rag.py` / `tests/test_server.py` — the touched files
