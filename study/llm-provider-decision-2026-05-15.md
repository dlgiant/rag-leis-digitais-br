# LLM Provider Decision — Sabiá-3.1 vs Sonnet 4.5

**Date**: 2026-05-15
**Phase**: 4.0.d — D9 (LGPD residency) resolution
**Verdict**: **Recommend swap to Marítaca Sabiá-3.1 as default generator**
(under production framing). Anthropic Claude stays as fallback option +
canonical judge. Decision is data-driven; see `study/llm-comparison-2026-05-15.json`
for raw numbers.

## Why this decision matters

Project framing flipped to production on 2026-05-15. D9 (LGPD data
residency) became load-bearing: Anthropic hosts in US; queries
containing personal data crossing the border is a compliance risk
that ToS disclaimers patch but don't fix.

Marítaca hosts Sabiá in São Paulo. The question wasn't "is Sabiá good
enough?" — it was "can it match Claude on the project's actual eval?"
Before today, that was a guess. After 3 runs each, it's data.

## Headline numbers (3 runs each, 16-row answer-eval)

| Metric | sonnet-4-5 | sabia-3.1 | Δ |
|---|---|---|---|
| Faithfulness mean (0-5, opus-judged) | 4.051 | **4.205** | +0.15 |
| Citation precision strict | 0.40 | **0.49** | +0.09 |
| Citation precision lenient | 0.671 | **0.759** | +0.09 |
| Citation recall | 0.825 | **0.842** | +0.02 |
| Citation F1 (strict) | 0.45 | **0.53** | +0.08 |
| Refusal accuracy | 0.938 | 0.938 | 0 |
| Rejected citation rate | **0.000** | 0.022 ± 0.031 | -0.022 |
| Wall-clock per run | 209.3 ± 5.8s | **114.8 ± 5.1s** | -45% |

**Decision matrix (Phase 4.0 thresholds)** — both providers PASS ALL 4:

| Threshold | Required | sonnet-4-5 | sabia-3.1 |
|---|---|---|---|
| faithfulness ≥ 3.7 | ✅ | 4.051 ✅ | 4.205 ✅ |
| cit_precision_lenient ≥ 0.55 | ✅ | 0.671 ✅ | 0.759 ✅ |
| rejected_citation_rate ≤ 0.05 | ✅ | 0.000 ✅ | 0.022 ✅ |
| refusal_accuracy ≥ 0.85 | ✅ | 0.938 ✅ | 0.938 ✅ |

## Per-type breakdown — where each model wins

| Type | sonnet | sabia | Notes |
|---|---|---|---|
| **definicao** (n=5) | faith 4.80, P_l 0.51 | faith 4.67, **P_l 0.72** | Sabiá huge P_lenient lead; recall 0.98 vs 0.87 |
| **enumeração** (n=4) | **faith 2.67**, ref_acc 0.75 | **faith 3.33**, ref_acc 1.00 | Sabiá fixes the row 7 sanções non-determinism that plagued sonnet |
| **citacao-literal** (n=3) | P_l 1.00, faith 5.0 | P_l 1.00, faith 5.0 | Tie. Both perfect. |
| **cross-doc** (n=1) | P_l 0.86, faith 3.0 | P_l 0.86, faith 3.0 | Tie. |
| **OOS** (n=3) | ref_acc 1.00 | ref_acc 0.67 | Sabiá loses 1 OOS — divorce edge case (see below) |

Sabiá leads on **definicao** and **enumeração** — the two types where
PT-BR fluency and legal-Portuguese fine-tuning likely give it an edge.
Sonnet ties or loses everywhere except OOS, where it wins on 1 edge case.

## The two Sabiá-3.1 issues — diagnosed, not deal-breakers

### Issue 1: 5 rejected URNs in run 0 (sanções ANPD)

The sanções enumeration query — already a known stress test (top_k=10 vs
9-10 gold URNs) — caused Sabiá to cite URNs that **weren't in the top-K
context** but DO exist in the corpus. Inspection:

```
cited (verified): art52;inc3, art52;par1, art52;par1;inc1-10, art52;par6;inc1
cited (rejected): art52;inc1, inc2, inc4, inc5, inc6  ← real URNs, not in top-K
```

Sabiá appears to **extrapolate** from URN patterns it sees in context
(par1;inc1...inc10) and confidently cite siblings (inc1...inc6 directly
on art52) without checking whether they were retrieved. Sonnet doesn't
do this.

**Mitigation**: `verify_citations` catches **all 5** before they reach
the user. The `rejected_citation_rate` of 0.022 is *what got caught* —
the answer text presented to the user is clean. This is the entire
reason cite-and-verify exists.

**Production impact**: zero, **iff verify_citations stays in the
pipeline** (which it does — it's the load-bearing guard). Without
verify, Sabiá's 2.2% rejected URN rate would surface in production.

### Issue 2: OOS divorce — refused 0/3 (sonnet refused 3/3)

The query "como funciona o divórcio judicial no Brasil?" was authored
as OOS (corpus = direito digital, not direito de família). But the
corpus contains **one chunk** that mentions divorce: CF art. 226 §6
("O casamento civil pode ser dissolvido pelo divórcio").

  - Sonnet's behavior: emits canonical "Não há informação suficiente"
    refusal because the chunk doesn't substantively answer the procedural
    question. Conservative.
  - Sabiá's behavior: cites the chunk, answers with the thin content
    available, doesn't refuse. Liberal.

This is a **gold-set debate**, not a Sabiá bug. Both behaviors are
defensible:
  - For a strict legal RAG → sonnet's conservatism wins.
  - For a "best-effort answer with caveats" UX → sabiá's behavior wins.

The expected_paragraph for this row says "pipeline should refuse" —
under that gold, sabiá fails. But the OOS classification itself is
borderline; the chunk DOES exist.

**Mitigation options**:
1. Re-classify the divorce row as in-scope partial-answer (gold update);
   sabiá's behavior becomes correct.
2. Keep the row as OOS, document that sabiá fails this specific edge case,
   monitor in production telemetry.
3. Tighten Sabiá's SYSTEM_PROMPT for OOS detection — instruct it to
   refuse when context is "thin" even if non-empty.

Recommended: option 2 (document, monitor) for now. Re-evaluate when OOS
test set expands to ≥50 rows in Phase 5.

## Cost + latency

Wall-clock per full eval run (16 queries):
- sonnet-4-5: 209s mean → ~13s per query
- sabia-3.1: 115s mean → ~7s per query — **45% faster**

The latency win is partly real (BR region = lower RTT) and partly
"smaller model = less compute". For user-facing production, the gap
shrinks once `judge` (kept on opus-4-7) is removed from the loop —
production won't call the judge. But the **generator** side is the
hot path, and Sabiá's wall-clock win there is genuine.

Cost-per-run is harder to attribute without per-call token counts in
the JSON dump (Phase 4.0.c didn't instrument that). Marítaca pricing
is published as ~50-60% below Anthropic; if that holds for our token
mix, full eval run cost drops by similar fraction. Total budget for
3 runs each: estimated ~$0.85 anthropic + ~$0.30 marítaca = ~$1.15.
Cheap.

## D9 resolution

D9 (LGPD data residency) — **resolved as YES, hard requirement is
achievable** via Marítaca:

  - User queries (potentially containing personal data) → BR-resident
    Sabiá-3.1
  - Document embeddings (public Brazilian law, no PII) → Voyage US (acceptable
    per the prior analysis — public data, no LGPD scope)
  - Query embeddings (potentially PII) → Voyage US **with** Phase 4.2
    PII redactor as defense-in-depth (still BR for sensitive paths in
    the future if Marítaca offers embeddings)
  - Judge (faithfulness scorer) → opus-4-7 US — but the judge processes
    only pre-curated `expected_paragraph` (human-written) and
    `generated_answer` (already-redacted, post-LLM-generator). Less
    PII risk than the live query path.

Phase 9 compliance (DPA, ToS, etc.) reflects this stack:
  - Marítaca DPA for the generator + query embeddings if migrated later
  - Voyage DPA for embeddings (until migrated)
  - Anthropic DPA for the judge only (lower-stakes path)

## Recommendation

**Swap default generator to Marítaca Sabiá-3.1**. Specifically:

1. **`rag_leis/llm.py`**: change `DEFAULT_GENERATOR_PROVIDER = "anthropic"`
   to `"maritaca"`. Generator model default: `sabia-3.1`.
2. **`rag_leis/rag.py`** `load_pipeline()`: same shift.
3. **`rag_leis/run_answer_eval.py`** CLI default: `--llm-provider maritaca`.
4. **Judge stays opus-4-7** (Anthropic) — no residency concern; the
   judge is a quality-assurance loop, not a user-facing path.
5. **Anthropic stays a first-class supported provider** — not deprecated.
   Phase 7.4 (model fallback layer) keeps Sabiá-3.1 → Sonnet 4.5 as one
   of the canonical fallback configurations: if Marítaca 429s or fails
   the structured-output contract, fall back to Sonnet.
6. **Re-eval is non-destructive**: existing `eval/runs/phase-2-*.json`
   and `phase-3-*.json` remain as historical baselines. New runs go under
   `eval/runs/sabia-3.1-baseline-2026-05-XX.json` etc.

### What this decision is NOT

- **NOT** a final endorsement of Sabiá over Claude across the board.
  Anthropic has a better track record on the cite-and-verify guarantee
  (zero hallucinations across all our runs vs sabiá's 2.2% caught-by-verifier
  rate). For applications without `verify_citations` in the loop, Anthropic
  is still safer.
- **NOT** a recommendation to migrate the judge. opus-4-7's strength as
  faithfulness scorer is well-established by our own runs.
- **NOT** decided forever. Re-run this comparison when sabia-4 matures,
  when Marítaca publishes new versions, or when the eval set expands
  to ≥50 rows (Phase 5).

## Open items added to BACKLOG

- **Per-call token counting** — `run_llm_comparison.py` doesn't track
  tokens used; add to enable real cost comparison (not just inferred).
- **OOS divorce edge case** — decide whether to re-classify the row as
  in-scope or tighten Sabiá's OOS detection prompt.
- **Long-tail rejected_citation_rate monitoring** — Sabiá's 0.022 was
  driven by 1/3 runs having 5 hallucinations. With more runs, what's
  the steady-state rate? Run 10+ before locking the threshold.
- **Marítaca embeddings investigation** — D9 deferred this on the query
  embedding axis. Phase 5 or earlier, evaluate Marítaca embeddings if
  available (currently unconfirmed).

## Updated Phase 7.4 (model fallback) spec

```python
PROVIDER_FALLBACK_CHAIN = [
    ("maritaca", "sabia-3.1"),     # default
    ("anthropic", "claude-sonnet-4-5"),  # fallback on 429 / parse fail
    # ("anthropic", "claude-haiku-4-5"),  # last-resort if cost-sensitive
]
```

When Marítaca returns rejected_citations > N, or 5xx error, or fails
the structured-output contract, fall through to Anthropic. Caller is
notified via `RAGAnswer.degraded: bool` or similar metadata.

## Files

- `study/llm-comparison-2026-05-15.json` — raw run output (3×2 = 6 runs)
- `rag_leis/run_llm_comparison.py` — the runner; re-runnable when needed
- `rag_leis/maritaca.py` — adapter implementation
- `study/phase-4-0-llm-comparison-plan.md` — original plan

## Verdict

Sabiá-3.1 is **production-grade** for this project under the cite-and-verify
contract. The 2.2% rejected_citation_rate is **the verify layer doing
its job**, not a failure surface. Combined with the residency win (D9) +
cost + latency + faithfulness lead, the swap is the right call.

Anthropic stays as a first-class option, canonical judge, and fallback in
Phase 7.4. This is a **stack composition** decision, not a "we love
provider X" decision.
