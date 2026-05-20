# Phase 8 — Production hosting entry plan

**Date:** 2026-05-19
**Status:** Planning. No sub-phase committed yet; this doc is the scope-and-tradeoff frame for the conversation that picks the first move.
**Predecessors that unblocked this phase:**

- Phase 7.5.7 — SRE Golden Signals (latency, errors, cost) now first-class on every eval row
- Phase 7.5.2 + 7.5.7 — cost-per-query tracker fixed (was 13× under-reported)
- Phase 7.6 → 7.8 — OOS refusal discipline lifted to 0.633 on legalbench (5.2× lift); Phase 8 entry no longer blocked on refusal quality
- Phase 7.8.1 — Sabiá-vs-Opus A/B established eval-default = Opus relevance judge, prod-default = Sabiá (cost-driven split)
- Phase 7.9 — LLM response cache shipped (opt-in via `--llm-cache-dir`)

## What Phase 8 *is*

Putting the RAG pipeline behind an HTTP server with the operational
properties a real production service needs: bounded latency under load,
cost ceilings, auth, structured observability, rollback discipline,
deploy hygiene. This is the architectural transition from
"reproducible eval CLI" to "service someone can call from another
machine."

Concretely, Phase 8 is the surface where the project's existing memory
("production-level project") and the audit doc's stated gaps (provider
availability, throughput, true structured logging, tracing) become
load-bearing for the first time.

## Baseline numbers (measured, anchored to sabia-4 production default)

From [Phase 8.0 prod-cost baseline](phase-8-0-prod-cost-baseline.md) +
[Phase 8.0.1 A/B](phase-8-0-1-sabia-3.1-vs-4-findings.md). Pipeline:
sabia-4 generator + sabia-4 self-judging relevance gate, no answer-
quality judge (eval-only). 78 rows combined (internal + legalbench).

| Metric | Value | Notes |
|---|---|---|
| Cost mean (all rows) | **$0.0046 / query** | includes refused rows (cheap; no LLM call on cosine fast-path) |
| Cost mean (answered only) | **$0.0064 / query** | the SLO-relevant subset |
| Cost p95 (answered) | **$0.0109 / query** | |
| Latency p50 (all rows) | **0.31s** | cosine fast-path dominates; no LLM call |
| Latency p95 (fresh API) | **~2.87s** | from A/B variant B fresh measurement |
| Latency p99 (fresh API) | **~4.19s** | |
| Error rate | **0.0%** | |
| Refusal rate | 0.564 | OOS recall 0.672 + in-scope FR 0.071 |

## SLO targets (candidates, anchored to sabia-4 measurements)

These are starting positions; pick the final numbers when you commit to
a hosting platform, since some are platform-bounded.

| SLO | Target | Why |
|---|---|---|
| Latency p95 (short) | **< 5s** | sabia-4 fresh p95 ≈ 2.9s; 5s gives ~70% headroom |
| Latency p95 (discursive) | < 15s | OAB-style longer answers (Phase 7.5.5 measured ~p95 26s — needs separate discursive baseline before locking) |
| Cost mean per query | **< $0.01** | sabia-4 measures $0.0064; $0.01 = 1.6× headroom; alert above |
| Cost p99 per query | **< $0.02** | sabia-4 measures $0.011; 2× headroom for outliers |
| In-scope false-refusal rate | **< 0.10** | sabia-4 measures 0.071 at n=14 (wide CI); alert if rolling 7d > 0.10 |
| OOS refusal recall | ≥ 0.65 | sabia-4 measures 0.672 on combined surfaces; hold |
| Error rate | < 1% | provider rate-limit + timeout headroom |
| Cache hit rate | tracked, no SLO | informational; flag when production query distribution shifts |

## Sub-phase decomposition

Each sub-phase is sized to ship in 1-2 sessions. Order is dependency-
driven; later items lean on the harness from earlier items.

### 8.0 — Production cost baseline (½ session, $0 spend)

