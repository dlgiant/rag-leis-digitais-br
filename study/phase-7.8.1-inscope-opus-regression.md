# Phase 7.8.1 — In-scope regression check with Opus as the relevance judge

**Date:** 2026-05-19
**Eval:** `eval/answer_queries.yaml` (29 rows: 14 in-scope, 15 OOS)
**Pipeline:** Sabiá-3.1 generator + Opus-4-7 relevance judge + Opus-4-7 answer-quality judge
**Pre-locked criterion:** `false_refusal_rate` must stay at **0.000** (Phase 7.8 baseline established this bar on the same eval; the 7.8.1 OOS A/B left it as the load-bearing safety check).
**Verdict:** **PRE-LOCKED CRITERION CLEARED.** false_refusal_rate = 0.000 with Opus as the relevance judge. Limitation #1 from `phase-7.8.1-sabia-vs-opus-judge-findings.md` is closed.

## Why this run existed

The Phase 7.8.1 Sabiá-vs-Opus A/B ran only on legalbench OOS (49 rows).
Opus refused 5 more rows than Sabiá — all legitimately OOS, all caught for
the right reason. That triggered the swap to Opus as the eval-default
relevance judge. The OOS-only evidence left one limitation explicit in the
7.8.1 findings doc:

> **In-scope regression NOT measured for Opus.** Phase 7.8 confirmed
> `false_refusal_rate = 0.000` on internal answer-eval with Sabiá as the
> relevance judge. Opus may be strict enough on the relevance criterion to
> false-refuse legitimate in-scope citations [...]. **Before promoting
> Opus to production default**, an in-scope regression check is required.

This run executes that check.

## Headline numbers

Comparison anchor: Phase 7.8 in-scope regression check
(`eval/runs/phase-7.8-inscope-regression-check.json`), which used Sonnet
as generator and Sabiá as relevance judge. The cleanest single-variable
comparison would have been Sabiá-gen + Sabiá-judge vs. Sabiá-gen +
Opus-judge on the same eval, but that paired baseline doesn't exist on
the in-scope set (only on legalbench OOS, per the 7.8.1 doc). The
absolute-bar comparison still works: `false_refusal_rate = 0.000` is the
pre-locked criterion, and we hit it.

| Metric | 7.8 baseline (Sonnet+Sabiá) | This run (Sabiá+Opus) | Δ | Notes |
|---|---|---|---|---|
| **false_refusal_rate** | **0.000** | **0.000** | **0.000** | ✅ pre-locked criterion met |
| oos_refusal_recall | 0.933 | 0.667 | −0.27 | **Generator effect**, not relevance judge — see below |
| refusal_accuracy (macro) | 0.966 | 0.828 | −0.14 | Composed of the two above |
| faithfulness (in-scope mean) | 4.50 | 4.21 | −0.29 | Generator effect (Sabiá < Sonnet on prose) |
| coherence (in-scope mean) | 5.00 | 4.64 | −0.36 | Generator effect |
| quality (in-scope mean) | 5.00 | 4.50 | −0.50 | Generator effect |
| compactness (in-scope mean) | 3.50 | 3.57 | +0.07 | Flat |
| cit_precision strict | 0.318 | 0.357 | +0.04 | Sabiá retrieves slightly tighter |
| cit_recall | 0.762 | 0.727 | −0.04 | Flat |
| Cost total (USD) | $2.82 | $3.14 | +$0.32 | +14 Opus relevance calls, consistent with +$0.04/row estimate |
| LLM calls | 105 | 111 | +6 | Includes the new Opus relevance-judge calls on rows with citations |
| Latency p50 | 16,792 ms | 6,265 ms | −10,527 ms | Apparent gain — see "Honest caveats" |

`false_refusal_rate = 0.000` is the load-bearing number. The other shifts
have known attributions (generator change, not relevance judge):

- **Faithfulness / coherence / quality drops** mirror the Sabiá-vs-Sonnet
  prose-quality gap measured in `phase-7.8.1-sabia-vs-opus-judge-findings.md`
  and the broader Sabiá-vs-Opus comparison work pre-7.8.1. Generator-side
  effect, not judge-side.
- **OOS refusal recall −0.27** comes from Sabiá leaking on the doutrina-
  sem-positivação subtype (`(e)` in the OOS subtype breakdown: 0.000
  refusal rate). Phase 7.8.1 OOS findings already showed Opus refuses
  more than Sabiá on hard OOS (legalbench), but the internal eval's OOS
  is partly a generator-side problem.
- **Latency p50 drop is misleading.** This run's p50 (6.3s) is mostly
  driven by cache hits on the generator + answer-judge calls (the eval
  re-ran with `--llm-cache-dir data/cache/llm` already populated from
  the initial run). The first-pass Sabiá+Opus latency would have been
  closer to the +1.6s Opus-call overhead estimated in 7.8 findings.

## Row 12 detail — the false-refusal that almost shipped

This run was actually executed **twice**. The first execution had
`false_refusal_rate = 0.071` (1 in-scope row refused: row 12, the cross-doc
question about Decreto 8.771/2016 guarda de logs). Investigation revealed
that the relevance judge wasn't actually Opus — the CLI default fallback
silently used Sonnet-4-5 (the generator default), not Opus-4-7 (the
judge default), when `--relevance-judge-model` was omitted.

