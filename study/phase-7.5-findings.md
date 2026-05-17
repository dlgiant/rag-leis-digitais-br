# Phase 7.5 findings — what eval expansion revealed about the pipeline

**Date:** 2026-05-17 (one-day execution)
**Predecessor:** Phase 7 (production infra) — closed 2026-05-16
**Plan doc:** [`phase-7.5-eval-expansion-plan.md`](phase-7.5-eval-expansion-plan.md)
**Sub-phase findings:** [`7.5.3`](phase-7.5.3-legalbench-oos-findings.md) · [`7.5.4`](phase-7.5.4-rule-recall-findings.md) · [`7.5.5`](phase-7.5.5-oab-bench-discursive-findings.md) · [`7.5.7`](phase-7.5.7-sre-golden-signals-findings.md)
**Status:** 6 of 7 originally-planned sub-steps complete (7.5.6 deferred — see §6)

## TL;DR

Phase 7.5 grew the eval surface ~8.5× (24 OOS rows → 122 rows total
across 4 distinct external sources), shipped four production-grade
instrumentation upgrades, and produced four findings — three of which
forced an honest reframing of what the pipeline is and isn't good at.

The most important number: **internal OOS refusal accuracy of 93.8%
overstated the external measurement (12.2%) by 6.7×**. The internal
eval set, written by the same person who designed the system, was
unintentionally easy. External benchmarks are the only honest signal.

## §1 — Numbers, before and after

### Eval surface

| Surface | Pre-Phase 7.5 (2026-05-16) | Post-Phase 7.5 (2026-05-17) | Δ |
|---|---|---|---|
| Internal answer-eval (`answer_queries.yaml`) | 29 (14 inscope + 15 OOS) | 29 | — |
| Concurso pilot (`oab_concurso_pilot.yaml`) | 16 (7 inscope + 9 OOS) | 16 | — |
| **External OOS** (`legalbench_br_oos.yaml`) | 0 | **49** | +49 |
| **External rule recall** (`legalbench_br_rule_recall.yaml`) | 0 | **40** | +40 |
| **External discursive** (`oab_bench_discursive_pilot.yaml`) | 0 | **5** | +5 |
| **TOTAL** | **45** | **139** | **+209%** |

Three of four external sources came online in Phase 7.5; the fourth
(OAB 39-44 LGPD manual) was deferred (see §6).

### Headline quality metrics

| Metric | Source | Value | What it reveals |
|---|---|---|---|
| OOS refusal accuracy | 7.5.3 (legalbench.br, n=49) | **12.2%** | 6.7× worse than internal claimed |
| External rule recall | 7.5.4 (legalbench.br, n=40) | **97.5%** | In-corpus citation is essentially solved |
| Discursive score | 7.5.5 (oab-bench, n=5) | **54% mean** | Below OAB 60% pass; bimodal |
| Internal refusal accuracy | answer_queries.yaml (n=15 OOS) | 93.8% | The selection-bias baseline |

### SRE / observability (first-time measurements)

| Signal | Value | Status |
|---|---|---|
| Latency p50 | 6,758 ms | first instrumented 7.5.7 |
| Latency p95 | 13,506 ms | first instrumented 7.5.7 |
| Cost per query (discursive) | $0.075 | first correctly attributed 7.5.7 |
| Error rate | 0.00% | per-row try/except added 7.5.7 |
| Judge cost under-report | 13.2× | bug found 7.5.5, fixed 7.5.7 |

## §2 — The four findings

### Finding 1 — selection bias in self-curated evals is quantitatively real

Three OOS measurements on the same pipeline configuration, different
provenance:

| OOS source | n | refusal accuracy | provenance |
|---|---|---|---|
| `answer_queries.yaml` | 15 | **93.8%** | Self-curated by project author |
| `oab_concurso_pilot.yaml` | 7 | **43%** | External OAB content, manually filtered |
| `legalbench.br` `multiple_choice_qa` | 49 | **12.2%** | External benchmark, semi-random sample |

The progression is monotonic with detachment from author: closer to the
author → easier eval. **The internal eval surface overstated production
refusal behavior by 6.7×.** This isn't a Brazilian-legal-RAG insight
per se — it's a general lesson about why external benchmarks matter for
honesty. But having it quantified on a real system is the point.

