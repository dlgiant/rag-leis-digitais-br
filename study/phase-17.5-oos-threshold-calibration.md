# Phase 17.5 — `DEFAULT_OOS_THRESHOLD` calibration

**Date:** 2026-05-22
**Embedder:** `voyage-3-large` (production default)
**Text mode:** `title+label+nav+caput+text` (production default)
**Corpus:** 7,201 chunks (post-Phase-16.3, three `PENDENTE_*` stub Temas filtered)
**Cost:** ~$0.0009 (49 + 102 query embeddings; no LLM calls)
**Reproduce:** `uv run python scripts/phase_17_5_oos_threshold_calibration.py`

## Question

What value should `rag_leis.rag.DEFAULT_OOS_THRESHOLD` take, and on what evidence?

The threshold controls a **cosine fast-path refusal**: if top-1 cosine
similarity over the index is below the threshold, the pipeline refuses
without invoking the LLM. Production value is currently `0.40`, set in
Phase 2.7 with the comment "no clean cosine threshold separates [OOS
from in-scope]; cosine gate is a fast-path for very clearly OOS
queries (e.g. someone pasting a paragraph in a different language)".

Phase 17.5's job: convert "no clean threshold" into a measurement
with a citation. Pick the **highest safe** threshold — the cosine gate
is a safety net for structurally-alien inputs, not a primary
classification mechanism (the LLM self-refusal does that).

## Method

Sweep candidate thresholds T ∈ {0.200, 0.225, ..., 0.600} (17 points,
step 0.025) and at each point compute:

- **OOS-refusal recall**: fraction of `eval/legalbench_br_oos.yaml`
  rows (n=49, all genuinely OOS by construction) where top-1 cosine
  drops below T. Higher = more OOS pre-empted by the fast-path.
- **In-scope false-refusal rate**: fraction of `eval/queries.yaml`
  rows (n=102, all in-scope) where top-1 cosine drops below T.
  Higher = more legitimate queries refused for the wrong reason.

Retrieval-only — no LLM. The script embeds 49 + 102 queries via
`voyage-3-large.embed_query` and computes cosine vs the pre-loaded
doc vectors (`title+label+nav+caput+text`). L2-normalized at index
time so dot product = cosine.

## Distributions

**OOS top-1 cosine (n=49, legalbench Tributário/Trabalhista/etc.):**

| stat | min | p10 | p25 | median | mean | p75 | p90 | max |
|---|---|---|---|---|---|---|---|---|
| value | 0.4205 | 0.4687 | 0.5311 | 0.5872 | 0.5904 | 0.6575 | 0.7036 | 0.7779 |

OOS queries land in the same cosine range as in-scope (median 0.587).
This empirically confirms the Phase 2.7 observation — the legalbench
OOS set is **domain-adjacent OOS** (PT-BR legal queries with
overlapping vocabulary), not language-distant OOS. The cosine gate
cannot cleanly separate this kind of OOS; only LLM-self-refusal can.

**In-scope top-1 cosine (n=102, eval/queries.yaml):**

| stat | min | p10 | p25 | median | mean | p75 | p90 | max |
|---|---|---|---|---|---|---|---|---|
| value | 0.4388 | 0.5666 | 0.6147 | 0.6611 | 0.6584 | 0.7145 | 0.7498 | 0.7913 |

The bottom-3 in-scope queries are all about Tier-4 jurisprudência:

1. `0.4388` — "o que diz a Súmula 403 do STJ?"
2. `0.4568` — "qual a tese fixada pelo STF no Tema 786?"
3. `0.4747` — "o que diz a Súmula 227 do STJ?"

These are LEGITIMATE in-scope queries — Súmulas 227/403 + Tema 786
are high-confidence verbatim transcriptions in
`data/chunks/tier-4/jurisprudencia.jsonl`. The low cosine reflects
weak embedding signal on short jurisprudência texts, not OOS-ness.
**Any threshold above 0.4388 false-refuses these.**

## Sweep

