# Phase 7.5.5 findings — OAB-bench discursive pilot (5 rows)

**Date:** 2026-05-17
**Eval set:** `eval/oab_bench_discursive_pilot.yaml` (5 rows, manually curated)
**Source:** `maritaca-ai/oab-bench` v2 (Apache-2.0, OAB editions 39-44, 2023-2024)
**Run config:** Voyage-3-large + Sabiá-3.1 + `title+label+nav+caput+text` + top_k=10;
opus-4-7 judge with `score_pct ∈ [0.0, 1.0]` tool schema
**Run log:** `eval/runs/phase-7.5.5-oab-bench-discursive.json`

## Headline result

**discursive_mean_pct = 0.540 (54%)** across 5 rows; **answered_rate = 100%** (no refusals).

Below the OAB 2ª fase passing threshold (60% / nota 6.0). The mean is bimodal,
not central: 3 rows ≥ 0.84 vs 2 rows ≤ 0.25.

## Per-row breakdown

| QID                                     | Score | Diagnosis |
|-----------------------------------------|-------|-----------|
| `40_direito_constitucional_questao_2`   | **1.00** | Perfect — identified inconstitucionalidade + cited CRFB art.21 VII exatamente como gabarito |
| `39_direito_civil_questao_3` (LGPD)     | **0.84** | Strong — cobriu A1 (LGPD art.8 §5) integralmente; em A2 citou art.18 VI em vez de art.15 III/art.16 |
| `39_direito_penal_questao_1` (terror)   | **0.46** | Parcial — mencionou desclassificação para crime de explosão (CP art.251), mas não fundamentou com Lei 13.260/2016 (OUT of corpus) |
| `39_direito_constitucional_questao_1`   | **0.25** | Citou CRFB art.170 parágrafo único mas não respondeu objetivamente "Sim" à pergunta; faltou explicitar tese |
| `39_direito_civil_questao_1` (comodato) | **0.15** | **Hallucination** — discutiu usucapião urbana (CF art.183) ignorando o pedido sobre comodato; conclusão certa por sorte, fundamentação completamente errada |

## What the bimodal scores reveal

The two extremes confirm the diagnostic pattern from 7.5.3 + 7.5.4:

- **In-corpus + direct hit** (rows 1-2 above): pipeline drafts solid legal text
  with correct URN citation. 1.00 and 0.84 are competitive scores by OAB
  examiner standards.
- **Out-of-corpus** (row 5 — comodato CC arts.579-585, OUT of our 11-21
  window): pipeline **invented** a usucapião answer using adjacent CF material
  rather than refusing. Same Pattern B failure as 7.5.3 (citation
  hallucination toward adjacent corpus).
- **Partial coverage** (row 3 — penal): partial credit because CP is in corpus
  but the dispositivo central (Lei 13.260/2016) is not.

