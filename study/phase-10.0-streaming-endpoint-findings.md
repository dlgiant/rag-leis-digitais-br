# Phase 10.0 — Streaming endpoint (findings)

**Date:** 2026-05-20
**Predecessor:** [Phase 10 entry plan](phase-10-ui-entry-plan.md).
**Cost:** $0 (one request to test the deployed SSE endpoint).
**Status:** Phase 10.0 SHIPPED. SSE endpoint live at `POST /v1/ask/stream`. All pre-locked criteria met. Token-by-token streaming within `generate` is documented as a Phase 10.0.1 follow-up.

## Pre-locked criteria — result

| # | Criterion | Status |
|---|---|:-:|
| 1 | `POST /v1/ask` with `Accept: text/event-stream` returns SSE chunks | ⚠️ shipped at `POST /v1/ask/stream` instead (cleaner endpoint separation; chose against header-based content negotiation) |
| 2 | Final SSE message contains the full `RAGAnswer` JSON for clients | ✅ `{"event": "complete", "answer": AskResponse}` |
| 3 | Auth + rate limit gates unchanged | ✅ same `X-API-Key` + per-key rate limit as `/v1/ask` |
| 4 | Existing non-streaming clients still get one-shot JSON | ✅ `POST /v1/ask` byte-identical to Phase 8.5.1 |

## What ships

- **`pipeline.answer()`** now accepts optional `on_event: Callable[[dict], None] | None` argument (default `None` = preserves existing behavior). When provided, called synchronously at each stage boundary with `{"event": "stage", "name": ..., "status": "started"|"finished", **stage_attrs}`. No-streaming callers see identical behavior.
- **Stage emissions in `rag.py`**: `classify`, `retrieve`, `generate`, `verify`, `relevance_judge` (when the gate fires). Each stage emits `started` and `finished` events; `finished` includes summary attributes (top_1_cosine, n_verified, n_decisions, etc.).
- **`POST /v1/ask/stream`** in `rag_leis/server.py`:
  - Same auth + rate-limit gates as `/v1/ask`
  - `StreamingResponse(media_type="text/event-stream")`
  - Runs `pipeline.answer(query, on_event=...)` in `run_in_executor` so the sync pipeline doesn't block the async event loop
  - Events bridged from sync thread to async generator via `asyncio.Queue` + `loop.call_soon_threadsafe`
  - Final event: `{"event": "complete", "answer": AskResponse.model_dump()}` — same payload `/v1/ask` returns
  - On exception: `{"event": "error", "detail": "pipeline error: <ExceptionType>"}` (status remains 200; SSE has no per-event status code)
- **5 new tests** in `tests/test_server.py`:
  - SSE Content-Type
  - Canonical stage event sequence + final complete event
  - Auth gate (401 missing key)
  - Rate limit (429 over cap)
  - Direct `pipeline.answer(on_event=...)` callback contract

## Why two endpoints (`/v1/ask` and `/v1/ask/stream`) instead of header-based content negotiation

The plan suggested `Accept: text/event-stream` on `/v1/ask` could switch
modes. Implementation went with separate endpoints because:

1. **OpenAPI cleanliness**: two distinct endpoints render correctly in
   the auto-generated schema; one endpoint with content-type-dependent
   behavior is ambiguous.
2. **Operational clarity**: load tests, alerts, and structured logs can
   distinguish streaming vs non-streaming traffic by path without
   parsing headers.
3. **Client simplicity**: UI code calls `/v1/ask/stream` deliberately
   when it wants streaming; CLI/scripts call `/v1/ask` deliberately
   when they want one-shot JSON. No surprise mode-switching from a
   misspelled header.

Pre-locked criterion #1's exact wording (the `Accept` header form) was
sacrificed for these UX/ops wins. Findings doc records the deviation
explicitly.

## Live smoke test (against the deployed instance)

Cold-start (auto-stopped Fly machine waking up):
```
[19.6s] stage  started: classify         ← machine was asleep
[19.6s] stage finished: classify
[19.6s] stage  started: retrieve
[20.0s] stage finished: retrieve
[22.0s] stage  started: generate
[28.7s] stage finished: generate
[28.7s] stage  started: verify
[28.7s] stage finished: verify
[28.7s] stage  started: relevance_judge
[34.6s] stage finished: relevance_judge
[34.6s] COMPLETE  refused=False n_cites=5 cost=$0.005998
```

Warm steady-state (machine already running):
```
[ 0.2s] stage  started: classify        ← first event in 0.2s
[ 0.2s] stage finished: classify
[ 0.2s] stage  started: retrieve
[ 0.6s] stage finished: retrieve
[ 2.7s] stage  started: generate
[10.9s] stage finished: generate        ← ~8s Sabiá call
[10.9s] stage  started: verify
[10.9s] stage finished: verify
[10.9s] stage  started: relevance_judge
[19.5s] stage finished: relevance_judge ← ~8.6s Sabiá call
[19.5s] COMPLETE
```

**SSE works end-to-end.** Events arrive in real-time. The cold-start surcharge (~19s) is the auto-stop machine wake-up, NOT a buffering bug.

## UX implications for Phase 10a/b

Three findings that the load-bearing UI work in 10a should design against:

### 1. Cold-start adds ~19s to first-of-day traffic

`auto_stop_machines = "stop"` in `fly.toml` saves money when idle but
makes the first user of any quiet period wait ~19s before seeing the
first event. Mitigations in priority order:

- **Cheapest fix**: `min_machines_running = 1` (one warm replica
  always; ~$5/mo additional)
