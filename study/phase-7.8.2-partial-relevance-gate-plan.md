# Phase 7.8.2 — Partial-relevance gate threshold (planning, NOT YET RUN)

**Date:** 2026-05-19
**Status:** Planning. No experiment run; criterion not yet pre-locked.
**Predecessor:** [`phase-7.8.1-inscope-opus-regression.md`](phase-7.8.1-inscope-opus-regression.md) — closed Limitation #1 and surfaced this candidate.

## The problem this would solve

The Phase 7.8 per-citation relevance gate fires only when **all**
verified citations are judged irrelevant. The Phase 7.8.1 in-scope
regression run produced this distribution on the 5 OOS rows that leaked
through (Sabiá generator + Opus relevance judge):

| OOS query | n_citations | n_irrelevant | % irrelevant | Current gate? |
|---|---:|---:|---:|---|
| "Como funciona o divórcio judicial no Brasil?" | 5 | 4 | 80.0% | doesn't fire (need 100%) |
| "Posso processar a Meta no Brasil…?" | 5 | 0 | 0.0% | doesn't fire |
| "Como funciona a interceptação telefônica…?" | 5 | 4 | 80.0% | doesn't fire |
| "Princípio da minimização excessiva como fundamento autônomo…" | 4 | 1 | 25.0% | doesn't fire |
| "direito ao esquecimento na internet brasileira…" | 6 | 5 | 83.3% | doesn't fire |

Three of the five leakers had Opus mark **the majority** of their
citations as irrelevant. The gate's binary-strict rule — fire only on
all-irrelevant — discards that majority signal. One stretchy citation
defeats the gate.

## The signal the pipeline already produces

The relevance gate calls Opus once per row with citations and receives
a per-URN `{relevant: bool, reason: str}` evaluation. The `bool` array
is consumed; the *fraction* irrelevant is computed but only thresholded
at 1.0 (all-irrelevant). The same call gives us a `0.0 → 1.0` score
for free; the only change is the gate-firing predicate.

This makes Phase 7.8.2 a **threshold experiment, not a model change**.
No additional LLM calls. Reuses the Phase 7.8.1 cached eval data.

## The threshold sweep (using 7.8.1 cached data)

Re-evaluated the gate predicate against the 14 in-scope and 15 OOS
rows in `eval/answer_queries.yaml`, varying the irrelevant-fraction
threshold:

| Threshold (≥% irrelevant fires) | New in-scope false-refusals | Newly-caught OOS leakers | Net OOS catches |
|---:|---:|---:|---:|
| ≥50% | +3 | +3 | 0 (break-even) |
| ≥60% | +2 | +3 | +1 |
| **≥67%** | **+1** | **+3** | **+2** |
| **≥75%** | **+1** | **+3** | **+2** |
| **≥80%** | **+1** | **+3** | **+2** |
| ≥90% | 0 | 0 | 0 (no change) |
| ≥100% (current) | 0 | 0 | baseline |

The cliff sits between 80% and 90%: any threshold in `[67%, 80%]`
gains 3 OOS catches at the cost of 1 in-scope false refusal. Below 67%
the false-refusal cost climbs; above 80% there's no behavioral change.

## The in-scope row at risk

At threshold `[67%, 80%]`, the single in-scope row that flips to
refused is:

> Row 3: "qual a definição legal de programa de computador no Brasil?"
> n_cits=7, n_irrel=6, %irrel=85.7%

That row's `cit_precision_strict = 0.14` in the eval (1 of 7 citations
matched gold). Opus identified the other 6 as off-topic. So the
question is whether a row where the model produced an answer grounded
in 1 of 7 citations is "correctly answered" or "answered for the wrong
reasons." Two readings:

- **Lenient:** the answer was right; the 1 correct citation grounds
  it; the 6 unrelated citations are noise that should be downranked
  but not block the answer. The current gate behavior is correct.
- **Strict:** an answer that retrieves 7 chunks and only 1 is actually
  on-topic is a fragile foundation. The model lucked into the right
  citation among 6 wrong ones. Refusing here is honest about the
  retrieval miss.

Both readings have merit. Which one is right depends on what the
pipeline is **for**. A practitioner-facing tool that wants
high-confidence citations should refuse; a research/draft-assist tool
should let the answer through with the high citation-precision-lenient
already in place as a soft signal.

This codebase is positioned as practitioner-utility (per project
memory: production-level, reproducibility/compliance load-bearing).
That biases toward strict.

## The risk distribution in the in-scope set

Looking at the full in-scope distribution to understand whether row 3
is an outlier or representative:

| %irrel range | In-scope row count |
|---|---:|
| 0% (no citations rejected) | 10 of 14 |
| 1-39% | 0 |
| 40-66% | 2 (rows 4, 8) |
| 67-89% | 2 (rows 1, 3) |
| 90-100% | 0 (row 12 was the false-refusal in the broken Sonnet run, but Opus marks it 0%) |