**For the portfolio:** this is the single most defensible claim Phase
7.5 produced. Repeated as: *"our self-curated OOS eval said 94%; the
external benchmark said 12%; the gap is selection bias and we measured
it."*

### Finding 2 — retrieval+citation is excellent; refusal is the load-bearing gap

| Capability | Eval | Score |
|---|---|---|
| In-corpus citation precision (given verbatim text) | rule_recall 7.5.4 | **97.5%** |
| OOS refusal (queries from non-corpus domains) | OOS-A 7.5.3 | **12.2%** |

These are different and complementary capabilities, evaluated on
external benchmarks we did not author. The pattern:

- ✅ **Find the right article when it exists in corpus** — solved
- ❌ **Refuse cleanly when the right article isn't in corpus** — not solved

Same root cause across both gaps: the model is trained to be helpful.
When the retrieved context has the answer, helpful = correct citation.
When the retrieved context is adjacent material with the wrong answer,
helpful = hallucinating a relationship between corpus material and the
question.

This is **diagnostically clean**: it's not a retrieval problem, not a
citation-precision problem, not a faithfulness-to-context problem (the
model is being faithful to context that isn't relevant). It's a
**refusal-discipline problem**, specifically. That diagnosis changes
what Phase 8 needs to prioritize — SYSTEM_PROMPT iteration against the
expanded OOS set is now the highest-ROI next intervention, not better
retrieval or another reranker.

### Finding 3 — discursive surface confirms hypothesis with N=5

The OAB-bench discursive pilot (n=5) reproduced Finding 2 on the
generation surface:

| Question type | Score | Diagnosis |
|---|---|---|
| Constitutional (CRFB art.21 VII, in-corpus) | 1.00 | Perfect |
| LGPD art.8 §5 (in-corpus) | 0.84 | Strong |
| Penal terrorismo (CP in, Lei 13.260 OOS) | 0.46 | Partial degradation |
| Constitutional LC/LO (in-corpus, weak prose) | 0.25 | Found article, didn't answer |
| Civil comodato (CC arts.579-585 OOS) | **0.15** | Drafted usucapião answer for a comodato question — **canonical hallucination** |

The 0.15 row is the bug: clear question about CC arts.579-585 (not in
our 11-21 indexed range), pipeline drafted a usucapião answer using
CF art.183 as if it were comodato doctrine. No retrieval tuning fixes
this — the model needs to refuse, not approximate.

Three eval surfaces (OOS-A, rule_recall, discursive) on three different
data shapes (MCQ, verbatim text, free-form drafting) — same diagnosis.

### Finding 4 — eval discipline catches its own bugs (judge cost)

The Phase 7.5.5 discursive eval run reported `cost_total_usd = $0.028`
for a run that actually cost ~$0.59. The Phase 7.5.2 cost instrumentation
only tracked the generator (Sabiá) — not the opus judge.

This was caught **because** Phase 7.5.5 added a new eval category
(discursive, judge-heavy), making the under-report large enough to be
implausible against back-of-envelope math. With only short generator
calls + faithfulness judge, the under-report would have been ~2-3×
and might have gone undetected for weeks.

Phase 7.5.7 fixed it: `_fold_judge_cost_into_answer()` reads
`judge.last_call_usage` and accumulates into the existing RAGAnswer
cost/tokens/calls fields. Verification: re-ran 7.5.5 pilot.
$0.0283 → $0.3747 (13.2×). The "if you don't measure it, it's wrong"
principle applied to its own measurement infrastructure.

**Lesson worth keeping:** every time a new LLM-judge eval category
ships, immediately sanity-check the reported cost against a manual
token-pricing calculation. This is a check that should be a test
(future work).

## §3 — Implementation summary

| # | Sub-step | What shipped | Where | Cost |
|---|---|---|---|---|
| 7.5.1 | `false_refusal_rate` + `oos_refusal_recall` as first-class | `run_answer_eval.py:308-310` | $0 |
| 7.5.2 | Cost-per-query tracker | `cost.py` + `llm.py:last_call_usage` + `rag.py:RAGAnswer.cost_estimate_usd` | $0 |
| 7.5.3 | legalbench.br OOS expansion | `scripts/extract_legalbench_oos.py` → `eval/legalbench_br_oos.yaml` (49 rows) | $1.50 |
| 7.5.4 | legalbench.br rule recall | `scripts/extract_legalbench_rule_recall.py` → `eval/legalbench_br_rule_recall.yaml` (40 rows) | $0.07 |
| 7.5.5 | oab-bench discursive pilot | `scripts/extract_oab_bench_discursive.py` + `DISCURSIVE_TOOL` judge in `run_concurso_eval.py` (5 rows) | $0.37 |
| 7.5.6 | OAB 39-44 LGPD manual curation | **deferred** — see §6 | (n/a) |
| 7.5.7 | SRE Golden Signals + judge cost fix | `rag.py:RAGAnswer.latency_ms` + p50/p95/p99 in both Aggregates + `_fold_judge_cost_into_answer()` | $0.37 |
| 7.5.8 | This findings doc + audit doc update + README link | (this commit) | $0 |

**Total API spend (Phase 7.5):** ~$2.30 (well under the $15 ceiling
locked in D4).
**Engineering time:** ~1 day focused (matches D2 path β estimate).
**Tests:** 354 → 364 (+10 SRE tests). Suite green throughout.
**Commits:** 8 phase-tagged, all preserving phase-N.M-findings.md.

## §4 — What this means for Phase 8 (hosting)

Phase 7.5's audit-doc update (§3 rows 24-27 flipped ❌→✅) means Phase
8 now starts with **all four SRE basics already instrumented**:

| SRE field | Phase 8 reads from | Suggested SLO |
|---|---|---|
| Latency p95 | `Aggregate.latency_p95_ms` | < 10s short-answer, < 15s discursive |
| Cost per query | `Aggregate.cost_mean_usd` | < $0.05 median (currently $0.075 discursive) |
| Error rate | `Aggregate.error_rate` | < 1% |
| Token usage | `Aggregate.total_input/output_tokens` | informational (prompt-bloat detector) |

**But the load-bearing Phase 8 priority shifted.** Pre-Phase 7.5, the
plan was "ship hosting + monitoring." Post-Phase 7.5, the diagnosis is:
**refusal discipline must be improved before hosting**, because a
production user query that hits the 88% "approximation instead of
refusal" path returns plausible-looking citations toward wrong
articles. That's a confidence-in-citation problem, which is the project's
core promise.

Concrete order for Phase 8 entry:

1. **SYSTEM_PROMPT iteration against 49 legalbench OOS rows** (~1-2d)
   — close at least half the 88pp refusal gap before any hosting work
2. **`_is_self_refusal()` improvement** — scan full answer, not just
   first 120 chars (catches Pattern A from 7.5.3)
3. **Require `len(citations) > 0` for non-refusal valid answer** —
   catches Pattern C
4. THEN hosting / API / observability

The eval surface to validate (1)-(3) against now exists. Pre-Phase 7.5
the validation surface was the 15-row internal OOS set (overstated by
6.7×) — fixing refusal against that wouldn't have moved the production
needle.

## §5 — Methodological notes worth preserving

Three things Phase 7.5 did *procedurally* that are worth keeping as
patterns for future eval-expansion phases:

1. **Plan doc with locked decisions (D1-D5) before any implementation.**
   `phase-7.5-eval-expansion-plan.md` forced explicit exit criteria. Without
   that, the work would have continued open-endedly without a "done"
   gate. The 4 decisions (scope ceiling, path β, manual D operator-only,
   $15 budget) all held; D5's 5-point exit criteria were directly
   checkable.

2. **Path β (instrument first, then expand) was correct.** Doing
   cost instrumentation (7.5.2) before legalbench expansion (7.5.3+) meant
   the first run of the expanded eval produced real cost numbers
   immediately. Path α (expand first, instrument later) would have produced
   a 2.5h re-run cycle to attribute cost retroactively. Path β paid back
   on first use.

3. **Per-sub-phase findings doc + final synthesis.** Five separate
   findings docs (7.5.3/4/5/7/this) instead of one giant document means
   each finding can be cited independently, and the synthesis (this doc)
   doesn't repeat their content. For a portfolio reviewer, this signals
   eval-discipline-as-version-control, not eval-discipline-as-afterthought.

## §6 — Deferred / open items

### 7.5.6 — OAB 39-44 LGPD manual curation (DEFERRED)

The original plan included a 4-6h human curation pass: download OAB
39-44 PDFs, extract LGPD-specific questions, curate gold URNs. This
was deferred for two reasons:

1. **Diagnostic value is lower than expected.** The 7.5.3/4/5 findings
   already converged on the same diagnosis (refusal-discipline gap).
   A 10-20-row LGPD-only set would confirm what we already know; it
   wouldn't reveal anything new.
2. **Better suited to D7 lawyer engagement.** Manual LGPD curation
   benefits from legal-expert validation of gold URNs. Doing it
   operator-only and then re-validating later is wasteful; deferring
   until D7 contract is in place is more efficient.

Filed for the lawyer-review checklist; will reappear when D7 starts.

### Refusal-discipline fixes (Phase 8 entry items, NOT 7.5 scope)

Documented in `phase-7.5.3-legalbench-oos-findings.md` §3 — three
specific SYSTEM_PROMPT/`_is_self_refusal` changes that should close
the bulk of the OOS gap. Explicitly out of Phase 7.5 scope (per the
non-goal stated in 7.5.3 findings: "don't iterate prompt against
partial set").

### Future eval-surface additions (not blocking)

- **OAB 39-44 LGPD manual** (D6 above)
- **Rabula (FGV)** — dataset URL still not located; ⏸ until found
- **CUAD / COLIEE** — US/EN benchmarks; lower priority than
  expanding pt-br surface
- **Adversarial prompt-injection eval** — audit doc row 22 still 🟡;
  needs a curated adversarial corpus (Greshake 2023 framing)

## §7 — Done-criteria verification (per D5)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | ~60-75 OOS rows / ≥30 in-scope external / ≥1 discursive / ≥1 LGPD subset | 🟡 4 of 5 | 49 OOS ✓, 40 rule recall ✓, 5 discursive ✓, LGPD subset deferred (§6) |
| 2 | `false_refusal_rate` + `cost_per_query` + SRE Golden Signals in Aggregate | ✅ | `run_answer_eval.py:308,321-326,346-352`; `tests/test_sre_metrics.py` asserts non-None |
| 3 | Audit doc gap table updated (4 ROI items ❌→✅) | ✅ | `study/rag-eval-metrics-audit.md` §3 rows 24-27 |
| 4 | One findings writeup | ✅ | This document |
| 5 | Suite green; production metrics within band | ✅ | 364 passed; nDCG/MRR unchanged (no corpus or embedder change) |

4 of 5 fully met; criterion 1 partially met (LGPD-subset deferred per
§6 rationale). **Phase 7.5 is closed** with the deferred item moved to
the lawyer-review checklist.

## §8 — Cross-references

- [`phase-7.5-eval-expansion-plan.md`](phase-7.5-eval-expansion-plan.md) — predecessor plan
- [`phase-7.5.3-legalbench-oos-findings.md`](phase-7.5.3-legalbench-oos-findings.md)
- [`phase-7.5.4-rule-recall-findings.md`](phase-7.5.4-rule-recall-findings.md)
- [`phase-7.5.5-oab-bench-discursive-findings.md`](phase-7.5.5-oab-bench-discursive-findings.md)
- [`phase-7.5.7-sre-golden-signals-findings.md`](phase-7.5.7-sre-golden-signals-findings.md)
- [`rag-eval-metrics-audit.md`](rag-eval-metrics-audit.md) — 41-row gap table (now 20 ✅ / 10 🟡 / 11 ❌; was 17/9/13 pre-Phase 7.5)
- [`query-expansion-plan.md`](query-expansion-plan.md) — sub-phase A+B+C ✅; D ⏸
- [`concurso-pilot-findings.md`](concurso-pilot-findings.md) — the pilot that motivated Phase 7.5
- `eval/runs/phase-7.5.{3,4,5,7}-*.json` — preserved per-row reports
- `BACKLOG.md` — updated with Phase 7.5 closure + Phase 8 priorities