The current cost numbers are eval-mode. Phase 8 design conversations
need prod-mode numbers. Smallest possible sub-phase: instrument a
no-judge eval pass that simulates "production query" (Sabiá generator
only, Sabiá relevance gate, no answer-quality judge). Re-run internal
eval that way. Use cached LLM responses → $0 spend.

Output: a `phase-8-0-prod-cost-baseline.json` with the actual numbers
that the SLO conversation needs.

### 8.1 — HTTP harness (1 session)

- Single endpoint: `POST /v1/ask` with `{query: string, ...optional knobs}` body
- Returns: `RAGAnswer` JSON (already a dataclass; just serialize)
- Sync handler; one query at a time; no streaming yet
- Framework: **FastAPI** (recommended). Pydantic-native, async-ready
  when needed, OpenAPI for free
- Persistence: in-process pipeline instance — load once at startup,
  serve from memory. Index + chunks already loadable in <2s from
  the eval CLI; same path here
- Health endpoint: `GET /health` returns 200 with pipeline-loaded flag
- This is the foundation; nothing else can be built without it

### 8.2 — Auth + rate limiting (½ session)

- API key auth (header-based, single shared key for v1 — multi-tenant
  is a Phase 9 problem)
- Per-key rate limiting: token bucket, configurable cap. Default:
  60 req/min per key (matches Maritaca's typical per-account ceiling
  with headroom)
- 429 responses include `Retry-After`
- This must happen *before* observability gets meaningful; otherwise
  load tests will be against an open-relay endpoint

### 8.3 — Structured observability (1 session)

- Replace `print()` with JSON structured logs (`structlog` or stdlib
  `logging` + JSON formatter). Each request gets a request_id and a
  log record with: query length, classified_type, top_1 cosine,
  latency_ms, cost_estimate_usd, refused, refusal_reason, error
- OpenTelemetry traces: at minimum, the request span + child spans
  for retrieve / generate / verify / relevance-judge. Defer exporter
  choice (could be Honeycomb, Grafana Tempo, or no-op until 8.4)
- Audit doc rows 23, 28, 30 → ✅ at completion of this sub-phase

### 8.4 — Load test + capacity (1 session, ~$10 spend)

- `locust` or `wrk` against the deployed endpoint
- Workload: replay of `eval/answer_queries.yaml` + `legalbench_br_oos.yaml`
  in random order, configurable concurrency
- Measure: degradation curve (latency p95 vs concurrent users),
  saturation point (where errors start), provider rate-limit hits
- Output: capacity table — "N concurrent users → p95 latency X seconds,
  error rate Y%, cost per minute Z"
- Cost: load test will pay real LLM bills since the cache
  won't help adversarial-varied queries. Cap the test budget.

### 8.5 — CI deploy pipeline + eval gate (1 session)

- GitHub Actions workflow: on merge to main, run the existing
  `pytest` suite (all 438 tests) + a fast subset of the answer eval
  (cache-hit-only, $0)
- If suite green and fast eval shows no SLO regression vs. previous
  baseline, deploy to staging
- Manual promote-to-prod via gh CLI or a `release` git tag
- Rollback: keep last N deployments warm; rollback is a re-deploy of
  previous tag
- Decision needed: hosting platform (Fly.io / Railway / Render /
  bare VM). Smallest is Fly.io with one Brazilian-region machine

### 8.6 — Production cost ceiling + alerting (½ session)

- Daily spend cap configured at provider level (Anthropic console,
  Maritaca dashboard if available)
- Alert when: cost-per-query rolling 1h mean > $0.05; latency p95 > 15s;
  error rate > 2%; refusal accuracy drops below 0.90 (computed offline
  weekly against a held-out replay subset)
- Alerts go to a single channel — Telegram bot or email; not paging.
  This is a personal project, not a SaaS

## Open design questions (resolve before sub-phase commits)

