# Phase 7.6.2 findings — scope-tag gate (negative gate result)

**Date:** 2026-05-19
**Sub-phase:** 7.6.2 (path B of Phase 7.6)
**Plan:** `~/.claude/plans/lucky-questing-nova.md` D3
**Eval set:** `eval/legalbench_br_oos.yaml` (49 rows, baseline 0.122)
**Run log:** `eval/runs/phase-7.6.2-scope-gate.json`
**Cost:** $0.13 (105 LLM calls, 179k input + 22k output tokens)
**Latency:** p50=3.5s, p95=8.2s (added ~1-2s vs baseline from extractor call)

## Headline result — gate did not clear

**oos_a_refusal_rate: 0.122 → 0.184** (+0.062pp).

Gate threshold (per D3 decision): **≥+0.10pp**.

The mechanism produced a real but underpowered signal. The bigger
BACKLOG #1 idea (full static concept KG with hierarchical relationships)
**stays parked in EXPERIMENTS.md** per the pre-committed fail-fast rule.

## Why the rule mattered

The plan locked the +0.10 threshold BEFORE running the eval (D3 in
`phase-7.5-eval-expansion-plan.md`-style decision discipline). Without
the pre-commit, the +0.062 result would be tempting to spin as "small
signal, worth pursuing" — and that's how 3-day curation tasks turn
into 3-week curation tasks that don't move the production metric.

The bigger concept-KG version needs lawyer review (D7) to be
trustworthy. If the cheap version doesn't show the mechanism has
fundamental signal, the expensive version inherits the same
underpoweredness *plus* the D7 dependency. Net: not worth it.

## What the mechanism DID catch (the +2 real signal)

Of the 9 refused rows (vs 6 baseline), **2 were from the new
scope-check**, 7 were existing llm-self-refusal. The +3 net delta is
+2 from the mechanism + ~1 from LLM-stochasticity noise between runs.

Sample concept-scope-mismatch refusal:

> **Q:** "João, vítima de crime, deseja atuar diretamente como
> assistente da acusação. Em que momento processual..."
>
> Refusal: `concept-scope-mismatch: query=[devido-processo,
> processo-eletronico, ordem-judicial] vs retrieval=[consumidor,
> crimes, defesa-consumidor, dolo-culpa, estelionato-digital]`

The extractor correctly identified the query's concepts (procedural
penal — devido-processo + processo-eletronico); retrieval landed on
CDC/CP material (no procedural-penal coverage); gate fired with an
audit-friendly refusal reason.

This is **exactly the mechanism the paper described**, working as
designed. It's just not enough cases.

## Why it didn't catch more

Two failure modes in the 40 remaining missed rows:

### Failure mode 1 — extractor returns empty concepts (defensive default = don't refuse)

Many legalbench OOS queries touch concepts our vocabulary doesn't
cover (`incompetencia-territorial`, `defesa-previa`, `usucapiao`,
etc.). The extractor returns `concepts=[]` → per the defensive
default, we DON'T refuse on empty extraction. The downstream LLM then
gets the query + (irrelevant) retrieval + 88% of the time produces an
approximation answer.

**Why not refuse on empty extraction?** Because that would create
false-refusals on legitimate in-scope queries the extractor
under-tags. Verification step 5 confirmed `false_refusal_rate=0.000`
on internal eval — the conservative default is correct, just
underpowered.

### Failure mode 2 — extractor over-tags with generic concepts

A few queries match generic vocabulary tags (`crimes`, `tipicidade`)
which our CP doc carries. So query=[crimes] + retrieval=[crimes, ...]
= overlap = don't refuse. But the specific crime in the query is one
the CP doesn't cover (eleitoral, militar). Generic tag matching is
not specific enough.

The fix for both failure modes is the SAME thing — **richer
vocabulary with finer concept distinctions**. That's exactly what
BACKLOG #1 (full concept KG with broader-than / related-to /
contradicted-by relationships) was supposed to deliver. So the
mechanism's verdict isn't "approach is wrong" — it's "needs lawyer-
reviewed full ontology to work." Which means it's a D7-dependent
project, which isn't Phase 7.6 territory.

## What this DOES validate

