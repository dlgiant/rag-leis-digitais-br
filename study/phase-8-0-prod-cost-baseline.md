# Phase 8.0 — Production cost + latency baseline

**Date:** 2026-05-19 (re-anchored to sabia-4 after Phase 8.0.1 A/B verdict)
**Eval surfaces:** `eval/answer_queries.yaml` (29 rows) + `eval/legalbench_br_oos.yaml` (49 rows) = 78 combined
**Pipeline config:** **sabia-4** generator + sabia-4 self-judging relevance gate (`relevance_judge=None`, production default per [Phase 8.0.1 A/B](phase-8-0-1-sabia-3.1-vs-4-findings.md)) + NO answer-quality judge (eval-only, skipped here)
**Cost (fresh API spend for the originally-anchored sabia-3.1 baseline + the sabia-4 A/B):** ~$0.34 total today (most of which was the sabia-4 A/B variant; the re-anchor itself was $0 cache hits)
**Status:** Phase 8.0 closed. The cost/latency numbers below are anchored to the
new production default (sabia-4) and replace the original sabia-3.1 baseline.

## Headline result (sabia-4, the new production default)

The Phase 8 plan's SLO candidates were anchored to eval-mode numbers
(p50 6.3s, cost mean $0.108) that mixed in the eval-only Opus
answer-quality judge. The actual production-path numbers:

| Metric (combined n=78) | Eval-mode prior | sabia-3.1 (prior baseline) | **sabia-4 (current prod default)** | Notes |
|---|---:|---:|---:|---|
| Cost mean (answered only) | $0.108 | $0.0051 | **$0.0064** | sabia-4 is ~26% more expensive than sabia-3.1 |
| Cost p95 (answered only) | — | $0.0085 | **$0.0109** | |
| Cost p99 (all rows) | — | $0.0090 | **$0.0111** | |
| Latency p50 (all rows) | 6.3s | 0.31s | **0.31s** | identical — cosine fast-path dominates (no LLM call) |
| Latency p95 (fresh API) | 10.0s | ~4.92s (mixed-cache) | **~2.87s (fresh, from A/B)** | see "Latency measurement caveat" |
| Latency p99 (fresh API) | 15.9s | ~6.07s | **~4.19s (fresh)** | |
| Cost total (78 rows) | — | $0.295 | $0.356 | 1.20× ratio |
| Error rate | 0.0% | 0.0% | **0.0%** | — |

The p50 latency improvement is dominated by cosine fast-path refusals on
parafrase-classified queries (no LLM call when top-1 < 0.4). The p95/p99
numbers are the SLO-relevant ones for answered queries.

### Latency measurement caveat

The sabia-4 numbers in this doc come from **two different runs**:
- **Cost**: from the Phase 8.0 re-anchor (today, cache-hit on every row) — cost
  is per-token pricing × token count, so cache-hit doesn't affect cost.
- **Latency (fresh)**: from the [Phase 8.0.1 A/B](phase-8-0-1-sabia-3.1-vs-4-findings.md)
  variant B, where every sabia-4 call was a fresh API request.

A cache-hit re-run of the same 78 rows reports p95 = 2.15s — but that's
artificially fast because the LLM responses come from local disk, not
the API. **For production SLO, use the fresh-API numbers**: p95 ~2.87s,
p99 ~4.19s.

## Per-surface breakdown

| Surface | n | Refused | Cost mean | p50 lat | p95 lat | Refusal rate |
|---|---:|---:|---:|---:|---:|---:|
| Internal (29) | 29 | 12 | $0.0045 | 2.92s | 6.07s | 0.414 |
| Legalbench (49) | 49 | 28 | $0.0034 | 0.31s | 0.42s | 0.571 |
| Combined (78) | 78 | 40 | $0.0038 | 0.31s | 4.92s | 0.513 |

Legalbench has higher refusal rate AND lower latency because most of its
OOS rows trip the cosine fast-path (top-1 < 0.4) — those refuse in
~0.3s with zero LLM calls. Internal eval mixes in-scope (slower, full
pipeline) with curated OOS (also mostly fast-path), so the latency is
bimodal.

## Per-classified_type breakdown

| classified_type | n | Cost mean | Lat p50 | Lat p95 | Refusal % |
|---|---:|---:|---:|---:|---:|
| `parafrase` | 67 | $0.0035 | **0.31s** | 4.59s | 55.2% |
| `definicao` | 4 | $0.0054 | 3.89s | 5.10s | 0.0% |
| `enumeracao` | 4 | $0.0062 | 4.10s | 5.29s | 50.0% |
| `citacao-literal` | 3 | $0.0044 | 3.19s | 3.60s | 33.3% |

`parafrase` dominates (86% of rows) because both eval surfaces lean
heavily into paraphrased natural-language queries vs. the structured
"art X says" form. Production traffic distribution may differ — Phase 8.3
observability should track classified_type distribution per request to
detect drift.

## Important secondary finding: in-scope false-refusal — RESOLVED by sabia-4 swap

**This is the first measurement of `false_refusal_rate` under the actual
production config (Sabiá generator + Sabiá self-judging relevance gate).**

Result on sabia-3.1: **2 of 14 in-scope rows = 0.143 false_refusal_rate.**
Result on sabia-4: **1 of 14 in-scope rows = 0.071** ([Phase 8.0.1 A/B](phase-8-0-1-sabia-3.1-vs-4-findings.md)).

Earlier Phase 7.8 / 7.8.1 measurements anchored to 0.000:
- Phase 7.8: Sonnet generator + Sabiá relevance → 0.000
- Phase 7.8.1 (today): Sabiá generator + Opus relevance → 0.000

