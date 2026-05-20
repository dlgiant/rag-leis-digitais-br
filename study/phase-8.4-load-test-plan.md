# Phase 8.4 — Load test + capacity (planning, NOT YET RUN)

**Date:** 2026-05-20
**Status:** Planning. No code yet; no measurements taken.
**Predecessors:**
- [Phase 8.1](phase-8-entry-plan.md#81--http-harness-1-session) HTTP harness (`213e0b4`)
- [Phase 8.2](phase-8.2-auth-rate-limit-findings.md) auth + rate limit (`4e7e51f`)
- [Phase 8.3](phase-8.3-structured-observability-findings.md) structured logs + OTel spans (`465720b`)
- [Phase 8.0](phase-8-0-prod-cost-baseline.md) prod cost baseline: cost mean answered $0.0064, latency p95 fresh ~2.87s, p99 ~4.19s at n=1 concurrency
- [Phase 8 entry plan](phase-8-entry-plan.md) 8.4 line-item: "locust or wrk against the deployed endpoint; replay of eval queries in random order, configurable concurrency; measure degradation curve, saturation point, provider rate-limit hits; ~$10 cost"

## Why this sub-phase blocks 8.5 + 8.6

- **8.5 (CI deploy gate)** wants "no SLO regression vs. previous baseline" as a merge gate. Without a measured capacity curve, "no regression" is vague — what concurrency level should the gate test at, and what p95 threshold? 8.4 answers that.
- **8.6 (alerting)** sets thresholds for p95 latency, error rate, refusal accuracy. Setting those thresholds without measured load behavior means they're guesses. 8.4 converts them to calibrated numbers.

## What 8.4 ships

Three concrete deliverables, ordered by dependency:

1. **Load-test harness** — single script that hits the local server with configurable concurrency, query workload from the eval YAMLs, and records per-request results.
2. **Capacity table** — measured numbers across concurrency levels: p50/p95/p99 latency, error rate, throughput (req/s), cost-per-1k-requests, server-side resource peaks.
3. **Findings doc** with identified bottleneck (provider rate limit? server-side CPU? pipeline-internal lock contention?) and the calibrated SLO numbers Phase 8.6 will alert against.

## Tool choice

| Option | Trade-off |
|---|---|
| **A. Custom asyncio + httpx script (Recommended)** | Tight integration: reads eval YAMLs as workload source; reuses existing `httpx` dep (no new lib); produces JSON output the Phase 8.3 structured logs can be cross-referenced against; ~80 lines. Less polished UI than locust, but the use case is "produce a capacity table once, archive it" — UI isn't load-bearing. |
| B. `locust` | Python-native, web UI, distributed support. Adds a dep + a different DSL ("locust users") that doesn't match how we already think about load. Overkill for v1 single-instance. |
| C. `wrk` (C, fast) | Ultra-fast; Lua scripting for variation. Adds a system dep outside Python; harder to integrate with eval YAML workload. Better when measuring raw HTTP throughput; ours is mostly LLM-call-bound, so wrk's speed advantage doesn't matter. |
| D. `k6` | Excellent dev UX but JavaScript-based. New language surface for a one-off measurement. |

**Choice: A.** The 80-line custom script reuses every primitive we
already have (httpx, asyncio, yaml.safe_load). The output is a JSON
file that downstream Phase 8.5 + 8.6 can parse mechanically.

## Workload design

### Source

Replay queries from the two eval surfaces already in the repo:

- `eval/answer_queries.yaml` (29 rows: 14 in-scope, 15 OOS)
- `eval/legalbench_br_oos.yaml` (49 rows: all OOS)

= **78 unique queries**, shuffled with replacement to fill each
concurrency level's request budget.

### Concurrency sweep

| Level | Total requests | Rationale |
|---|---:|---|
| 1 | 50 | warm cache baseline; matches Phase 8.0 conditions |
| 2 | 50 | smallest concurrency that exercises any locking |
| 4 | 100 | typical small-deployment traffic |
| 8 | 100 | Fly shared-cpu-1x ceiling (1 vCPU = ~4-8 concurrent I/O-bound requests) |
| 16 | 200 | over-subscribed CPU; measures contention |
| 32 | 200 | well into provider rate limit territory |
| 64 | 200 | stress; expect substantial errors |

Per-level run: open N parallel workers, each pulling from a shared
queue of (total_requests/N) requests. Stop after all complete.
Records per-request: latency, status, error type if any, cache hit
(via response presence at startup).

### Cache strategy — single-axis variable

**v1: warm cache, replay same 78 queries.** Eliminates the
provider-rate-limit confound from the capacity measurement — the
server is measured under its own load, not Maritaca's. Cold-cache
sweep is a separate axis worth measuring but deferred:

- Hot (cached) sweep → measures **server-side** capacity:
  request parsing, slowapi token-bucket lock contention,
  uvloop event-loop saturation, response serialization.
- Cold sweep → measures **upstream provider** capacity:
  Maritaca rate limits, network latency, Voyage embedder calls.

Mixing them in one test makes the bottleneck attribution ambiguous.
v1 ships hot only; cold sweep can land as Phase 8.4.1 if needed.

### Rate-limit disabled for the test

Set `RAG_RATE_LIMIT_PER_MINUTE=0` (= 1M/min effective) for the load
test process. The point is to measure capacity, not the rate
limiter's enforcement (already verified in Phase 8.2 tests).

## Pre-locked criteria

> Phase 8.4 ships iff:
> 1. **Harness exists**: `scripts/phase_8_4_load_test.py` runs the
>    concurrency sweep, writes per-request JSON, prints aggregate
>    table.
> 2. **Capacity table** covers at least 5 concurrency levels
>    (1, 4, 8, 16, 32).
> 3. **Server doesn't crash** at any concurrency level tested
>    (might error individual requests; process stays alive).
> 4. **Error rate** stays under 5% at concurrency ≤8 (Fly
>    shared-cpu-1x estimate); higher at 16/32 acceptable as
>    saturation signal.
> 5. **p95 latency knee identified**: the concurrency-vs-p95
>    curve shows a clear inflection point. The pre-knee p95
>    informs Phase 8.6 alerting threshold.
> 6. **Cost stays under $1**. Hot-cache test path should be
>    effectively $0 (all 78 queries' API calls cached from prior
>    Phase 8.0.1 A/B run); the cap is paranoia about misses.
> 7. **Findings doc** with: capacity table, bottleneck
>    identification, calibrated SLO numbers for Phase 8.6 alerting.

## Out of scope (explicit non-goals)

- **Distributed load** (multi-machine load generator). Single host
  is sufficient for the single-instance v1 server. Distributed
  becomes interesting in Phase 9 if horizontal scaling lands.
- **Sustained 24h soak test.** Memory leaks / connection-pool
  exhaustion over hours is a Phase 9 reliability concern.
- **Cold-cache adversarial workloads.** Defer to Phase 8.4.1 if
  capacity surface needs the data.
- **Provider rate-limit recovery testing.** Hitting the Maritaca
  ceiling and measuring recovery time. Not in 8.4's scope.
- **Soak test for queue-depth metrics.** OTel spans + log fields
  already provide the visibility; alerting uses thresholds, not
  trend lines.
- **Auth/rate-limit-effectiveness measurement.** Phase 8.2 unit
  tests already verify the mechanism; 8.4 doesn't re-test.
- **Multi-tenant scaling.** Single shared key in v1.

## Open design questions to resolve at sub-phase start

1. **Worker model: asyncio tasks vs threadpool?** Recommendation:
   **asyncio.gather** of N coroutines, each pulling from a
   `asyncio.Queue`. Single event loop, one process, low overhead.
   Threads only matter if the request-side work is CPU-bound; HTTP
   client work isn't.

2. **Cold-cache axis: ship now or defer?** Recommendation:
   **defer**. v1 ships hot; cold becomes Phase 8.4.1 if/when needed.
   Splitting the axes keeps the v1 findings doc focused.

3. **Pre-warming**: should the harness run a "pre-warm" pass at
   concurrency=1 to populate any in-process caches before the real
   sweep? Recommendation: **yes**. One pass through the 78 queries
   at concurrency=1 — already part of the cap=1 baseline level —
   guarantees the LLM cache is populated for the rest of the
   sweep. No extra cost; just sequencing.

4. **Report format**: JSON-only, JSON+CSV, JSON+CSV+chart?
   Recommendation: **JSON + a markdown table in the findings**.
   No chart for v1; if a chart adds value later, generate offline.

5. **Local server startup**: should the harness start its own server
   or assume one is running on localhost? Recommendation:
   **assume running**. Operator starts `uv run uvicorn rag_leis.server:app`
   in one terminal, runs the load test in another. Keeps the
   harness focused on one job (loading), not lifecycle management.

## Risk + tradeoff analysis

| Risk | Severity | Mitigation |
|---|---|---|
| Test misconfigured → real $$ spent | Medium | `--max-cost-usd` flag aborts the run if `cost_estimate_usd` rolling sum exceeds budget. Conservative default $1. |
| Local Maritaca calls hit account rate limit | Low | Cache pre-warmed; provider calls only if cache miss. Account-limit hit would surface as `429`/`529` on a few requests — recorded but doesn't fail the test. |
| Server load test slows down concurrent dev work | Low | Run on localhost; load is bounded by cap. |
| Event-loop blocking from sync code in pipeline | Medium | `pipeline.answer()` is sync; awaiting it via run_in_executor would matter at high concurrency. **Open question**: does the FastAPI endpoint already run sync handlers in a threadpool? (Yes — FastAPI wraps sync handlers in `run_in_threadpool`.) So this isn't load-bearing for the test, but it's worth noting. |
| Network noise on localhost-only tests | Very low | localhost is reliable; doesn't matter |

## Cost estimate

- **API spend**: **$0 to ~$0.50**. With cache pre-warmed via the
  cap=1 level, all subsequent levels hit cache. Some cost may
  arise if uvloop concurrency timing causes the LLM call's
  request-id to differ (it shouldn't — cache key is
  (system, user, tool_schema, max_tokens) not per-request).
- **Wall time**: ~1 session per entry plan (~3-4h) including:
  - harness script (~80 lines)
  - sweep execution (~5-10 min wall)
  - findings doc + plot
- **New deps**: none. httpx already pulled in; PyYAML already a
  base dep; asyncio is stdlib.

## Sequencing within 8.4

1. **Write the harness** `scripts/phase_8_4_load_test.py`:
   - Argparse for `--levels 1,4,8,16,32`, `--total-per-level 100`,
     `--api-key`, `--base-url`, `--out`, `--max-cost-usd`
   - Loads queries from both eval YAMLs
   - For each level: open N coroutines, each loops pulling from
     queue, records per-request `(latency_ms, status, cost_estimate_usd, error)`
   - Aggregates per-level: p50/p95/p99, error rate, throughput,
     mean cost
   - Writes JSON to `eval/runs/phase-8.4-load-test.json`
2. **Smoke run** at concurrency=1, total=5 to verify the harness
   talks to the server correctly. Confirm cache populates.
3. **Full sweep**: levels=1,2,4,8,16,32, total=50/50/100/100/200/200,
   `--max-cost-usd 1`. Capture results.
4. **Optional concurrency=64** if 32 didn't saturate.
5. **Findings doc** with table, identified bottleneck, calibrated
   SLO numbers.
6. **Tests**: add 1-2 unit tests for the harness's aggregation
   logic (no live server needed). Skip end-to-end test (covered by
   smoke run).

## What we'll learn that's not in this plan

- The actual concurrency knee — could be 4, 8, 16, or higher
  depending on uvloop + threadpool defaults.
- Whether FastAPI's sync-handler-in-threadpool wrapping is the
  bottleneck at high concurrency (FastAPI uses Starlette's default
  threadpool which is ~40 threads — should be fine).
- Whether the slowapi token-bucket has lock contention at high
  concurrency (probably not, since it's per-key not global, but
  worth confirming).
- Whether the OTel auto-instrumentor adds measurable overhead
  under load (Phase 8.3 measured ~3-5ms per request at
  concurrency=1; under-load behavior unknown).
- The provider rate-limit response shape (429? 529 Overloaded? both?)
  — useful for Phase 8.6 alerting taxonomy.

## SLO calibration outputs

The findings doc will produce three calibrated numbers Phase 8.6
will consume:

| Phase 8.6 alert | Phase 8.0 candidate | Phase 8.4 will refine |
|---|---|---|
| Latency p95 (short) | < 5s | will tighten to measured pre-knee p95 + 50% headroom |
| Cost mean per query | < $0.01 | likely stays at $0.01 (cache-warmed test = lower bound) |
| Error rate | < 1% | concurrency-dependent; will set per-tier thresholds |
| Saturation (req/s) | undefined | first measurement; sets capacity-planning baseline |

## Cross-references

- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — parent plan
- [`phase-8-0-prod-cost-baseline.md`](phase-8-0-prod-cost-baseline.md) — single-request baseline this extends to concurrency=N
- [`phase-8.3-structured-observability-findings.md`](phase-8.3-structured-observability-findings.md) — observability surface the load test will measure against
- `eval/answer_queries.yaml` + `eval/legalbench_br_oos.yaml` — workload sources
- `scripts/phase_8_4_load_test.py` — file we'll create
- `eval/runs/phase-8.4-load-test.json` — output
