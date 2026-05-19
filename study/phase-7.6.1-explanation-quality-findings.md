# Phase 7.6.1 findings — explanation-quality LLM-judge eval

**Date:** 2026-05-19
**Sub-phase:** 7.6.1 (path A of Phase 7.6 — see [`phase-7.5-findings.md`](phase-7.5-findings.md) for the parent narrative)
**Plan:** `~/.claude/plans/lucky-questing-nova.md`
**Eval set:** `eval/answer_queries.yaml` (29 rows: 14 in-scope + 15 OOS) — internal, no external benchmark used at this step
**Run log:** `eval/runs/phase-7.6.1-explanation-baseline.json`
**Cost:** $2.41 (62 LLM calls, 209k input + 33k output tokens)
**Latency:** p50=10.9s, p95=39.3s (up from p50=6.8s pre-7.6.1 because of the second judge call per row)

## Headline result

**Coherence 4.93 / Quality 5.00 / Compactness 3.57** out of 5.

Faithfulness (4.57/5) and the three new explanation-quality dimensions
were scored by Opus-4-7 on the 14 in-scope rows. Three observations:

- **Coherence and quality are essentially saturated** on the internal
  eval (13/14 rows scored 5/5 on coherence; 14/14 on quality). On a
  curated-by-author eval surface this is expected — the queries were
  designed to be answerable.
- **Compactness shows real variance** (distribution: 1×2 + 5×3 + 7×4 +
  1×5). It's the only axis that discriminates between rows in this
  measurement.
- The pipeline produces **faithful, coherent, useful — but bloated**
  answers. New diagnostic signal Phase 7.5 didn't surface.

## Score distribution (14 in-scope rows)

| Axis | 0 | 1 | 2 | 3 | 4 | 5 | Mean |
|---|---|---|---|---|---|---|---|
| Faithfulness | 0 | 0 | 0 | 1 | 1 | 12 | 4.57 |
| **Coherence** | 0 | 0 | 0 | 0 | 1 | 13 | **4.93** |
| **Quality** | 0 | 0 | 0 | 0 | 0 | 14 | **5.00** |
| **Compactness** | 0 | 0 | 1 | 5 | 7 | 1 | **3.57** |

## What "compactness 3.57" means concretely

Sample judge reasoning on three in-scope rows:

> **Q:** "qual a definição legal de programa de computador no Brasil?"
> coh=5/5 qual=5/5 **comp=2/5**
> *"A resposta entrega a definição legal pedida logo no primeiro
> parágrafo com citação do dispositivo, e encadeia coerentemente o
> regime de proteção. Porém, a pergunta é estrita ('definição
> legal'), e a resposta agrega muito contexto regulamentar não
> solicitado..."*

> **Q:** "qual a definição de dado pessoal na LGPD?"
> coh=5/5 qual=5/5 **comp=3/5**
> *"Resposta começa com a definição exata pedida (Art. 5º, I) e
> encadeia logicamente para conceitos correlatos (titular, sensível,
> anonimizado, perfil comportamental)..."*

> **Q:** "o que é neutralidade de rede no Marco Civil da Internet?"
> coh=5/5 qual=5/5 **comp=4/5**
> *"A resposta define o conceito, cita o dispositivo central (art.
> 9º), e estrutura logicamente: regra → vedações → exceções → deveres.
> Responde diretamente à pergunta com contexto regulamentar
> pertinente..."*

Pattern: when the query is narrow ("definição legal"), the system
produces a *broad* answer including regime / context / related
concepts. The judge recognizes this as bloat. When the query is
broader ("o que é neutralidade"), the broad answer is appropriate
and compactness scores higher.

This is consistent with the SYSTEM_PROMPT design (encourages
hierarchical context + cross-references) — but the prompt doesn't
distinguish "narrow definitional ask" from "open-ended explanation
ask" and serves the same shape regardless.

## What this measurement is + isn't useful for

### What it IS

- **Regression detector** — if a SYSTEM_PROMPT change makes coherence
  drop from 4.93 to 4.0, that's a real signal that the new prompt
  introduced incoherence