| threshold | oos_refusal_recall | false_refusal_rate | oos_caught | false_refusals |
|---|---|---|---|---|
| 0.200 — 0.400 | 0.0000 | 0.0000 | 0 | 0 |
| 0.425 | 0.0204 | 0.0000 | 1 | 0 |
| 0.450 | 0.1020 | 0.0098 | 5 | **1** |
| 0.475 | 0.1224 | 0.0294 | 6 | 3 |
| 0.500 | 0.1429 | 0.0294 | 7 | 3 |
| 0.525 | 0.2245 | 0.0294 | 11 | 3 |
| 0.550 | 0.3469 | 0.0784 | 17 | 8 |
| 0.575 | 0.4694 | 0.1275 | 23 | 13 |
| 0.600 | 0.5714 | 0.1765 | 28 | 18 |

## Decision

**Pin `DEFAULT_OOS_THRESHOLD = 0.425`.**

Reasoning:

- **0.400 (status quo)** is a no-op for the measured set: 0 of 49
  legalbench OOS queries trigger the fast-path. The threshold is set
  below the bottom of the measured OOS distribution (min 0.4205), so
  there's no useful work the gate is doing on this evaluation.
- **0.425** catches exactly one OOS query (2% recall) at **zero**
  false-refusal cost. The bottom of the in-scope distribution is
  0.4388, comfortably above 0.425. Marginal gain, no downside.
- **0.450** is what a naive ROC-style optimization would recommend
  (10% OOS recall, ~1% false-refusal). But the single false-refusal
  is the **Súmula 403** query — a legitimate jurisprudência citação-
  literal that the system SHOULD answer. Sacrificing it for a 10%
  fast-path catch is not the right trade.
- **0.475+** false-refuses Tema 786 + Súmula 227 too. Off the table.

The cosine gate is **not** the place to do work on this OOS set.
The OOS-refusal numbers north of 50% (visible at threshold 0.600)
come paired with a 17% false-refusal rate — well above the operator
sanity threshold. **The LLM self-refusal must remain the load-
bearing OOS classifier.**

## Why not raise the gate higher despite the in-scope risk?

Two alternatives that were considered + rejected:

1. *"Sacrifice Súmula 403 for 10% OOS recall."* Rejected — the
   Súmula 403 query is precisely the query shape lawyers ask for
   when triaging cases. False-refusing it trains the user to mistrust
   the system on its strongest content (verbatim STJ jurisprudência).
   The 10% OOS catch could equivalently come from a sharper LLM
   self-refusal prompt (Phase 17.x area), not from raising the
   cosine floor.
2. *"Add a per-query-type threshold."* Rejected — adds configuration
   surface for a gain of <10% on a set where the LLM is already the
   primary classifier. Defer to Phase 18.x corpus + embedding work
   if the gap between OOS and in-scope cosine ranges proves stable.

## What this calibration does NOT do

- It does NOT measure "structurally alien" OOS (other languages, OCR
  garbage, prompt injection). The 49 legalbench rows are domain-
  adjacent. For those alien cases, the threshold could in principle
  be set even lower without false-refusal cost — but we don't have
  an eval set for them. The current 0.425 still catches the alien
  case in practice; if a future Phase 18.x adds an "alien" OOS
  fixture, the threshold can be re-tuned then.
- It does NOT validate the LLM self-refusal stage. That's a separate
  axis measured by `phase-7.5.3-legalbench-oos.json` + Phase 17.1's
  nightly canary (refusal_recall on a 20-row OOS subset).
- It does NOT change the OOS subtype taxonomy (a/b/c/d). The cosine
  fast-path emits `cosine fast-path` as `refusal_reason`; finer
  subtypes only happen on the LLM-self-refusal path.

## Operator notes

- Re-run cadence: re-calibrate when **either** the corpus changes
  materially (>10% chunk count drift) **or** the embedder changes
  (BGE-M3 → Voyage-3-large or future) **or** the text mode changes
  (Phase 6.6 r4 was the last such change).
- The sweep JSON at `eval/runs/phase-17.5-oos-threshold-sweep.json`
  carries the full per-query top-1 cosines for both sets — useful
  if Phase 18.x wants to inspect the bottom-of-distribution in-scope
  queries to improve embedding signal on Tier-4.
- Phase 17.1 (nightly refusal-discipline canary) gates on
  `oos_refusal_recall ≥ 0.55` + `false_refusal_rate ≤ 0.02`. Those
  gates measure the **end-to-end** pipeline (cosine + LLM), not just
  the cosine gate. With this threshold pin, the cosine gate
  contributes ~2 percentage points to the recall numerator.