- Sonnet relevance judge on row 12: both Decreto 8.771 art13 §2 incisos
  marked `relevant=False` ("trata de eliminação de dados pessoais, não
  de guarda de logs"). The gate fired → row refused.
- Opus relevance judge on row 12 (same prompt, after fix): both incisos
  marked `relevant=True` ("art. 13 do Decreto 8.771/2016 [...] trata
  justamente dos padrões de segurança e diretrizes para guarda de
  dados/logs, incluindo a obrigação de eliminação dos registros").

Sonnet's strictness on this row would have been a real false-refusal in
production. Opus correctly read the dispositivo as on-topic. The
mechanism that surfaced this was the LLM cache — two different cache
entries for the "same" prompt revealed that one of the calls had used a
different model. Without the cache, the silent default would have
shipped as "Opus performance" with a hidden Sonnet underneath.

## Honest caveats

1. **Paired baseline (Sabiá + Sabiá on in-scope) is not measured.**
   The 7.8.1 OOS A/B compared Sabiá+Sabiá vs Sabiá+Opus on legalbench
   OOS. The in-scope equivalent — Sabiá+Sabiá on the 14 in-scope
   rows — was skipped. The closest baseline (Sonnet generator + Sabiá
   relevance) shows `false_refusal_rate = 0.000`. Both anchors agree
   on the absolute bar, but a same-generator paired delta isn't on
   record. n=14 in-scope is small enough that single-row stochastic
   moves are 0.07pp — the +1 false-refusal swing we just saw between
   Sonnet and Opus on row 12 is exactly that magnitude.

2. **n=14 in-scope.** False-refusal-rate 0.000 at n=14 is consistent
   with the underlying rate being anything ≤ 1/14 ≈ 7%. The pre-locked
   criterion is "stays at 0.000", which we met; a stronger test at
   n≥100 in-scope would be desirable. Internal answer-eval doesn't have
   more rows; closing this would need a curated in-scope expansion or
   gold-labeled rows from oab/legalbench's in-scope subset.

3. **The cache nudges the result on row 12.** Row 12's Opus relevance
   judge call hit cache (from a diagnostic invocation, see
   `scripts/diagnose_row12.py`). It returned `relevant=True` on both
   incisos. A cold Opus call on the same prompt could in principle
   return differently; LLM temperature=0 doesn't fully remove
   variance (the OOS findings doc measured 3-row variance on the
   49-row Sabiá baseline). The cached result is stable, but the
   *first-ever* Opus call's variance isn't bounded.

4. **OOS-side leakage is unchanged from Phase 7.8.1 OOS findings.**
   On the 5 internal-OOS rows that leaked through, Opus correctly
   marked 4/5, 4/5, 5/6, 1/4, and 0/5 citations as irrelevant — but
   the gate requires **all** citations irrelevant to fire. **One
   stretchy citation defeats the gate.** Relaxing to "≥80% irrelevant"
   would catch 3 of 5 leakers; future work item below.

## What changed in the codebase

### Fix (substantive)
- `rag_leis/run_answer_eval.py` — when `--relevance-judge-provider
  anthropic` is set without `--relevance-judge-model`, the default
  model is now `DEFAULT_JUDGE_MODEL` (Opus), not `DEFAULT_GENERATOR_MODEL`
  (Sonnet). The previous behavior silently used Sonnet, producing
  misleading "Opus run" output. The startup banner shows the active
  model name; verify it matches intent.

### Fix (silent bug discovered en route)
- `rag_leis/run_answer_eval.py` — `serialize_row()` now emits
  `rejected_irrelevant_citations` (added in Phase 7.8 to the
  `RAGAnswer` dataclass but never made it into the eval JSON output).
  Without this field, audit of which citations the relevance gate
  rejected required re-running the eval or scraping the LLM cache.

### Diagnostic
- `scripts/diagnose_row12.py` — direct invocation of the relevance
  judge on row 12's data, plus cache-key inspection to compare
  Sonnet's vs Opus's decision on the same prompt. Re-runnable.

## Future-work observation (NOT in 7.8.1 scope)

The 5 OOS rows that leaked through in this run had Opus mark
**most but not all** of their citations as irrelevant (4/5, 4/5, 5/6,
1/4, 0/5). The current gate fires only when ALL are irrelevant —
intentionally conservative. A "≥80% irrelevant" threshold would
have caught 3 of these 5 leakers (rows where 4/5 or 5/6 were
marked irrelevant). Costs: a single stretchy citation defeats the
strict-all gate; partial-relevance threshold would risk false
refusals if Opus mis-marks one citation among many legitimate ones.
Worth a future Phase 7.8.2 calibration if OOS recall on the internal
eval becomes a phase-8 entry blocker.

## Cross-references

- [`phase-7.8.1-sabia-vs-opus-judge-findings.md`](phase-7.8.1-sabia-vs-opus-judge-findings.md) — Limitation #1 listed here; this doc closes it
- [`phase-7.8-citation-relevance-findings.md`](phase-7.8-citation-relevance-findings.md) — the gate this validated
- `eval/runs/phase-7.8.1-inscope-opus-relevance.json` — per-row results
- `eval/runs/phase-7.8.1-inscope-opus-relevance.log` — full run output
- `eval/runs/phase-7.8-inscope-regression-check.json` — Sonnet+Sabiá baseline
- `scripts/diagnose_row12.py` — diagnostic + cache-comparison script
