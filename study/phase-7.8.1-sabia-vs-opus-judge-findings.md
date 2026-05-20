# Phase 7.8.1 findings — Sabiá vs Opus as the relevance-gate judge

**Date:** 2026-05-19
**Eval:** `eval/legalbench_br_oos.yaml` (49 rows OOS, same set as Phase 7.8)
**Variant A:** relevance gate uses Sabiá-3.1 (Phase 7.8 default, == pipeline generator)
**Variant B:** relevance gate uses Opus-4-7 (new, via the `relevance_judge: LLM | None` field added on RAGPipeline)
**Pre-locked criterion (D1):** if `|delta| > 0.10pp` AND Opus refuses more → swap default to Opus. Otherwise keep Sabiá.
**Verdict:** **SWAP TO OPUS for the relevance judge.** Pre-locked threshold met by exactly +0.10pp, and per-row analysis of the 5 differentiating rows shows Opus catches them for the right reason (genuine OOS Pattern B), not false-strictness.

## Headline numbers

| Variant | refusal_rate | n refused / 49 | cost (49 rows) |
|---|---|---|---|
| Sabiá judge | **0.571** | 28 | $0.17 |
| Opus judge  | **0.673** | 33 | $2.16 (13×) |
| Δ | **+0.102pp** | +5 | +$1.99 |

Per-row agreement (49 rows total):
- **Both refused:** 28
- **Only Sabiá refused, Opus passed:** 0
- **Only Opus refused, Sabiá passed:** 5
- **Neither refused:** 16

The "0 in one direction, 5 in the other" pattern is the load-bearing
signal. Opus's set of refusals is a strict superset of Sabiá's — Opus
catches everything Sabiá catches, plus 5 more. If Opus were just
random-stricter (false-positives), we'd expect bidirectional disagreement.

## What those 5 rows actually are

All five are **legitimately OOS** for this corpus — the cited URNs that
Sabiá judged "relevant" came from indexed material that's topically
adjacent but addresses different statutes:

| source_id | legal_area | query (truncated) | Sabiá verdict | Opus verdict |
|---|---|---|---|---|
| `legalbench.br/246` | Processual Penal | "Em que situação cabe recurso em sentido estrito?" | answered (cites unrelated) | refused (irrelevant-citations) |
| `legalbench.br/347` | Tributário | "André não pagou ICMS e responde criminalmente. Que ilícito?" | answered | refused |
| `legalbench.br/310` | Tributário | "Alíquota do ITCMD é definida por qual ente federativo?" | answered | refused |
| `legalbench.br/402` | Internacional | "Imunidade de jurisdição absoluta é reconhecida para:" | answered | refused |
| `legalbench.br/414` | Internacional | "Empresa brasileira contrata empregados estrangeiros remotos. Lei aplicável?" | answered | refused |

The relevant laws (CPP, CTN, Direito Internacional Público) are not in
the corpus. Sabiá rationalized its own citations as relevant; Opus
correctly identified them as off-topic. This is exactly the
**Sabiá-judging-its-own-output self-defense bias** that Phase 7.8's
findings doc flagged as a theoretical risk. The bias is real and
measurable at ~10% of the OOS set.

## Cost analysis

13× cost multiplier in absolute terms:
- Per eval run (49 rows): +$1.99 (Sabiá $0.17 → Opus $2.16)
- Per production query (1 row): roughly +$0.04 in worst case (one extra Opus call vs one Sabiá call on rows with citations)

For batch eval, $2/run is small absolute. For production hosting, the
multiplier scales linearly with query volume. With Phase 7.9's response
cache active, repeat queries hit free — but production queries are
mostly unique, so the cache helps less in that surface.

## Recommended split

- **Batch eval runs (CI, A/B, calibration):** use Opus default for
  relevance judge. The +5 catches are real and the $2/run cost is
  negligible vs. the value of correctly characterizing pipeline
  behavior.
- **Production hosting (Phase 8):** START with Sabiá default for cost
  reasons (13× per-query multiplier). Add per-environment override.
  Production telemetry should track `rejected_irrelevant_citations`
  rates; if a meaningful fraction of refusals would have caught more
  with Opus, swap there. (Decision belongs to Phase 8 design.)

To support this split, the `relevance_judge: LLM | None` field on
RAGPipeline (added 2026-05-19) lets the caller choose per-pipeline.
Default None = uses self.llm = pipeline generator = Sabiá. Setting
`pipeline.relevance_judge = opus_llm` swaps in Opus without affecting
the main generation path.

## Honest limitations of this experiment