The risk surface is small: only 4 of 14 in-scope rows have any
citation rejection at all, and only 2 cross the 67% threshold. At a
threshold ≥80%, only row 3 fires. At ≥67%, row 1 also fires
("qual a definição de dado pessoal na LGPD?", 4 of 6 irrelevant —
`cit_precision_strict = 0.17`, similar pattern of low-precision
retrieval).

## Pre-locked design options

Three candidates, in order of conservatism:

### Option A — Pure threshold change (≥80%)
- Predicate: `n_irrelevant / n_citations >= 0.80` fires.
- Best ratio in the sweep: +3 OOS catches : +1 in-scope FR.
- Internal eval projection: `false_refusal_rate = 0.071`,
  `oos_refusal_recall = 0.867`.
- Risk: in-scope FR violates Phase 7.8's pre-locked criterion
  ("stays at 0.000"). Needs a renegotiated criterion.

### Option B — Threshold + citation-count guard (≥80% AND n_cits ≥ 4)
- Predicate: `n_citations >= 4 AND n_irrelevant / n_citations >= 0.80`.
- Avoids firing on rows with very few citations where a single
  judge mis-call has disproportionate weight (1-of-1 = 100%
  irrelevant, but the sample size is too small).
- All 5 OOS leakers in 7.8.1 have n_cits ∈ {4,5,5,5,6} — all
  satisfy the guard. Net OOS catches identical to Option A: +3.
- In-scope row 3 has n_cits=7 — still fires. Same in-scope cost
  as Option A.
- Adds defense against future low-citation rows; cheap insurance.

### Option C — Adaptive threshold by classified_type
- Predicate: per-query-type threshold table.
  - `definicao`, `citacao-literal`: ≥100% (current strict — high-
    confidence retrieval expected, false refusal more costly)
  - `enumeracao`, `cross-doc`, `oos`: ≥80% (relaxed — multiple
    citations make partial-irrelevance more reliable as signal)
- More complex; more parameters to calibrate; needs n>14 per type
  to validate. **Not recommended without expanded eval set.**

## Recommended next step (NOT a commitment)

**Option B at threshold 0.80.** Pre-locked criterion candidate:

> Gate should be relaxed (`>= 0.80` AND `n_cits >= 4`) iff:
> 1. Internal in-scope `false_refusal_rate ≤ 0.071` (i.e., row 3
>    is the only candidate; no surprises)
> 2. Internal OOS refusal recall increases by `≥ 0.10pp`
> 3. legalbench OOS refusal rate increases by `≥ 0.05pp` (cross-
>    validation on the harder OOS surface)
> 4. Cost neutral (no new LLM calls — threshold is a predicate
>    change)

If conditions met → ship as Phase 7.8.2.
If conditions partially met → escalate to Phase 7.8.3 calibration
with adaptive thresholds.

## What this is NOT solving

- **Row 12 (cross-doc Decreto 8.771)** isn't a threshold problem —
  Opus correctly judged its citations relevant in the 7.8.1 in-scope
  run (the prior Sonnet judgment was the bug). Phase 7.8.2 wouldn't
  touch it.
- **Sabiá-generator OOS leakage on doutrina-sem-positivação** —
  the `(e)` subtype refusal rate is 0.000 because Sabiá-generator
  commits to citations. Opus catching 5 of 6 citations as
  irrelevant on row 29 is exactly the signal a relaxed gate would
  catch. So Phase 7.8.2 *would* improve this subtype, but the
  fundamental fix is generator-side (or scope-tag pre-classifier).

## Cost to run

- LLM API: **$0**. Predicate change reuses cached responses.
- Wall time: ~30 min for the predicate refactor + targeted unit tests
  + cached-data sweep validation.
- Risk: low. The gate is a refusal-side mechanism; relaxing it can
  only refuse more, never produce a wrong answer.

## Open questions to resolve BEFORE running

1. **Pre-locked criterion: does in-scope `false_refusal_rate ≤ 0.07`
   count as "stays at 0.000"?** Strict reading no. Pragmatic reading:
   the 0.000 bar was set against the existing strict-all gate; a
   different gate is a different bar. Needs explicit re-baseline.
2. **Should row 3's case be treated as a true refusal (the model
   answered for the wrong reasons) or a false refusal (the answer
   was right despite weak retrieval)?** Determines whether Option A/B
   is a regression or a feature.
3. **legalbench OOS impact.** Need to compute the threshold sweep on
   that surface before committing. May reveal a different cliff.

## Cross-references

- [`phase-7.8.1-inscope-opus-regression.md`](phase-7.8.1-inscope-opus-regression.md) — surfaced this candidate
- [`phase-7.8-citation-relevance-findings.md`](phase-7.8-citation-relevance-findings.md) — original gate design
- `eval/runs/phase-7.8.1-inscope-opus-relevance.json` — the per-row
  `rejected_irrelevant_citations` field that makes this analysis
  possible (without it, threshold sweeps would require re-running)