- **Discrimination on compactness** — flags rows where the system is
  over-answering; per-row reasoning identifies the specific bloat
- **Cheap to run alongside faithfulness** — 1 extra LLM call per row,
  ~$0.05/row added, negligible vs. the value of the new signal
- **Closes audit doc Gap #4** (RAGAS Answer Relevance) — gives the
  project a parallel-to-RAGAS dimension it didn't have

### What it ISN'T (yet)

- **Not a quality ceiling for hosting** — internal eval can saturate
  this metric without the production behavior being good. Phase 8 SLO
  targets should be set after running this same judge against the
  external benchmarks (legalbench rule recall, oab-bench discursive),
  where coherence + quality will likely show real variance
- **Not a refusal-discipline metric** — the 12.2% OOS refusal gap from
  Phase 7.5 is orthogonal. On OOS rows the judge doesn't run (no
  `expected_paragraph` to compare against); explanation quality is
  silent there. Path B (Phase 7.6.2) is the parallel attack on that gap.

## Cross-eval surface comparison (recommended next step, NOT in this sub-phase)

A useful follow-up: run the same explanation-quality judge against
the discursive eval set (`eval/oab_bench_discursive_pilot.yaml`, 5
rows). Hypothesis: on those rows the pipeline scored 0.54 against
OAB rubrics; explanation-quality scores should be lower than the
internal 4.93/5.00/3.57, validating the metric's discriminating
power on harder data. Cost: ~$0.5. Filed as Phase 7.6 follow-up,
not blocking sub-phase close.

## Implementation summary

### What shipped

- `rag_leis/run_answer_eval.py`:
  - `EXPLANATION_QUALITY_TOOL` — structured-output schema with 3
    integer properties (coherence / general_quality / compactness, each
    0-5) + reasoning string
  - `EXPLANATION_JUDGE_SYSTEM` — prompt explicitly tells the judge NOT
    to score factual accuracy (that's faithfulness' job) — orthogonal axes
  - `judge_explanation_quality(judge, question, generated)` — mirrors
    `judge_faithfulness` shape; defensive clamp on all three axes
  - `EvalRow` ← +4 fields (3 scores + reasoning)
  - `Aggregate` ← +3 mean fields
  - `by_type` per-type breakdown ← +3 dimensions
  - `print_report` ← new columns in summary + per-type table + verbose
    per-query detail
  - `serialize_row` ← +4 JSON keys
  - `score_in_scope()` ← extracted `_fold_judge_usage_in_place` local
    helper because `judge.last_call_usage` is overwritten on every call —
    can't batch the fold; must run immediately after each call

- `tests/test_answer_eval.py`:
  - Extended `_row_with_cost()` to accept explanation-quality fields
  - 4 new tests: means-across-rows, None-treated-as-zero, by-type
    breakdown, OOS-rows-don't-count
  - Suite: 364 → 368 passing

### What's NOT in this sub-phase

- Running the judge against external benchmarks (deferred — see
  "follow-up" above)
- Adjusting SYSTEM_PROMPT based on the compactness=3.57 finding —
  premature optimization without external validation
- New CLI flag to disable the second judge call — could be useful for
  cheaper runs but path A doesn't need it; default-on is right

## Phase 7.6 progress

- ✅ **7.6.1** (this) — explanation-quality eval shipped; closes audit Gap #4
- ⏸ **7.6.2** — scope-tag refusal gate (path B); next sub-phase
- ⏸ **7.6 close** — synthesis findings doc after both sub-phases ship

## Cross-references

- [`phase-7.5-findings.md`](phase-7.5-findings.md) — parent phase, 12.2% refusal gap that 7.6.2 attacks
- [`rag-eval-metrics-audit.md`](rag-eval-metrics-audit.md) — Gap #4 should now flip ❌ → ✅
- [`paper-evaluation-graph-rag-2025.md`](paper-evaluation-graph-rag-2025.md) — Springer source of the three-axis idea
- `eval/runs/phase-7.6.1-explanation-baseline.json` — per-row scores + reasoning
- `rag_leis/run_answer_eval.py:106-263` — new judge surface
- `tests/test_answer_eval.py:230-345` — new tests
