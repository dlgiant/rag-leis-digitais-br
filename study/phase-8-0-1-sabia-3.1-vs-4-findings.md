# Phase 8.0.1 — sabia-3.1 vs sabia-4 A/B (production config)

**Date:** 2026-05-19
**Predecessor:** 2026-05-15 LLM provider decision picked sabia-3.1 vs sonnet-4-5,
explicitly deferring the sabia-3.1-vs-sabia-4 bake-off
([`llm-provider-decision-2026-05-15.md:185`](llm-provider-decision-2026-05-15.md)).
All three deferral conditions are now met (sabia-4 available, eval set >50 rows,
Phase 8.0 entry anchored to whichever generator wins).
**Eval surfaces:** `eval/answer_queries.yaml` (29) + `eval/legalbench_br_oos.yaml` (49) = 78 rows.
**Pipeline config (both variants):** generator AND self-judging relevance gate use the same model. No answer-quality judge (Phase 8.0 prod-config pattern).
**Cost (this run):** ~$0.30 of fresh sabia-4 API calls; sabia-3.1 variant was fully cached.
**Verdict:** **SWAP TO SABIA-4 AS PRODUCTION DEFAULT.** All three pre-locked criteria met.

## Pre-locked criterion result

| # | Criterion | sabia-3.1 | sabia-4 | Δ | Met? |
|---|---|---:|---:|---:|:-:|
| 1 | in-scope `false_refusal_rate` drops ≥0.07pp | 0.143 | **0.071** | **−0.071** | ✅ exactly hits threshold |
| 2 | OOS refusal recall doesn't drop more than 0.05pp | 0.594 | **0.672** | **+0.078** | ✅ improved |
| 3 | cost increase < 2× | — | — | **1.20×** | ✅ well under cap |

Three out of three. The cost criterion was tested expecting list-price +60%
(`sabia-4` is $0.80/$3.00 vs `sabia-3.1` $0.50/$2.00 per 1M tokens), but
**effective cost ratio is only 1.20×** because cosine-fast-path refusals
(no LLM call) dilute the per-token differential.

## Per-row agreement (n=78)

| Class | n | Notes |
|---|---:|---|
| Both refused | 38 | mostly OOS, cosine-fast-path or clear-refusal cases |
| Only sabia-3.1 refused (sabia-4 lenient) | **2** | one good (row 12 false-refusal fixed), one bad (Patrícia OOS leak) |
| Only sabia-4 refused (sabia-3.1 lenient) | **6** | all OOS catches — net positive for sabia-4 |
| Neither refused | 32 | mostly in-scope answers + 5 OOS leakers under both |

### The 2 "Only sabia-3.1 refused" cases

1. **`o que o decreto regulamentador do Marco Civil diz sobre guarda de logs...?`**
   — the row 12 false-refusal that sonnet-4-5 ALSO false-refused in Phase 7.8.1.
   sabia-3.1 inherited the Sabiá-family blindspot on extending from §2 incisos
   to the parent art 13's topic; sabia-4 joins opus on the right side. **Confirmed
   fix of the load-bearing predicted test case.**

2. **`Patrícia alugou um imóvel comercial próprio... qual imposto incidirá?`**
   — sabia-3.1 correctly refused (tax law, not in our digital-law corpus);
   sabia-4 incorrectly answered with 2 citations. **One OOS leak** under sabia-4
   that sabia-3.1 caught. Documented limitation.

### The 6 "Only sabia-4 refused" cases (all net wins)

| Query | Subtype | Significance |
|---|---|---|
| "como funciona o divórcio judicial no Brasil?" | OOS (a) other domain | Sabiá-3.1 leaked; sabia-4 catches |
| "princípio da minimização excessiva como fundamento autônomo…" | OOS (e) doutrina sem positivação | **Phase 7.8.x's known weak spot** — (e) was stuck at 0.000 refusal under sabia-3.1; sabia-4 catches |
| "Em que situação cabe recurso em sentido estrito?" | OOS (a) processual penal | sabia-4 catches |
| "André, comerciante, não pagou ICMS criminalmente..." | OOS (a) tributário | sabia-4 catches |
| "Eduardo promoveu queimada irregular..." | OOS (a) ambiental | sabia-4 catches |
| "imunidade de jurisdição absoluta é tradicionalmente..." | OOS (a) direito internacional | sabia-4 catches |

All 6 are legitimately OOS for our digital-law corpus. The doutrina-sem-positivação
catch (row 2) is the most strategically valuable — Phase 7.8.x's findings docs
flagged (e) as the structural weak spot of Sabiá-as-judge.

## Net OOS change: +5 catches (6 wins − 1 leak)

The +0.078pp OOS recall improvement = 5 / 64 OOS rows. Exactly matches the
+6 catches − 1 leak (Patrícia) accounting from the agreement matrix.

## Cost detail

| Measurement | sabia-3.1 | sabia-4 | Ratio |
|---|---:|---:|---:|
| Total cost (78 rows) | $0.295 | $0.356 | 1.20× |
| Mean cost / query (all rows) | $0.0038 | $0.0046 | 1.21× |
| Mean cost / answered query | $0.0051 | $0.0064 | 1.26× |
| Cost p95 (all rows) | $0.0079 | $0.0093 | 1.18× |