The hypothesis from 7.5.4 ("pipeline excellent at finding what's in-corpus,
bad at refusing what isn't") survives the discursive surface. The bug is
*generative*: when retrieval finds nothing useful, the model fills with
plausible-looking adjacent doctrine instead of stopping.

## What discursive scoring adds vs. citation-only metrics

The 5-question pilot showed three things that pure citation-precision metrics
miss:

1. **Drafting quality** — row 3 (penal) cited a real CP article correctly but
   missed the dispositivo central. Citation metrics would score this as a
   partial hit; the judge correctly scored 0.46 reflecting both the partial
   citation AND the weak fundamentação.
2. **Hallucination severity** — row 5 (comodato) returned valid-looking
   citations (`urn:lex:.../1988~art183`) for a question about an entirely
   different contract type. Pure URN-validity checks miss this; the judge
   caught it (0.15).
3. **Answer objectivity** — row 4 (constitucional) cited the right article
   but failed to answer the actual question. The judge identified this as a
   distinct failure (0.25, not 0.0) — partial credit for relevant citation,
   penalty for failing to respond objectively.

This validates the LLM-judge discursive approach as a complementary signal
to retrieval/citation metrics for production hardening.

## Bug discovered — judge cost not accounted

The Phase 7.5.2 cost instrumentation tracks `pipeline.llm.last_call_usage`
but **not** `judge.last_call_usage`. This run reported:

```
cost_total_usd:     $0.0283  (5 Sabiá generation + 3 retry calls)
total_llm_calls:    8        (excludes 5 opus judge calls)
```

The true cost was ~$0.59 (estimated):
- Sabiá generation: $0.028 (measured correctly)
- Opus judge (5 calls × ~5k input + 0.5k output): ~$0.56

**Fix scope:** `_score_discursive()` in `run_concurso_eval.py` must accumulate
`judge.last_call_usage` into the per-record `cost_estimate_usd`/`tokens_used`
fields after each `judge.complete_structured()` call. Same pattern needed
when answer_eval.py adds judge accounting for faithfulness scoring.

This is a **measurement bug, not a budget bug** — actual spend was still
within Phase 7.5.5's ~$1-2 plan envelope. But the cost numbers reported
in eval logs are systematically undercounting LLM-judge runs by ~20×.

Filed for Phase 7.5.7 (SRE Golden Signals) — judge accounting belongs in
the cost instrumentation pass.

## Methodology — manual curation rationale

5 questions chosen for **diagnostic coverage**, not random sampling:

- 1 LGPD direct (validates digital-law primary use case)
- 2 Constitutional (CF fully indexed — should land near 1.0; one did, one didn't)
- 1 Penal partial (CP indexed; Lei 13.260 OUT — measures degradation)
- 1 Civil OUT-of-window (probes sub-corpus gap — confirmed hallucination)

At n=5, point estimates have wide CIs (±~25pp). The value is **failure-mode
diagnosis**, not a converged refusal-rate measurement. The OOS_A
legalbench.br set (7.5.3, n=49) and rule-recall set (7.5.4, n=40) are the
converged measurements; this pilot is qualitative confirmation that the same
patterns surface in the discursive generation surface.

## Implications

**For Phase 8 SYSTEM_PROMPT iteration:** the discursive surface confirms what
the OOS+rule-recall split already showed — the pipeline needs **explicit
refusal training for out-of-corpus content** more than it needs better
retrieval. Row 5 is the canonical bug: question has clear answer in CC
arts.579-585; pipeline doesn't have those articles; pipeline drafts an
answer about usucapião (CF art.183) as if it were comodato. No prompt
adjustment to retrieval will fix this — it requires either:
- Stronger refusal instruction ("if the retrieved articles don't address
  the question's specific dispositivo, refuse"), OR
- Pre-generation classifier that checks "do retrieved chunks plausibly
  contain the answer?" before letting the LLM draft.

**For Phase 7.5.6 (OAB 39-44 LGPD manual):** this pilot established the
discursive scoring infrastructure works (`DISCURSIVE_TOOL`, `judge_discursive`,
aggregate fields). The next 4-6h human curation pass will use the same
schema; just need to add ~10-15 LGPD-focused discursive rows from OAB
39-44 + similar concursos.

**For audit doc (`study/rag-eval-metrics-audit.md`):** §3 should add a new
row for discursive scoring as an externally-anchored generation-quality
metric, distinct from in-corpus citation precision.

## Cross-references

- `study/phase-7.5.3-legalbench-oos-findings.md` — OOS refusal (12.2%) failure modes
- `study/phase-7.5.4-rule-recall-findings.md` — in-corpus citation precision (97.5%)
- `study/phase-7.5-eval-expansion-plan.md` — parent plan, sub-step 7.5.5
- `eval/oab_bench_discursive_pilot.yaml` — eval set
- `scripts/extract_oab_bench_discursive.py` — extractor (re-runnable)
- `rag_leis/run_concurso_eval.py` — discursive scoring runner additions
