# Phase 8.3 — Structured observability (planning, NOT YET BUILT)

**Date:** 2026-05-20
**Status:** Planning. No code yet; no pre-locked criteria committed yet.
**Predecessors:**
- [Phase 8.1](phase-8-entry-plan.md#81--http-harness-1-session) — HTTP harness shipped 2026-05-19 (`4e7e51f`).
- [Phase 8.2](phase-8.2-auth-rate-limit-findings.md) — auth + rate limit shipped 2026-05-20 (`4e7e51f`). Left one explicit open item: **200 responses lack `X-RateLimit-*` headers** due to slowapi/FastAPI `response_model` interaction. Phase 8.3 picks this up.
- [Phase 8 entry plan](phase-8-entry-plan.md) — original 8.3 line-item: "Replace `print()` with JSON structured logs; OpenTelemetry traces with request span + child spans for retrieve / generate / verify / relevance-judge; defer exporter choice."
- [rag-eval-metrics-audit](rag-eval-metrics-audit.md) — rows 23 (structured logging), 28 (provider availability — partial), 30 (throughput — Phase 8.4) currently ❌. Phase 8.3 closes row 23 cleanly; nudges 28 toward ✅ via auth-failure visibility.

## Why this sub-phase blocks 8.4

Sub-phase 8.4 (load test) measures the endpoint under concurrency.
Without structured logs + traces, the load-test outputs are opaque
— we get aggregate numbers (p95 latency, error rate) but no
visibility into *why* a given request was slow or failed. Phase 8.4
needs sub-phase-specific instrumentation to be useful, and the
instrumentation should be in place BEFORE the load runs (not bolted
on after).

The Phase 8 entry plan also reads sequentially: 8.3 unlocks the rest
of the diagnostic capability needed for 8.4 to produce capacity
numbers that downstream sub-phases (8.5 CI gate, 8.6 alerting) can
act on.

## What 8.3 ships

Four concrete deliverables, ordered by dependency:

1. **Per-request structured JSON logs** with `request_id`,
   timestamps, key fields (latency, cost, classified_type, refused,
   refusal_reason). One line in, one line out per request.
2. **`X-Request-ID` response header** so clients can correlate
   logs/traces with their own observability surface.
3. **OpenTelemetry spans** — at minimum, request boundary span +
   child spans for `retrieve`, `generate`, `verify`,
   `relevance-judge`. No-op exporter for v1 (spans created but not
   shipped anywhere). Exporter choice deferred to 8.5 deploy work.
4. **Phase 8.2 follow-up** — middleware that injects
   `X-RateLimit-*` headers on **every** `/v1/ask` response (200 +
   429), resolving the known limitation from
   [`phase-8.2-auth-rate-limit-findings.md`](phase-8.2-auth-rate-limit-findings.md).

## Logging design

### Library choice

| Option | Trade-off |
|---|---|
| **A. `structlog` (Recommended)** | De facto standard for structured logging in modern Python. Key-value builder API; async-safe via `contextvars`; integrates cleanly with OpenTelemetry trace IDs (auto-stamps traces in log lines). Adds one dep. |
| B. stdlib `logging` + `python-json-logger` | No `structlog` dep; familiar to most engineers. More verbose configuration; context propagation is manual. |
| C. Hand-rolled JSON dump to stdout | Zero deps. Loses level/handler/formatter machinery that downstream aggregators rely on. Brittle. |

**Choice: A.** Worth the one dep — once OpenTelemetry trace IDs land
in 8.3, `structlog`'s `contextvars` integration auto-stamps the
trace ID on every log line emitted during a request. That's the
property that makes logs + traces searchable across the same
correlation ID without manual wiring.

### Log format

JSON to stdout (Fly / Railway / Render aggregate stdout automatically;
no file rotation logic needed). One log line per event. Required
fields on every record:

| Field | Type | Example |
|---|---|---|
| `timestamp` | ISO-8601 | `"2026-05-20T04:35:12.847Z"` |
| `level` | str | `"info"`, `"warning"`, `"error"` |
| `event` | str | `"request.received"`, `"request.completed"`, `"auth.failed"`, `"rate_limit.exceeded"` |
| `request_id` | str (uuid4 hex first 8) | `"a3f8b921"` |
| `trace_id` | str (OTel hex) | `"4bf92f3577b34da6a3ce929d0e0e4736"` |
| `service` | str | `"rag-leis-digitais-br"` |
| `version` | str | `"0.1.0"` (from pyproject) |

Event-specific fields:

**`request.received`** (entry):
- `method`, `path`, `client_ip`, `api_key_prefix` (first 8 chars or `none` — NEVER log full keys)

**`request.completed`** (exit on every path including errors):
- `status_code`, `latency_ms`, `query_length` (if `/v1/ask`), `classified_type`, `top_1_cosine`, `n_citations`, `n_rejected_irrelevant`, `refused`, `refusal_reason`, `cost_estimate_usd`, `llm_calls`, `tokens_input`, `tokens_output`
- Set fields to `null` when not applicable (e.g., `query_length` is null for `/health`).

**`auth.failed`** (every 401):
- `reason` (`"missing-key"` or `"invalid-key"`), `api_key_prefix` (first 8 chars of the bad key, useful for debugging without leaking the full string)

**`rate_limit.exceeded`** (every 429):
- `api_key_prefix`, `cap_per_minute`, `retry_after_seconds`

**`pipeline.error`** (every 500):
- `error_type`, `error_message`, traceback (single multi-line string field)

### What we explicitly DO NOT log

- **Full API keys.** Prefix only (first 8 chars). Tests should
  verify a key like `rag_smoketest123` never appears in log output
  beyond `rag_smoke`.
- **Raw query text.** The query may contain PII (CPF, CNPJ, names —
  Phase 4.2 redacts these for the LLM call but logs are a separate
  exposure). Log `query_length` + `classified_type`; if richer
  query analysis is needed for debugging, do it offline against the
  audit log (Phase 4.2 path) which has its own PII handling.
- **Raw answer text.** Same rationale — logs aggregate broadly.
  Log `n_citations`, `refused`, `cost_estimate_usd` instead.
- **Stack traces with embedded query/answer.** Generic
  `error_type` + `error_message`; trace bodies are useful but
  redact before logging.

### Per-event log volume

For a healthy production load (~10 req/min steady state):
- 10 `request.received` + 10 `request.completed` = 20 lines/min
- Sporadic `auth.failed` / `rate_limit.exceeded` / `pipeline.error`

~1 KB / line × 30 lines/min × 60 × 24 = **~43 MB / day**. Well
within any aggregator's free-tier budget for v1.

## OpenTelemetry design

### Library + exporter choice

| Decision | Recommendation |
|---|---|
| OTel SDK | `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-instrumentation-fastapi` |
| Exporter for v1 | **No-op (in-memory) exporter.** Spans created but not shipped. Phase 8.5 deploy work picks a real exporter (Honeycomb / Grafana Tempo / Lightstep) when production traffic exists to instrument. |
| Span propagation | Auto-instrument captures FastAPI request boundaries; manual `tracer.start_as_current_span("retrieve")` etc. inside `rag.py` for inner stages. |

The "no-op exporter for v1" is the load-bearing choice: it means
**8.3 can ship without committing to a vendor or backend**. The
instrumentation surface (spans created at the right boundaries) is
the durable artifact; the exporter is a swap-in concern.

### Span hierarchy

```
http.request POST /v1/ask          (auto-instrumented by OTel FastAPI)
├── pipeline.answer                (manual; one span per pipeline.answer call)
│   ├── pipeline.redact            (skipped if redact_pii=False)
│   ├── pipeline.classify
│   ├── pipeline.retrieve          (top_k cosine; FAISS lookup)
│   ├── pipeline.llm.generate      (the main generator call)
│   ├── pipeline.verify            (cite-and-verify URN ∈ corpus)
│   └── pipeline.relevance_judge   (only when relevance gate fires)
```

Each span carries attributes mirrored from the log fields
(`classified_type`, `top_1_cosine`, `cost_estimate_usd`, etc.). When
a real exporter lands later, trace timelines visualize where time is
spent without re-instrumenting.

### Where in the code does instrumentation live?

**Option B (per entry plan): touch `rag.py` to add inner spans.**
- Adds ~10-15 lines per phase boundary in `rag.py`
- Spans are real diagnostic capability — load test can see retrieve
  taking 50ms while llm.generate takes 5s; that's actionable
- Cost: `rag.py` is the most-touched file in the repo; adding OTel
  imports + try/finally span scopes touches a lot of test surface

**Option A (lighter): only the request-boundary span at HTTP layer.**
- Just auto-instrument FastAPI; no `rag.py` changes
- Loses inner-phase visibility — load test sees "pipeline.answer
  took 5s" but not whether that was retrieve or generate
- Cheaper to ship; less invasive

**Recommendation: Option B**, scoped tightly. The entry plan
already committed to inner spans, and the cost-of-not-having-them
gets bigger every sub-phase. Touch `rag.py` once, get the visibility
forever.

## Phase 8.2 follow-up: 200 response headers

Build a small middleware that runs AFTER FastAPI's response is
constructed and BEFORE the response leaves the server:

```python
class RateLimitHeadersMiddleware:
    """Inject X-RateLimit-* headers on every /v1/ask response.
    Reads request.state.view_rate_limit (set by slowapi's decorator)
    and constructs the same headers the 429 handler produces."""
```

Approach: extract the manual header construction from the existing
`_rate_limit_handler` into a helper function, call it from the
middleware on successful responses. The 429 handler stays as a
fallback (covers cases where the middleware can't read state).

**Why this couldn't be done in 8.2**: Phase 8.2 surfaced the
slowapi/FastAPI `response_model` incompatibility as a known
limitation, with the planned fix deferred to 8.3 once we had a
middleware layer to work with. 8.3 adds structured logging
middleware ANYWAY — adding one more middleware in the same sub-
phase is the right place.

## Pre-locked criteria

> Phase 8.3 ships iff:
> 1. **Structured logs**: every request emits exactly one
>    `request.received` and one `request.completed` JSON log line
>    to stdout, with all required fields populated. Unrelated
>    `print()` statements are removed or migrated to `structlog`.
> 2. **Request correlation**: every response carries
>    `X-Request-ID` header (UUID first 8 hex chars). The same
>    `request_id` appears in both `request.received` and
>    `request.completed` log lines.
> 3. **Auth/rate-limit events logged**: 401 and 429 paths emit
>    `auth.failed` and `rate_limit.exceeded` events with key
>    prefixes (never full keys).
> 4. **OpenTelemetry spans**: the request boundary span + at least
>    4 child spans (`pipeline.classify`, `pipeline.retrieve`,
>    `pipeline.llm.generate`, `pipeline.verify`) are created for
>    every `/v1/ask` request. Verified via in-memory exporter in
>    tests.
> 5. **200 responses now carry `X-RateLimit-*` headers** (8.2
>    follow-up resolved).
> 6. **No PII / secret leakage** in any log line: tests pattern-
>    match for full API key strings in captured log output and
>    assert ABSENT; tests pattern-match for query text in log
>    output and assert ABSENT.
> 7. **Existing 458 tests still pass.**
> 8. **New tests** (8-12) cover: log line shape, request-id
>    propagation, auth/rate-limit event emission, OTel span
>    creation, PII-absent assertion, header injection on 200.

## Out of scope (explicit non-goals)

- **Production exporter choice** (Honeycomb / Grafana Tempo /
  Lightstep / Datadog) — defer to 8.5 deploy.
- **Metrics scraping endpoint** (`GET /metrics` for Prometheus) —
  could be a small adder later; not load-bearing for 8.3.
- **Log aggregation infrastructure** — Fly/Railway aggregate stdout
  natively; no new infra.
- **Real-time alerting on log patterns** — that's 8.6.
- **Audit-log integration** — Phase 4.2 `pii_audit_log` is a
  separate concern (PII-handling specific); not part of 8.3's
  observability layer.
- **Performance profiling** (py-spy, austin) — not in scope.
- **Log retention policy** — aggregator's concern.

## Open design questions to resolve at sub-phase start

1. **`structlog` config style**: `configure_once()` at module import
   vs lifespan setup. Recommendation: `configure_once()` so library
   users (eval CLI) get structured output for free; lifespan can
   override the level/processors if needed.

2. **PII redaction in logs**: should the existing `redact()` from
   `pii.py` be called on any logged query-derived field? Currently
   the plan logs `query_length` + `classified_type` only — no raw
   text. If we ever WANT to log a query snippet (e.g., for prefix-
   based abuse detection), redact first. Decision: **don't log
   query text in 8.3**; revisit if abuse-detection use case lands.

3. **Inner-span granularity**: should `pipeline.verify` and
   `pipeline.relevance_judge` be separate spans, or merged into
   `pipeline.postprocess`? Recommendation: **separate**. The
   relevance gate is a known latency contributor (~+1.6s per
   citation-having row per Phase 7.8 findings); merging hides it.

4. **Should `GET /health` be logged?** Platform probes hit every
   30s/replica — that's a lot of noise. Recommendation: **log
   `/health` at DEBUG level only**; INFO threshold for
   `/v1/ask`. Aggregators can filter.

5. **OpenTelemetry semantic conventions**: use standard
   `http.method`, `http.status_code`, etc., even if the no-op
   exporter doesn't ship them yet? Yes — costs nothing now and
   makes future exporter integration trivial.

## Risk + tradeoff analysis

| Risk | Severity | Mitigation |
|---|---|---|
| structlog config conflicts with existing logging (eval CLI) | Low | `configure_once()` is idempotent; eval CLI gets structured output for free, no behavioral change |
| OTel adds startup overhead | Low | SDK init is <100ms; no-op exporter has zero per-span overhead |
| Inner spans add CPU per request | Very low | Span creation is microsecond-scale; auto-instrument FastAPI already wraps every request |
| Logs accidentally include PII | Medium | Pre-locked criterion #6 explicitly tests for this; PII redaction in pipeline path is unchanged |
| `rag.py` touches break existing tests | Medium | Touching is scoped to span boundaries; existing tests are behavior tests, not structural |
| structlog/OTel deps add ~10MB to image | Low | Phase 8.5 deploy work cares about image size; 10MB is well within Fly's 2GB starter |

## Cost estimate

- **API spend**: $0. No LLM calls; pure middleware + instrumentation.
- **Wall time**: ~1 session per entry plan estimate (~3-4h).
  Includes the `rag.py` span wiring + tests + Phase 8.2 follow-up.
- **New deps**: `structlog>=24.0`, `opentelemetry-api>=1.27`,
  `opentelemetry-sdk>=1.27`, `opentelemetry-instrumentation-fastapi>=0.49`
  added to `server` optional-extra.

## Sequencing within 8.3

1. **Add deps + bump `pyproject.toml`** server extra. `uv sync`.
2. **structlog setup** in a new `rag_leis/obs.py` module:
   `configure_logging()` function called once at server startup.
   JSON renderer to stdout; `request_id` + `trace_id` via
   `contextvars`. Eval CLI doesn't call `configure_logging()` and
   stays on stdlib `print()` — no behavioral change there.
3. **Middleware**: `RequestContextMiddleware` generates
   `request_id`, binds it via `structlog.contextvars`, sets
   `X-Request-ID` response header. Emits `request.received`
   on entry, `request.completed` on exit.
4. **Phase 8.2 follow-up**: `RateLimitHeadersMiddleware` injects
   `X-RateLimit-*` on every `/v1/ask` response.
5. **OTel setup** in `obs.py`: SDK init, no-op exporter, FastAPI
   auto-instrument. `tracer = trace.get_tracer(...)` exported.
6. **`rag.py` inner spans**: wrap each phase boundary in
   `with tracer.start_as_current_span("pipeline.X"):`. Set span
   attributes for the data downstream consumers want.
7. **Auth/rate-limit log events**: extend
   `verify_api_key` and `_rate_limit_handler` to emit `auth.failed`
   and `rate_limit.exceeded` events.
8. **Tests** (8-12 new):
   - log line shape (JSON, fields present)
   - `X-Request-ID` correlates `request.received` + `request.completed`
   - `auth.failed` emitted on missing/invalid key
   - `rate_limit.exceeded` emitted on 429
   - OTel spans created (in-memory exporter for tests)
   - PII-absent assertions (full key, query text never appear)
   - `X-RateLimit-*` headers on 200 (8.2 follow-up regression test)
   - `request.completed` includes `cost_estimate_usd` on `/v1/ask`
9. **Smoke run**: start server with structured logging on, send
   variety of requests (200, 401, 429), grep stdout for the
   expected JSON shape + correlated request IDs.
10. **Findings doc**: `phase-8.3-structured-observability-findings.md`.

## What we'll learn that's not in this plan

- Whether `structlog`'s `contextvars` integration cleanly captures
  the OTel `trace_id` without manual wiring (claim: yes; verify
  empirically).
- Whether `opentelemetry-instrumentation-fastapi`'s auto-instrument
  captures the request boundary cleanly or interferes with our
  custom middleware ordering.
- Whether the no-op exporter creates measurable overhead vs no
  spans at all (claim: <1ms; verify).
- Whether the `rag.py` inner-span instrumentation surfaces
  unexpected latency hotspots once we can actually look at the
  decomposition (interesting either way).

## Cross-references

- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — parent plan
- [`phase-8.2-auth-rate-limit-findings.md`](phase-8.2-auth-rate-limit-findings.md) — open 200-response-header issue this resolves
- [`phase-7.5.7-sre-golden-signals-findings.md`](phase-7.5.7-sre-golden-signals-findings.md) — Phase 7.5.7 instrumented per-row latency/cost; 8.3 extends to per-request structured event log
- [`rag-eval-metrics-audit.md`](rag-eval-metrics-audit.md) row 23 — structured logging gap that 8.3 closes
- `rag_leis/server.py` — middleware adds
- `rag_leis/rag.py` — inner-span instrumentation
- `tests/test_server.py` — extended with observability assertions