1. **Hosting platform.** Fly.io is the recommended starting point —
   Brazilian-region machine, predictable pricing, simple CI. Vercel
   Functions are cheaper but have 60s timeout which clips p99 = 15.9s
   into errors. Railway and Render are similar to Fly with different
   pricing curves.

2. **Streaming responses.** The pipeline produces the answer in one
   shot today. Streaming would lower perceived latency at the cost of
   protocol complexity. Probably defer to a Phase 9 UI cycle.

3. **Cache strategy.** Phase 7.9 cache is per-machine filesystem.
   Production with a single instance can reuse that (mount a
   persistent volume). Multi-instance needs Redis or off-by-default.
   For v1 single-instance, persist a filesystem cache; warm it from
   the cached eval responses already in the repo.

4. **Maritaca + Anthropic dependency.** Two providers, two failure
   modes. Audit doc row 28 (provider availability) is the gap.
   Smallest treatment: if Maritaca times out or 5xx's, fall back to
   Sabiá-via-Anthropic-API (not viable — different vendor) OR fall
   back to a cached "I'm having trouble right now, try later" 503.
   Defer fancier failover to post-8.6.

5. **Query logging — PII implications.** Production queries can contain
   CPF/CPNJ; Phase 4.2 PII redaction is in the pipeline. Should
   structured logs include the *redacted* query (yes, useful for
   support) or omit query text entirely (privacy-maximalist)? The
   `pii_audit_log` path already handles raw queries; production
   should default to "log redacted only."

## Pre-locked criteria for sub-phase 8.1 ship

> Phase 8.1 (HTTP harness) ships iff:
> 1. `POST /v1/ask` returns a valid `RAGAnswer` JSON for the same query
>    that `run_answer_eval` produces, byte-for-byte equivalent answer
>    text and citations (no behavior drift through the HTTP layer)
> 2. Cold-start: pipeline loads in <5s
> 3. Memory footprint after pipeline load: <2GB (allows Fly's 2GB
>    starter machines)
> 4. All 438 existing tests still pass
> 5. New tests cover: endpoint contract (request/response schemas),
>    auth (when 8.2 lands), error responses (400/422/500)

## What this is NOT (explicit non-goals)

- **Multi-tenant.** Single shared API key for v1. Per-user accounts,
  billing, quotas → Phase 9 if at all.
- **Web UI.** API only. A UI would be a separate Phase 9/10 cycle
  using next-forge or a custom Astro frontend.
- **Streaming.** One-shot JSON responses. Streaming is a Phase 9
  perceived-latency optimization.
- **Multi-region.** Single Brazilian-region machine. Multi-region is
  premature without traffic.
- **Auto-scaling.** Single instance, vertical scale only. Horizontal
  scaling needs the multi-instance cache decision (open question #3).

## Sequencing recommendation

The smallest-risk way to enter is **8.0 → 8.1 → 8.2 → 8.3** (the
baseline + harness + auth + observability core), with 8.4/8.5/8.6
gated on the first three landing. Sub-phase 8.0 is the cheapest
($0, ½ session) and gives the actual SLO conversation real numbers.

Alternative entry: skip 8.0 and go straight to 8.1 if "we'll measure
prod cost from production" is acceptable. Saves ½ session at the cost
of an SLO conversation grounded in eval-mode numbers.

## Cross-references

- [`rag-eval-metrics-audit.md`](rag-eval-metrics-audit.md) — gaps that
  Phase 8 closes (rows 23, 28, 29, 30)
- [`phase-7.5.7-sre-golden-signals-findings.md`](phase-7.5.7-sre-golden-signals-findings.md) — what's already instrumented
- [`phase-7.8.1-sabia-vs-opus-judge-findings.md`](phase-7.8.1-sabia-vs-opus-judge-findings.md) — prod-default = Sabiá relevance judge; the design assumes this
- `BACKLOG.md` lines 134-153 — refusal-discipline status and the
  "remaining work (production-acceptable)" list that Phase 8 will
  consume