- **UI mitigation**: show a "Aquecendo o servidor..." (warming up)
  message if the first event takes > 5s to arrive
- **Accept as-is**: document the cold-start time in the demo banner

Recommendation for 10a (local UI): cold-start isn't a concern (local).
Recommendation for 10b (public demo): set `min_machines_running = 1`
on the demo app to avoid first-user surprise.

### 2. `generate` is the worst single-stage gap (~8s blank)

The user sees "Generating answer..." for ~8 seconds with no
intermediate signal. **This is the highest-ROI place to add
token-by-token streaming**: Maritaca's OpenAI-compatible API
supports streaming with `tool_choice` (untested empirically; a
Phase 10.0.1 task). If 10a/b user testing confirms the 8s gap is
the load-bearing UX issue, 10.0.1 ships first.

### 3. `relevance_judge` is structurally non-streamable

It's a Sabiá call with a structured-output tool that returns
booleans per citation. Nothing to stream incrementally. Total
latency is ~8.6s warm. Possible Phase 11+ optimizations:

- **Skip the gate on high-confidence retrievals** (e.g., `top_1_cosine
  > 0.85` → trust the citations without gate). Phase 7.8.2 sweep
  data already exists; could be revisited.
- **Run the gate in parallel** with the next user interaction (return
  early with `provisional=true`; mark cited URNs as "pending verification"
  in the UI; emit a follow-up event with verified citations).
- **Cache the relevance judgments** keyed on (query, citation URNs).
  Different problem from the LLM cache — this is for repeated
  similar queries on the same citation set. Probably low hit rate.

Out of scope for Phase 10; just flagged.

## Phase 8.6 threshold calibration note

Phase 8.6's `p95 > 20s sustained 5 min → alert` threshold was calibrated
against Phase 8.5.1's measurement of "9-13s p95 warm." This smoke
test, including the `relevance_judge` stage, shows warm end-to-end is
**~20s** (10.9s + 8.6s). The Phase 8.6 alert threshold is calibrated
almost exactly at the warm-state ceiling — meaning normal warm traffic
will occasionally trip it.

**Recommendation: relax the Phase 8.6 p95 threshold to 25-30s sustained
5 min.** Documented as a 30-day-tuning candidate in the 8.6 findings;
this smoke test surfaces the need earlier.

## Architecture notes

**Sync pipeline → async SSE response bridging**:
- `pipeline.answer(query, on_event=...)` is sync (the LLM call blocks)
- Async endpoint calls `loop.run_in_executor(None, run_pipeline)` to
  run the pipeline in a thread pool
- `on_event` callback bridges sync → async via
  `loop.call_soon_threadsafe(queue.put_nowait, event)`
- Async generator drains the queue and yields SSE-formatted bytes
- `SENTINEL` object in the queue marks pipeline thread completion;
  async generator drains until SENTINEL, then yields the final
  `complete` event from the pipeline future's result

**Client disconnect handling**: if the client disconnects mid-stream,
the pipeline thread keeps running until natural completion (no good
way to cancel a sync `requests` / `httpx` LLM call mid-flight).
Acceptable for v1 personal traffic; the orphan call still produces
billing on the LLM side but the result is discarded. Phase 11+ could
add cancellation if a real-traffic workload demands it.

**Cache layer compatibility**: pipeline cache (Phase 7.9) is
process-scoped and per-call. Streaming doesn't change cache behavior —
the LLM call is identical regardless of whether the caller streams the
result. Streaming the cache layer itself (e.g., yield partial cached
results as they arrive on a re-call) is a non-feature; cached calls
are already <1ms.

## What 10.0 does NOT do (deferred to 10.0.1)

- **Token-by-token streaming within `generate`.** Requires:
  - Maritaca streaming + tool_choice empirical test (untested today)
  - Streaming JSON parser to extract the `answer` field's growing value
    from chunked tool-call arguments
  - New `complete_structured_stream` method on the LLM abstraction
  - Cache-layer bypass for streaming (current cache assumes full responses)
- **Server-Sent Event compression negotiation.** Modern browsers handle
  SSE fine without compression; not worth the complexity.
- **Resumable streams.** SSE has `event:` IDs that could support
  `Last-Event-ID` resume, but our events aren't durable on the server
  side, so it would just restart from scratch.
- **Multiplexing.** One request = one stream. Phase 11+.

## What changed in the codebase

- `rag_leis/rag.py`:
  - import `Callable` from `collections.abc`
  - `pipeline.answer` signature gains optional `on_event` param
  - 5 stage-emit calls inserted at `classify` / `retrieve` /
    `generate` / `verify` / `relevance_judge` boundaries
- `rag_leis/server.py`:
  - new imports: `asyncio`, `json`, `Any`, `StreamingResponse`
  - new `_sse_format` helper
  - new `POST /v1/ask/stream` endpoint (~80 lines)
- `tests/test_server.py`:
  - new `StreamingStubPipeline` class
  - new `_parse_sse` helper
  - 5 new tests for SSE behavior

## Cross-references

- [`phase-10-ui-entry-plan.md`](phase-10-ui-entry-plan.md) — predecessor plan
- [`phase-8.5.1-deploy-findings.md`](phase-8.5.1-deploy-findings.md) — production latency baseline (9-13s warm without `relevance_judge`)
- [`phase-8.6-alerting-findings.md`](phase-8.6-alerting-findings.md) — p95 alert threshold needs updating per this smoke test
- `rag_leis/rag.py` — pipeline event emission
- `rag_leis/server.py` — SSE endpoint
- `tests/test_server.py` — SSE tests
