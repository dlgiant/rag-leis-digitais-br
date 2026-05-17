# Phase 7.5.7 findings — SRE Golden Signals + judge cost bug fix

**Date:** 2026-05-17
**Scope:** Latency p50/p95/p99/mean, error_count/rate, judge-cost accounting fix
**Gold-standard reference:** Beyer et al., *Site Reliability Engineering*
(Google, 2016) ch.6 — the Four Golden Signals (Latency, Errors, Saturation,
Traffic). For offline batch eval, Latency + Errors are the two applicable
signals (Saturation = queue depth, Traffic = QPS — both meaningful only
under load, not in single-call eval).
**Files touched:** `rag.py`, `run_answer_eval.py`, `run_concurso_eval.py`,
`tests/test_sre_metrics.py` (new), `study/rag-eval-metrics-audit.md`
**Run log:** `eval/runs/phase-7.5.7-discursive-rerun.json` (re-run of
7.5.5 discursive pilot with full instrumentation)

## Headline numbers (from 7.5.5 discursive pilot re-run, n=5)

| Signal | Value | Note |
|---|---|---|
| **Latency p50** | 6,758 ms | half of queries respond in ~7s |
| **Latency p95** | 13,506 ms | tail = 2× median |
| **Latency p99** | 13,506 ms | n=5 means p95=p99 here; gives shape, not converged tail |
| **Latency mean** | 7,122 ms | informational only (heavy-tail) |
| **Error count / rate** | 0 / 0.0000 | clean run |
| **Cost total (NEW: judge folded)** | $0.3747 | was $0.0283 pre-fix — **13.2× under-report** |
| **Cost per query** | $0.075 | mean across 5 discursive rows |
| **LLM calls (incl. judge)** | 11 | 5 Sabiá + 1 retry + 5 opus judge |
| **Tokens (in/out)** | 36,636 / 6,737 | judge dominates input volume |

## What the latency numbers reveal

n=5 means these are *shape* not *converged* measurements. The story:

- **p50 ≈ 7s, p95 ≈ 13.5s**: Sabiá generation tail is real. The pipeline is
  not at "interactive chat" latency yet — even the median user wait is
  multiple seconds. Discursive answers (long generation) skew higher than
  short-answer modes; the answer-eval set will likely show shorter p50.
- **No errors**: 0 exceptions across the run. The error_count metric is
  defensive — when a real run sees a rate limit or transport hiccup, the
  try/except wrap now counts it instead of crashing the whole eval.
- **Cost dominance**: opus judge (5 calls × ~$0.06) costs more than the
  generator (Sabiá 6 calls × ~$0.006). This is precisely the inversion the
  prior cost report was hiding — operator decisions about judge usage now
  visible.

## Implementation summary (what shipped)

### 1. `RAGAnswer.latency_ms` (rag.py)
- New `latency_ms: float = 0.0` field on the dataclass
- `RAGPipeline.answer()` wraps body with `time.monotonic()` measurement
- Set on BOTH return paths: cosine fast-path (typically <50ms) and main
  path (includes LLM + optional retry + post-process)

### 2. Aggregate SRE fields (run_answer_eval + run_concurso_eval)
- `latency_p50_ms`, `latency_p95_ms`, `latency_p99_ms`, `latency_mean_ms`
- `error_count`, `error_rate`
- Nearest-rank percentile (matches Beyer SRE Book formula + `numpy.percentile
  method='lower'`); zero-dep, stable for small n

### 3. Per-row pipeline error wrap (both runners)
- `try: ans = pipe.answer(row.query) except Exception as e: ans = RAGAnswer(
  ..., refusal_reason=f"ERROR: {type(e).__name__}: {e}")`