Per-query absolute cost stays well under 1¢. The Phase 8 SLO candidate
"Cost per query < $0.01" still has 2× headroom on sabia-4.

## Latency detail

**Critical caveat:** the A/B's variant A (sabia-3.1) was fully cache-hit
since today's earlier runs already populated those calls. Variant B
(sabia-4) was fully fresh. So the latency numbers ARE NOT apples-to-apples:

| Metric | sabia-3.1 (cached) | sabia-4 (fresh) | What this means |
|---|---:|---:|---|
| Latency p50 (ms) | 306 | 306 | Identical (cosine fast-path dominates; no LLM call) |
| Latency p95 (ms) | 614 | **2,865** | sabia-3.1 cache hits in <1s; sabia-4 fresh API call ~2.9s |
| Latency p99 (ms) | 2,797 | 4,194 | Sabiá-3.1 had 1 fresh call (~2.8s); sabia-4 fresh p99 ~4.2s |

The **only honest production-relevant latency number** is sabia-4 fresh:
**p50 306ms (fast-path), p95 ≈2.9s (full pipeline), p99 ≈4.2s**.

For sabia-3.1, the closest equivalent is the earlier Phase 8.0 baseline
(today, before sabia-4 cache populated): p95 4.92s, p99 6.07s — but that
was a mixed-cache run, also imperfect.

Honest comparison: **fresh sabia-4 (p95 2.9s) appears no worse than
mixed-cache sabia-3.1 (p95 4.9s)**. Could be a real win; could be
measurement artifact. A fresh sabia-3.1 measurement would resolve, but
costs ~$0.20 to invalidate cache.

## Why sabia-4 catches row 12 (and sabia-3.1 / sonnet don't)

Speculation worth recording: row 12 retrieves art 13 §2 incisos I/II of
Decreto 8.771 ("eliminação de dados pessoais após atingida a finalidade").
The query asks about "guarda de logs e segurança dos dados retidos."

- Smaller models (sonnet-4-5, sabia-3.1) appear to read the §2 incisos
  IN ISOLATION — they say "this is about eliminação, not guarda."
- Larger/newer models (opus-4-7, sabia-4) appear to read them in
  CONTEXT — they say "the parent art 13 is titled 'Padrões de segurança
  para guarda de logs,' so the §2 incisos ARE about guarda."

If this characterization is right, the relevance-judge prompt could
explicitly include the parent-article context (titulo, caput) to help
smaller models. Future work (Phase 7.8.3 candidate); not committed.

## Implementation decision: SWAP

Changed `rag_leis/maritaca.py:48` — `DEFAULT_MARITACA_MODEL = "sabia-4"`.

- All 438 existing tests still pass (tests use sabia-3.1 as literal
  fixtures, not as "the default", so they're unaffected).
- Phase 8.0 baseline re-anchored to sabia-4 — see
  [`phase-8-0-prod-cost-baseline.md`](phase-8-0-prod-cost-baseline.md)
  for the updated SLO candidates.
- Memory updated: production default = sabia-4 as of 2026-05-19.

## Honest limitations

1. **Latency comparison isn't apples-to-apples.** Variant A was cached;
   Variant B was fresh. Real sabia-3.1 fresh latency would need cache
   invalidation (~$0.20) to measure cleanly.

2. **n=14 in-scope is small.** The −0.07pp in-scope FR improvement is
   1-row swing at this n; could be noise. The accompanying OOS recall
   improvement (+5 of 64 rows = +0.078pp) is more confidence-inducing.

3. **One OOS leak under sabia-4 (Patrícia row).** Not a categorical
   regression but worth tracking — production telemetry should watch
   for this pattern (sabia-4 answering tax-law queries it shouldn't).

4. **No discursive-mode comparison.** The A/B was on short-answer +
   refusal-heavy surfaces. OAB-style discursive answers (Phase 7.5.5)
   could behave differently — sabia-4 might be more verbose, more
   expensive, slower. A discursive A/B should run before locking in
   the cost-per-query SLO for long-answer queries.

## Cross-references

- [`llm-provider-decision-2026-05-15.md`](llm-provider-decision-2026-05-15.md) — original sabia-3.1-vs-sonnet decision; this doc resolves its deferred sabia-3.1-vs-sabia-4 question
- [`phase-8-0-prod-cost-baseline.md`](phase-8-0-prod-cost-baseline.md) — re-anchored Phase 8.0 baseline (sabia-4)
- [`phase-7.8.1-inscope-opus-regression.md`](phase-7.8.1-inscope-opus-regression.md) — row 12 / Decreto 8.771 backstory (where Sonnet failed but Opus succeeded; now sabia-4 joins Opus)
- `eval/runs/phase-8-0-1-sabia-3.1-vs-4.json` — per-row data + agreement matrix
- `scripts/phase_8_0_1_sabia_3_1_vs_4.py` — re-runnable A/B harness