- The pre-LLM concept-extraction step works: 49 queries got concept
  tags in under 2 minutes total, ~$0.06 across the run, ~1-2s p50
  latency added per query
- The defensive default (empty query-concepts → don't refuse) holds
  in practice: false_refusal_rate stayed at 0.000 on internal eval
- The audit-readable refusal reason (`concept-scope-mismatch:
  query=[...] vs retrieval=[...]`) is useful for the 2 cases where
  it fired — operator can immediately see *why* the gate refused

## Phase 7.6 close decision

Per D3: gate did not clear → **BACKLOG #1 (full concept KG) moves
from BACKLOG.md to EXPERIMENTS.md** with the documented evidence
that the cheap version produces +0.06 lift, not the +0.10 needed to
justify investment.

The shipped code stays — the scope-check mechanism remains
production-default-on (`RAGPipeline.scope_check_enabled=True`)
because it produces NO regression (false_refusal_rate=0) and DOES
produce a small real signal (+0.04 attributable). Removing the
mechanism would lose that gain.

Future: revisit IF a richer vocabulary becomes available via D7
lawyer engagement, OR if the SYSTEM_PROMPT iteration (Phase 8 entry
item — alternative angle to this approach) doesn't move the
refusal-discipline needle either.

## Implementation summary

### What shipped (production-default-on)

- `rag_leis/corpus.py`:
  - `Document.document_scope: tuple[str, ...]` field added
  - All 26 docs tagged with 3-9 concepts each
  - `CORPUS_BY_URN` registry lookup (one-line dict comprehension)
- `rag_leis/concept_scope.py` (new, ~170 lines):
  - `CONCEPT_VOCABULARY: frozenset[str]` (60 concepts auto-built from
    union of all `document_scope`)
  - `CONCEPT_EXTRACTION_TOOL` structured-output schema
  - `EXTRACTION_SYSTEM_PROMPT` with vocabulary inlined
  - `extract_concept_tags(query, llm)` with defensive vocabulary
    filter (drops hallucinated concepts client-side)
  - `check_scope_overlap(query_concepts, retrieved_doc_urns)` —
    pure-logic gate predicate with defensive defaults
- `rag_leis/rag.py`:
  - `RAGPipeline.scope_check_enabled: bool = True` field
  - New gate block after cosine fast-path; folds extractor cost into
    `RAGAnswer.cost_estimate_usd/tokens_used/llm_calls` immediately
  - Returns `RAGAnswer(refused=True, refusal_reason="concept-scope-
    mismatch: ...")` when gate fires
- `tests/test_concept_scope.py` (new, 18 tests):
  - Vocabulary integrity (non-empty, frozenset, core concepts present)
  - Extractor filter (hallucinations dropped, non-strings dropped,
    empty query → no LLM call)
  - Gate decision (overlap → don't refuse; no overlap → refuse;
    partial overlap → don't refuse; defensive empty cases)
  - Corpus invariant: every Document has ≥1 tag

### Tests: 368 → 386 passing (+18)

## Phase 7.6 progress

- ✅ **7.6.1** — explanation-quality eval shipped; closed audit Gap #4
- ✅ **7.6.2** — scope-tag mechanism shipped + negatively-gated;
  BACKLOG #1 → EXPERIMENTS.md
- Phase 7.6 closes with this findings doc + a brief synthesis update
  to BACKLOG.md

## Cross-references

- [`phase-7.5-findings.md`](phase-7.5-findings.md) — parent narrative
- [`phase-7.6.1-explanation-quality-findings.md`](phase-7.6.1-explanation-quality-findings.md) — path A findings
- [`paper-evaluation-graph-rag-2025.md`](paper-evaluation-graph-rag-2025.md) — source paper's concepts that 7.6.2 implemented
- [`BACKLOG.md`](../BACKLOG.md) — Graph RAG section gets updated post-Phase 7.6
- [`EXPERIMENTS.md`](../EXPERIMENTS.md) — destination for BACKLOG #1 (full KG) post-negative-gate
- `eval/runs/phase-7.6.2-scope-gate.json` — gate validation per-row data
- `eval/runs/phase-7.6.2-internal-regression-check.json` — false_refusal_rate=0 confirmation
- `rag_leis/concept_scope.py` — production mechanism (stays on)