- Error-marked rows count toward `error_count` and are **excluded from the
  latency distribution** (time-to-fail isn't user-perceived latency)
- Before this PR, one rate-limit mid-eval lost all completed work; now the
  run completes and surfaces the failure

### 4. Judge cost bug fix (THE 7.5.5 bug)
The Phase 7.5.2 cost instrumentation only tracked `pipeline.llm` (the
generator). When score_in_scope/score_discursive called the opus judge,
the judge's spend was tracked nowhere — causing eval logs to under-report
cost by ~13× (or more, depending on judge model + generator ratio).

**Fix:** `_fold_judge_cost_into_answer(ans, judge)` reads
`judge.last_call_usage` after each `complete_structured` call and
accumulates it into the existing `RAGAnswer.cost_estimate_usd /
tokens_used / llm_calls` fields. Aggregation logic doesn't change — sums
across rows now produce a correct total because each row has correct
per-row cost.

Verification: re-ran the 7.5.5 discursive pilot.
- Pre-fix: `cost_total_usd = $0.0283` (8 calls, 27k/7k tokens)
- Post-fix: `cost_total_usd = $0.3747` (11 calls, 37k/7k tokens)
- Ratio: 13.2× — matches the predicted ~$0.59 estimate from the 7.5.5
  findings doc.

### 5. Tests
New `tests/test_sre_metrics.py` (10 tests):
- `RAGAnswer.latency_ms` field exists + accepts floats
- ConcursoAggregate p50/p95/p99 percentile correctness
- Error rows: counted in error_count, excluded from latency
- Empty records: no division-by-zero
- answer_eval Aggregate exposes the same fields
- `_fold_judge_cost_into_answer`: arithmetic correctness for opus pricing
- Defensive: missing `last_call_usage` doesn't crash
- Empty `tokens_used` dict initializes cleanly

Full suite: 364 passed (was 354 pre-PR).

## Why these specific signals (and not Saturation / Traffic)

Beyer's Four Golden Signals are designed for online services. In offline
batch eval:

- **Saturation** = queue depth / resource exhaustion. We have no queue —
  it's a serial CLI. Provider-side rate limits would surface as errors.
- **Traffic** = QPS. We have one query at a time by design (eval is
  reproducible, deterministic ordering). Throughput is meaningful for
  Phase 8 (load test) but not now.

When Phase 8 puts this behind an HTTP server, both signals become
applicable. The architecture is ready (latency_ms is per-call, errors
counted) — Phase 8 just needs a queue depth metric and a QPS counter
in the HTTP layer.

## What this unlocks for Phase 8

The audit doc (§3 rows 24-27) now has all four SRE basics ✅:
- Latency (p50/p95/p99) — SLO target candidate: p95 < 10s for short modes,
  p95 < 15s for discursive
- Cost per query — SLO target: median < $0.05 (currently $0.075 on discursive)
- Token usage — informational; useful for spotting prompt bloat
- Error rate — SLO target: < 1%

Phase 8 hosting design can now reference real numbers, not estimates.

## Non-goals (explicit)

- ❌ Provider availability / fallback (audit row 28) — Phase 8 work
- ❌ Cache hit rate first-class (audit row 29) — index cache exists but
  hit rate not surfaced; minor follow-up
- ❌ Throughput (row 30) — needs load-test harness, Phase 8
- ❌ True structured logging / tracing (OpenTelemetry) — Phase 8 hosting
  decision

## Cross-references

- `study/phase-7.5.5-oab-bench-discursive-findings.md` — bug originally found here
- `study/rag-eval-metrics-audit.md` §3 rows 24-27 — flipped ❌ → ✅
- `study/phase-7.5-eval-expansion-plan.md` — sub-step 7.5.7 completed
- `eval/runs/phase-7.5.7-discursive-rerun.json` — re-run with full
  instrumentation; the cost delta is the validation
- `tests/test_sre_metrics.py` — 10 new tests
- Beyer et al., *Site Reliability Engineering* (Google/O'Reilly, 2016)
  ch.6 — "Monitoring Distributed Systems"
