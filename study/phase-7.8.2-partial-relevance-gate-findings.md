# Phase 7.8.2 — Partial-relevance gate: three options compared

**Date:** 2026-05-19
**Eval:** `eval/answer_queries.yaml` (29 rows: 14 in-scope, 15 OOS) via the cached
results in `eval/runs/phase-7.8.1-inscope-opus-relevance.json`.
**Cost:** $0 — predicate sweep against cached per-row `rejected_irrelevant_citations`.
**Verdict:** **Option C (adaptive-by-classified_type) Pareto-dominates Options A
and B on internal eval. Legalbench validation is incomplete** — the existing
legalbench JSON doesn't capture `classified_type`, so Option C cannot be
projected on the harder surface from cache. Recommended variant: `C1` —
strict ≥1.00 for `definicao`, `citacao-literal`, `enumeracao`; relaxed ≥0.80
for `parafrase` and unclassified.
**Status:** **Do NOT ship yet.** Internal Pareto-win is suggestive but
legalbench projection (Option A as upper bound) shows ≥0.80 catches only 1
of 16 leakers there (+0.021pp), below the ≥0.05pp pre-locked criterion.
Recommend: re-run legalbench OOS once with `classified_type` captured,
then re-validate Option C. Cost ~$2.16. See "Legalbench projection" below.

## Headline result

| Variant | in-scope `false_refusal_rate` | OOS `refusal_recall` | Δ FR | Δ catches |
|---|---:|---:|---:|---:|
| **Baseline** (current Phase 7.8 ≥1.00) | **0.000** | **0.667** | — | — |
| A: pure ≥0.80 | 0.071 (+1 row) | 0.867 (+3) | +0.071 | +0.200 |
| B: ≥0.80 AND `n_cits ≥ 4` | 0.071 (+1 row) | 0.867 (+3) | +0.071 | +0.200 |
| **C1: 1.00 / 1.00 / 1.00 / 0.80** (def/lit/enum/paraf) | **0.000** | **0.867** | **+0.000** | **+0.200** |
| C2: 1.00 / 1.00 / 1.00 / 0.75 | 0.000 | 0.867 | +0.000 | +0.200 |
| C3: 1.00 / 1.00 / 0.80 / 0.80 | 0.000 | 0.867 | +0.000 | +0.200 |

The four Option C variants tie on this eval. C1 is the most conservative
(strictest on the highest-confidence types) and is the recommendation.

## Why A and B both pay one in-scope false-refusal

The single in-scope row that flips to refused under A and B is:

> **Row 3**: "qual a definição legal de programa de computador no Brasil?"
> `n_cits=7`, `n_irrel=6` (85.7%), `classified_type="definicao"`,
> `cit_precision_strict=0.14`, `faithfulness=5/5` (in original 7.8.1 run)

Opus marked 6 of 7 citations as off-topic; the answer was rated 5/5 by the
faithfulness judge. Two readings:

- **Strict reading:** retrieval was bad (1-of-7 hit rate); the model
  lucked into the right citation among 6 wrong ones; refusing is honest
  about the weak retrieval foundation.
- **Lenient reading:** the answer is right because one citation is right;
  partial-relevance is exactly the failure mode the model navigated
  correctly; refusing is over-strict.

The lenient reading wins iff the model's "lucked into the right citation"
behavior is reliable across queries — i.e., across many definicao queries
where retrieval surfaces 7 chunks and 1 is on-topic, the model
consistently picks the right one. We don't have evidence either way at
n=4 definicao rows. **Option B's `n_cits ≥ K` guard doesn't help** —
row 3 has `n_cits=7`, well above any plausible K. The guard is dead code
on this data.

Option C resolves the dilemma by **not making the choice generically**:
for `definicao`, where the right-citation pattern is the structural
expectation, keep the strict ≥1.00 (lenient reading wins by construction);
for `parafrase`, where retrieval can blur across many adjacent topics,
relax to ≥0.80 (strict reading wins by construction).

## What the 3 newly-caught OOS rows are

All three rows are classified by the router as `parafrase`:

| Row | Query (truncated) | Subtype | n_cits | n_irrel | %irrel |
|---|---|---|---:|---:|---:|
| 16 | "como funciona o divórcio judicial no Brasil?" | (a) other domain | 5 | 4 | 80.0% |
| 21 | "Como funciona a interceptação telefônica…?" | (a) other domain | 5 | 4 | 80.0% |
| 29 | "direito ao esquecimento na internet brasileira como princípio autônomo" | (e) doutrina sem positivação | 6 | 5 | 83.3% |

Row 29 is particularly load-bearing: it's the doutrina-sem-positivação
subtype that scored 0.000 refusal in Phase 7.8.1 — a known weak spot.
Catching even one row in that subtype lifts (e) from 0/2 to 1/2.

The two OOS leakers that **stay** uncaught under C:

| Row | Query | %irrel | Why stays uncaught |
|---|---|---:|---|
| 19 | "Posso processar a Meta no Brasil…?" | 0.0% | Opus considers all 5 citations relevant — LGPD framework is genuinely topically applicable. Not a gate problem; arguably a hard-OOS-classification problem. |
| 28 | "Princípio da minimização excessiva como fundamento autônomo…" | 25.0% | Only 1 of 4 citations marked irrelevant. Below any plausible threshold. |

## Why Option C is principled, not just empirically lucky

The `classified_type` signal correlates with how much trust to place in
partial-relevance. Two query types with structural reasons to behave
differently under the gate:

- **`definicao` / `citacao-literal` / `enumeracao`** are high-structure
  query types. The expected answer is anchored in a specific
  dispositivo (a definition article, a numbered article, an enumerated
  list). If retrieval surfaces 7 chunks and Opus says 6 are off-topic
  but 1 is on-topic, the on-topic one is probably the right answer.
  Partial irrelevance here is "retrieval was loose but the model found
  the right anchor."

- **`parafrase`** is a low-structure query type. The expected answer
  spans across multiple chunks or relates indirectly to the question.
  Partial irrelevance here is "the question was vague enough that
  retrieval drifted across adjacent topics" — exactly the failure mode
  Phase 7.8's gate was designed to catch.

This re-uses the same query-router classification that already informs
adaptive `top_k` (Phase 4.1). One classifier, two related uses — not
two independent calibration surfaces.

## What this analysis CAN tell us

- All predicate variants are evaluated against the **same** cached LLM
  responses. The choice between A, B, C is purely about the predicate
  shape; no LLM variance enters the comparison.
- Option C is a **strict Pareto improvement** over baseline on this
  eval: same in-scope FR (0.000), strictly better OOS recall (0.667 →
  0.867). No baseline criterion is violated.
- The improvement concentrates on the structural weak spot (`parafrase`
  classifications including the `(e)` doutrina subtype).

## What this analysis CAN'T tell us

1. **n=14 in-scope, n=15 OOS.** Confidence intervals on a +0 / +3 split
   at this sample size are wide. The result is reliable as a description
   of THIS eval, suggestive as a population estimate.

2. **All 3 OOS catches happen because the router classifies the 5 OOS
   leakers as `parafrase`.** If the router's class boundaries shift —
   either through prompt edits or future model upgrades — the
   correlation between `classified_type="parafrase"` and "this is the
   query type where partial-relevance is meaningful" might weaken.
   Option C's threshold table is calibrated to the current router's
   behavior, not to query semantics directly.

3. **Cross-doc queries classify as `parafrase` on this eval (rows 12, 13).**
   That means under C, cross-doc rows get the relaxed threshold. Whether
   that's right is unclear — cross-doc is *defined* as gold spanning
   multiple laws, so multi-relevant citations are expected and
   partial-irrelevance is plausible as a "found one law but missed the
   other" signal. Worth a deliberate decision before shipping.

4. **legalbench OOS not measured under C.** Phase 7.8.1 OOS A/B was on
   legalbench (49 rows). Option C's projection on internal OOS is +3;
   the legalbench impact is unknown. Before promoting C to the eval
   default, the legalbench projection should be computed against its
   cached responses (also $0 cost, same predicate-sweep pattern).

## Pre-locked criterion (revised vs the plan doc)

The plan doc proposed criteria assuming the +1 in-scope FR trade-off of
Options A/B. Option C eliminates that trade-off entirely, so the criteria
collapse to:

> Phase 7.8.2 ships variant C1 iff:
> 1. ✅ Internal in-scope `false_refusal_rate` stays at **0.000**.
>    *(Confirmed on this eval. Phase 7.8's pre-locked criterion preserved.)*
> 2. ✅ Internal OOS refusal recall increases by ≥0.10pp.
>    *(Measured +0.20pp; 0.667 → 0.867.)*
> 3. ⚠️ legalbench OOS refusal rate increases by ≥0.05pp.
>    *(Partial result — see "Legalbench projection" below. Option A at
>    T=0.80 gives only +0.021pp on legalbench, BELOW criterion. Option C
>    cannot be projected on legalbench because the existing legalbench
>    JSON doesn't capture `classified_type` — a fresh run would be
>    required. Cached-data analysis insufficient to bless C on
>    legalbench surface.)*
> 4. ✅ Cost neutral.
>    *(Predicate change only; no new LLM calls.)*

Criteria 1, 2, 4 met. Criterion 3 pending.

## What changed in the codebase (this analysis)

Nothing yet — the analysis is offline against cached eval data. The
codebase change required to ship Phase 7.8.2 is small:

- `rag_leis/rag.py` ~line 688: replace the `len(rejected_irrelevant) ==
  len(verified)` predicate with a per-type threshold lookup keyed off
  `classified` (already available in the gate's scope).
- `rag_leis/citation_relevance.py`: optional `THRESHOLDS_BY_TYPE` dict
  constant for clarity.
- Tests: add 1-2 cases per `classified_type` validating the threshold
  lookup. Existing 14-test suite already covers the strict-all gate
  semantics; new tests would cover partial-fire behavior.
- `serialize_row` already emits the necessary diagnostic fields
  (Phase 7.8.1 fix).

Estimated ~40 min implementation including tests + documentation
updates. Cost to validate: $0 (re-run cached eval).

## Legalbench projection (Option A only; C not computable from cache)

Same predicate sweep against `eval/runs/phase-7.8.1-sabia-vs-opus.json`,
the Opus-judge variant of the Phase 7.8.1 OOS A/B (49 rows). The legalbench
JSON has `rejected_irrelevant` (the URN list) but **does not capture
`classified_type`** — so Option C cannot be projected. Option A is a
useful upper bound on Option C's potential improvement (Option C will
catch fewer or equal rows since it restricts the relaxed threshold to
specific types).

| Threshold T (Option A) | Newly caught | Projected refusal rate |
|---:|---:|---:|
| Baseline (≥1.00) | 0 | 0.673 (33/49) |
| ≥0.50 | 8 | 0.837 (+0.164pp) |
| ≥0.60 | 7 | 0.816 (+0.143pp) |
| ≥0.67 | 6 | 0.796 (+0.123pp) |
| ≥0.75 | 6 | 0.796 (+0.123pp) |
| **≥0.80** | **1** | **0.694 (+0.021pp)** |
| ≥0.90 | 0 | 0.673 (+0.000pp) |

Two observations:

1. **The cliff is in a different place on legalbench.** Internal eval
   had a clean shoulder at ≥0.80; legalbench's same threshold gains
   only 1 catch. The big jump on legalbench is at ≥0.67 (+6 catches,
   +0.123pp). The two eval surfaces produce different irrelevant-
   fraction distributions among leakers.

2. **The 80% bar misses criterion 3 by 0.029pp.** Option A at the
   internally-Pareto threshold (≥0.80) doesn't meet the legalbench
   bar. To meet criterion 3 with a pure threshold change, we'd need
   ≥0.67 — but that comes with +1 in-scope FR risk on the internal
   eval (row 3, the definicao case).

This is exactly where Option C should shine — relax ≥0.80 ONLY where
it doesn't hit the high-confidence types. But we **can't validate that
on legalbench** without re-running to capture `classified_type`. The
$0 sweep can't bless Option C on the harder surface.

## Distributions side by side

| Eval | Total OOS | OOS already refused | Leakers w/ citations | %irrel ≥ 80% among leakers |
|---|---:|---:|---:|---:|
| Internal (15 rows) | 15 | 10 (66.7%) | 5 | **3 / 5** (60%) |
| Legalbench (49 rows) | 49 | 33 (67.3%) | 16 | **1 / 16** (6%) |

The 10× gap in "≥80% irrelevant among leakers" is the real story. Internal
OOS leakers tend to retrieve highly-off-topic chunks (where Opus marks
most as irrelevant); legalbench leakers tend to retrieve genuinely-
adjacent-but-wrong chunks (where Opus grants relevance to more). The
gate's effectiveness scales with how "off" the leaker's retrieved chunks
are. **Internal eval may be over-representing the easy-leaker pattern.**

## Sequencing recommendation

1. ✅ **Done:** Internal eval projection. Option C is a strict Pareto
   win on this surface.
2. ⚠️ **Partial:** Legalbench Option A projection. ≥0.80 misses criterion 3
   by 0.029pp; ≥0.67 meets it but introduces in-scope risk.
3. ⏸ **Required before shipping:** re-run legalbench OOS once with the
   Phase 7.8.1 + 7.9 stack (Sabiá+Opus, cache active, `classified_type`
   captured in serialized rows). Cost: same as the original Phase 7.8.1
   A/B Opus variant (~$2.16). Then project C on legalbench from the
   fresh cache; if C meets ≥0.05pp on legalbench too, ship.
4. **Alternative if cost-sensitive:** ship the small infra change first
   — pipeline change to write `classified_type` into the legalbench
   eval JSON — then wait for the next legalbench run to populate it.
   No new spend now; defer Phase 7.8.2 ship until that data exists.

## Diagnostic / repro

- `scripts/phase_7_8_2_threshold_sweep.py` — the sweep harness. Reads
  the cached eval JSON, projects metrics under each predicate variant,
  prints the recommendation table. Re-runnable against any eval run
  that serializes `rejected_irrelevant_citations` (Phase 7.8.1 fix).

## Cross-references

- [`phase-7.8.2-partial-relevance-gate-plan.md`](phase-7.8.2-partial-relevance-gate-plan.md) — predecessor planning doc
- [`phase-7.8.1-inscope-opus-regression.md`](phase-7.8.1-inscope-opus-regression.md) — the in-scope run whose cached data made this analysis possible
- [`phase-7.8-citation-relevance-findings.md`](phase-7.8-citation-relevance-findings.md) — original strict gate design
- `eval/runs/phase-7.8.1-inscope-opus-relevance.json` — per-row data
- `scripts/phase_7_8_2_threshold_sweep.py` — sweep harness