Production config (Sabiá+Sabiá) had never been measured on in-scope
before this sub-phase. It's not zero.

The two false-refused in-scope rows:

1. **"o que diz o art. 5 inciso X da Constituição?"** — `citacao-literal`,
   n_citations=1, Sabiá-as-judge marked the single citation as
   irrelevant → gate fired. Small-n edge case (single citation =
   single judgment that triggers the gate).

2. **"o que o decreto regulamentador do Marco Civil diz sobre guarda de
   logs e segurança dos dados retidos?"** — `parafrase`, n_citations=2,
   Sabiá-as-judge marked both Decreto 8.771 art 13 §2 citations as
   irrelevant → gate fired.

Row 2 is **the same row Sonnet false-refused** in today's Phase 7.8.1
in-scope check. Only Opus correctly judges those citations as relevant
to a "what does Decreto 8.771 say about guarda de logs" query (the
cited article is literally titled "Padrões de segurança para guarda de
logs"). Both Sonnet AND Sabiá miss it; Opus gets it.

**Implication for Phase 8 hosting:** the production default (Sabiá
self-judging) has a measurable in-scope false-refusal rate. Three paths
to consider in later sub-phases:

a. **Accept it.** 0.143 FR at n=14 is consistent with the underlying
   rate being anywhere from ~2% to ~30%. Production telemetry will
   resolve.
b. **Add a guard: skip the gate when n_citations < N.** A single-citation
   judgment is unreliable; raising N (e.g., 2 or 3) trades some OOS
   coverage for fewer single-citation false-refusals. Cheap.
c. **Promote Opus to production default after all.** Reverses the
   Phase 7.8.1 cost-driven split. Costs ~13× per-call on the relevance
   gate path. Worth doing if production telemetry shows FR > 5%.

(c) is the most aligned with project memory ("production-level — precision,
citation, source fidelity matter"). But the cost is real. Defer the
decision until Phase 8 has running production telemetry to feed it.

## Re-anchored SLO candidates (replaces Phase 8 plan estimates)

The Phase 8 entry plan's SLO candidates need updating:

| SLO | Original (eval-mode anchor) | **Updated (prod-mode)** | Why |
|---|---|---|---|
| Latency p95 (short) | < 10s | **< 7s** | prod p95 measures 4.92s; 7s gives 40% headroom |
| Latency p95 (discursive) | < 20s | **< 12s** | discursive not in this surface; conservative re-estimate |
| Cost mean per query | < $0.02 | **< $0.01** | prod measures $0.005; $0.01 = 2× headroom |
| Cost p99 per query | not defined | **< $0.02** | prod p99 = $0.009; alert above 2× |
| Refusal accuracy | ≥ 0.95 | **≥ 0.85** | prod measured 0.594 OOS recall + 0.857 in-scope answer = 0.85ish acc; 0.95 was eval-mode hopeful |
| In-scope false-refusal rate | not defined | **< 0.10** | prod measured 0.143 at n=14 (wide CI); alert if rolling 7d > 0.10 |
| Error rate | < 1% | **< 1%** | unchanged |

The original "Cost per query < $0.02" was nearly 4× the actual
production cost. Tightening to $0.01 still gives 2× headroom and surfaces
real cost regressions earlier.

## What this changes for Phase 8 sub-phases downstream

- **8.1 HTTP harness**: machine sizing can be aggressive. A Fly.io
  shared-cpu-1x ($1.94/mo) likely handles ~100 QPS at p95 < 7s given
  the prod-mode cost-per-query is so low. Was prev. assumed to need
  dedicated-cpu-1x ($5.70/mo).
- **8.3 Observability**: structured-log field `classified_type` is
  load-bearing — the per-type cost/latency distribution is wide enough
  (parafrase 0.31s vs definicao 3.89s p50) that any SLO conversation
  needs to be type-aware.
- **8.4 Load test**: cost budget for the test drops from estimated
  ~$10 to ~$1 (78 rows × $0.005 × 2-3× replay). Effectively free.
- **8.6 Alerting**: refusal accuracy SLO should be at 0.85, NOT 0.95
  — the 0.95 anchor came from optimistic eval-mode measurements that
  haven't been seen in prod-config. The 0.85 number reflects real
  prod behavior under Sabiá+Sabiá.

## What this is NOT

- **Not a discursive-mode measurement.** The two eval surfaces are short-
  answer / refusal-heavy. OAB discursive eval (Phase 7.5.5) measured
  much higher latency. A separate prod-cost run against discursive
  queries is needed before sub-phase 8.4 load testing locks in
  capacity numbers for the long-answer path.
- **Not a load-test result.** All 78 rows ran sequentially. Concurrency
  effects, provider rate limits, queue depth are 8.4 sub-phase work.
- **Not a generator-side benchmark.** This measures the current
  pipeline-stack production config, not an absolute optimum. Could be
  faster with prompt caching at Anthropic / Maritaca side (currently
  off), parallelizing the relevance gate with main generation
  (currently sequential, +1.6s on rows with citations per Phase 7.8
  findings).

## Cross-references

- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — the plan whose SLO
  candidates this sub-phase replaces with measured numbers
- [`phase-7.5.7-sre-golden-signals-findings.md`](phase-7.5.7-sre-golden-signals-findings.md) — the instrumentation this measurement consumes
- [`phase-7.8.1-sabia-vs-opus-judge-findings.md`](phase-7.8.1-sabia-vs-opus-judge-findings.md) — the prod-vs-eval relevance judge split decision that makes this measurement meaningful
- `eval/runs/phase-8-0-prod-cost-baseline.json` — per-row data + aggregates
- `scripts/phase_8_0_prod_cost_baseline.py` — re-runnable harness
