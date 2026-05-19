# Phase 7.6 findings — Graph RAG concepts triage in execution

**Date opened/closed:** 2026-05-19 (single-day execution)
**Predecessor:** Phase 7.5 (eval expansion) — closed 2026-05-17
**Predecessor input:** [`paper-evaluation-graph-rag-2025.md`](paper-evaluation-graph-rag-2025.md) — Springer 2025 Graph-RAG paper triage
**Sub-phase findings:** [7.6.1](phase-7.6.1-explanation-quality-findings.md) · [7.6.2](phase-7.6.2-scope-tags-findings.md)

## TL;DR

Phase 7.6 was a 1-day phase: two parallel paths from the post-Phase-7.5
paper triage, each with an explicit pre-locked decision gate. Both
shipped. One closes a known audit gap cleanly; the other produced a
negative gate result that **kept the bigger version from being built**.

This is the phase's main contribution to the project's discipline:
pre-committed fail-fast gates are how cheap experiments stay cheap.
+0.062pp on a gap-threshold of +0.10pp is the kind of result that
silently turns into 3 weeks of work if you don't decide the threshold
in advance.

## Headline outcomes

| Sub-phase | Path | Result | Status |
|---|---|---|---|
| 7.6.1 | Explanation-quality eval dimension | Coherence=4.93, Quality=5.00, **Compactness=3.57** (new discriminating axis) | ✅ shipped + audit Gap #4 closed |
| 7.6.2 | Scope-tag refusal mechanism | oos_a_refusal_rate 0.122 → 0.184 (+0.062, threshold was +0.10) | ✅ shipped production-default-on; gate did NOT clear; **BACKLOG #1 demoted to EXPERIMENTS.md** |

Both ✅ statuses are honest: 7.6.1 fully delivered on its stated goal,
and 7.6.2 fully executed the fail-fast experiment that the plan locked.
The "negative" result on 7.6.2's gate is **the experiment running
correctly** — not a failure of execution.

## What 7.6 produced for the project

### New diagnostic surface (7.6.1)

The pipeline now scores every in-scope eval row on four orthogonal
LLM-judged dimensions:

- **Faithfulness** (existing) — does the answer match `expected_paragraph`?
- **Coherence** (new) — legal-reasoning fluency
- **General quality** (new) — responsiveness to the question
- **Compactness** (new) — density vs. bloat

On internal eval, coherence + quality are saturated near 5.0
(curated-by-author queries are designed answerable). Compactness shows
real variance — the pipeline produces faithful, coherent, useful, but
**bloated** answers. New signal Phase 7.5 didn't have.

Production utility: regression detector + bloat finder. Phase 8 hosting
can use compactness < 4.0 on a query as an automatic "this answer is
too long, retry with a tighter prompt" signal.

### New refusal mechanism (7.6.2 — production-default-on)

`RAGPipeline.scope_check_enabled=True` adds a pre-LLM gate: query →
LLM extracts concept tags → check whether any retrieved chunk's
document declares any of those concepts → refuse if zero overlap.

Quantitative contribution: +2/49 refusals on legalbench OOS rows.
Modest but real. **false_refusal_rate stayed at 0.000** on internal
eval (verification step 5). Mechanism is conservative + correct.

The gate didn't clear (+0.062 vs +0.10 threshold) because the flat-tag
vocabulary is too coarse to discriminate at the level legalbench OOS
demands. The full concept KG (BACKLOG #1) would face the same root
constraint without lawyer-reviewed (D7) ontology depth. Hence the
demotion to EXPERIMENTS.md until D7 backing exists.

### Decision-doc discipline

The plan locked D3 — the +0.10 fail-fast threshold for path B —
BEFORE running the eval. The +0.062 result is tempting to spin as
"signal worth pursuing." The pre-commit prevented that.

This is the second time decision-doc discipline saved scope in a row:
Phase 7.5 D2 (path β, instrument first) paid back across every
sub-phase; Phase 7.6 D3 (+0.10 gate) prevented a 3-week curation task
that wouldn't have moved production numbers.

## Audit doc updates

- **Gap #4** (RAGAS Answer Relevance) — ❌ → ✅ via 7.6.1
- §3 counts: 22 ✅ / 8 🟡 / 9 ❌ (was 21/8/10 pre-Phase-7.6)
- No new audit row needed for 7.6.2 — the scope-check is a
  refusal-discipline component, not a new metric category

## Tests + budget

- **Tests:** 364 → 386 passing (+22: 4 new for 7.6.1, 18 new for 7.6.2)
- **Engineering:** ~1 day actual (under the 2-day plan estimate)
- **API spend:** $2.41 (7.6.1 eval run) + $0.13 (7.6.2 gate validation)
  + $0.32 (in-scope regression check) = **$2.86 total** (well under
  $15 phase budget)

## Phase 8 entry — unchanged

Phase 7.6 doesn't replace the Phase 8 entry priority. The scope-check
gives +0.04 attributable to the 12.2% refusal gap; the remaining
~0.66 is still the **SYSTEM_PROMPT refusal-discipline iteration**'s
target. Phase 7.6 contributions enter Phase 8 as:

1. New eval surface (compactness) for measuring whether SYSTEM_PROMPT
   changes preserve coherent / non-bloated explanations
2. Production-on scope-check that prompt iteration doesn't need to
   re-prove safe (false_refusal_rate=0 already verified)
3. EXPERIMENTS.md entry for concept-KG as a future angle if
   SYSTEM_PROMPT iteration also under-performs

## Cross-references

- [`phase-7.5-findings.md`](phase-7.5-findings.md) — parent narrative,
  12.2% gap, refusal-discipline as Phase 8 entry priority
- [`phase-7.6.1-explanation-quality-findings.md`](phase-7.6.1-explanation-quality-findings.md)
- [`phase-7.6.2-scope-tags-findings.md`](phase-7.6.2-scope-tags-findings.md)
- [`paper-evaluation-graph-rag-2025.md`](paper-evaluation-graph-rag-2025.md) — source paper triage
- [`rag-eval-metrics-audit.md`](rag-eval-metrics-audit.md) — Gap #4 ✅ flip
- [`BACKLOG.md`](../BACKLOG.md) §🧪 Graph RAG concepts — updated
- [`EXPERIMENTS.md`](../EXPERIMENTS.md) §1 — KG demoted here
- `eval/runs/phase-7.6.1-explanation-baseline.json` — explanation-quality scores
- `eval/runs/phase-7.6.2-scope-gate.json` — gate validation
- `eval/runs/phase-7.6.2-internal-regression-check.json` — false_refusal=0