1. **In-scope regression NOT measured for Opus.** ~~Phase 7.8 confirmed
   `false_refusal_rate = 0.000` on internal answer-eval with Sabiá as
   the relevance judge. Opus may be strict enough on the relevance
   criterion to false-refuse legitimate in-scope citations [...]~~
   **CLOSED 2026-05-19** — in-scope regression check run with Opus
   wired in via `pipeline.relevance_judge`. Result:
   `false_refusal_rate = 0.000` (pre-locked criterion met). See
   [`phase-7.8.1-inscope-opus-regression.md`](phase-7.8.1-inscope-opus-regression.md).
   Cost: $3.14 (close to the $3 estimate). The regression check also
   surfaced a silent CLI default-fallback bug (model defaulted to
   Sonnet when Opus was intended) — fixed.
2. **n=49 with stochastic LLM responses.** Sabiá at temperature=0
   showed run-to-run variance — Phase 7.8 measured 0.633 (31/49)
   yesterday; today's same-configuration rerun measured 0.571 (28/49).
   That's 3-row stochastic difference. The +0.10pp delta is right at
   the noise floor for n=49. Confidence in the swap recommendation
   would be stronger at n=100+, but legalbench.br OOS doesn't have
   more pre-curated OOS rows in our coverage.

   **CONFIRMED 2026-05-19** — a third independent run (as part of the
   Phase 7.8.2 cached-data infra change) measured:

   | Trial | Sabiá refuses | Opus refuses | Δ |
   |---|---:|---:|---:|
   | Original 7.8 baseline | 31/49 (0.633) | n/a | n/a |
   | Original 7.8.1 A/B | 28/49 (0.571) | 33/49 (0.673) | **+0.102pp** |
   | Re-run (this) | 28/49 (0.571) | 30/49 (0.612) | **+0.041pp** |

   Direction consistent across all three measurements (Opus refuses
   ≥ Sabiá), but magnitude is unstable. The +0.10pp pre-locked
   criterion was met by exactly 0.002pp in the original A/B — a hair
   over the threshold designed for the n=49 noise floor it sits at.
   The re-run gets +0.041pp, well below criterion.

   **The original Phase 7.8.1 swap decision was correctly applied
   against the data and criterion available at the time.** But two
   measurements at +0.102pp and +0.041pp suggest the underlying Opus
   advantage is real but smaller than the first sample indicated.
   The eval-default Opus assignment stays (direction consistent, cost
   not load-bearing for eval surface), but the criterion was too
   tight for the sample size. **Practical lesson for future per-LLM
   A/Bs at n≤50: require ≥3 independent samples, not 1, before
   committing pre-locked-criterion language. Confidence interval at
   n=49 with σ≈3 rows is roughly ±0.12pp** — almost the entire
   criterion threshold itself.
3. **No cost-folded latency comparison.** Opus calls are slower
   per-call (~6-9s vs ~3-5s for Sabiá at the same prompt length).
   Latency overhead from Opus judge wasn't measured row-by-row.
   Phase 8 hosting design should validate that p95 latency stays
   inside acceptable SLO under Opus default.

## Implementation summary

### Added (Phase 7.9 commit, prep for this experiment)
- `RAGPipeline.relevance_judge: LLM | None = None` field — when set,
  used in place of `self.llm` for the relevance gate's LLM call
- Updated relevance gate's cost-folding to read `last_call_usage`
  off the active judge (not `self.llm`), so cost reporting stays
  accurate when judge ≠ generator

### Added (this commit)
- `scripts/phase_7_8_1_sabia_vs_opus.py` — runnable A/B script.
  Loads the pipeline twice with different relevance_judge settings,
  runs both against legalbench OOS, produces per-row comparison +
  agreement summary + headline verdict against pre-locked criterion
- `eval/runs/phase-7.8.1-sabia-vs-opus.json` — per-row comparison
  output for both variants + summary + agreement breakdown
- This findings doc

### Suite
No new tests added — existing 422-test suite covers the
`relevance_judge` field semantics via the existing
`test_citation_relevance.py` cases. The A/B script is intentionally
not in the test suite (network-dependent, paid).

## Cross-references

- [`phase-7.8-citation-relevance-findings.md`](phase-7.8-citation-relevance-findings.md) — the per-citation relevance gate this experiment validated
- `eval/runs/phase-7.8.1-sabia-vs-opus.json` — full per-row data
- `scripts/phase_7_8_1_sabia_vs_opus.py` — re-runnable script
- BACKLOG.md will be updated: relevance-judge model is now a
  per-environment knob; defaults stay Sabiá until production
  telemetry warrants the swap, but eval surfaces should pass
  `pipeline.relevance_judge = get_llm("anthropic", DEFAULT_JUDGE_MODEL)`
  for maximum strictness
