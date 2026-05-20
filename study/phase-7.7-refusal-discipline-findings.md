# Phase 7.7 findings — refusal-discipline iteration (2 of 3 fixes shipped)

**Date:** 2026-05-19 (same-day execution after Phase 7.6 close)
**Plan:** `~/.claude/plans/lucky-questing-nova.md` D1-D5 (Phase 7.6 plan + Phase 7.7 inline gates)
**Eval set:** `eval/legalbench_br_oos.yaml` (49 rows; baseline post-7.6.2 = 0.184)
**Pre-locked gate:** combined lift ≥ +0.30pp on `oos_a_refusal_rate` (target ≥0.48)
**Result:** **+0.20pp average** (0.388-0.429 across two runs) — **gate NOT met**
**Disposition:** Fix #1 + Fix #2 ship; Fix #3 (SYSTEM_PROMPT iteration) reverted as net-negative

## Headline outcomes

| Fix | Description | Effect on oos_a_refusal_rate | Disposition |
|---|---|---|---|
| **#1** | `_is_self_refusal()` full-text scan (not just first 120 chars) | +0.10pp (0.184 → 0.286) | ✅ shipped |
| **#2** | `citations=[]` on non-refused → implicit refusal | +0.14pp (0.286 → 0.429) | ✅ shipped |
| **#3** | SYSTEM_PROMPT category (e) + dispositivo-specificity rule | -0.06pp (0.429 → 0.367) | ❌ REVERTED |
| **Final** | Fix #1 + #2, Fix #3 reverted | **+0.20pp** (0.184 → ~0.41 avg) | gate NOT met |

`false_refusal_rate` stayed at 0.000 on internal eval throughout — no in-scope regressions from any fix.

## Per-fix detail

### Fix #1 — full-text scan in `_is_self_refusal()`

**Problem (Pattern A from phase-7.5.3-legalbench-oos-findings.md):**
The original detector checked only the first 120 chars of the answer
for canonical refusal phrases ("não há informação suficiente", "as
fontes fornecidas não", etc.). The model often explained what it tried
in a 200-char preamble, THEN concluded with the canonical phrase.
Detector silent; row counted as a non-refusal answer despite being a
substantive refusal.

**Fix:** Widened to substring search across full answer text. The
existing prefixes include disambiguating qualifiers like "suficiente"
/ "fornecidas" / "possível encontrar" that make false-positive risk
very low — the guard test
`test_real_answer_mentioning_no_info_inline_is_NOT_refusal` still
passes (it uses "Não há informação" *without* the "suficiente"
qualifier).

**Code change:** ~5 lines in `rag_leis/rag.py` (`_SELF_REFUSAL_PREFIXES`
renamed to `_SELF_REFUSAL_PHRASES`, prefix-startswith → substring-in).

**Tests:** 8 → 12 in `test_rag_self_refusal.py`. New tests cover the
specific Pattern A failure case from legalbench/182, plus a
long-preamble edge case (>500 chars before the refusal phrase).

**Impact:** +5 catches (7 → 12 llm-self-refusals on legalbench OOS).

### Fix #2 — empty citations as implicit refusal

**Problem (Pattern C from phase-7.5.3 findings):**
The model produces an answer using "general legal knowledge" with
`citations=[]` (zero URNs). The cite-and-verify gate passes vacuously
(nothing to verify), so the row counted as a non-refusal answer
despite being unverifiable.

**Fix:** In `RAGPipeline.answer()`, after the `_is_self_refusal()`
check, treat `not self_refused AND not verified` as an implicit
refusal. Sets `refused=True` with
`refusal_reason="empty-citations-implicit-refusal"` (distinct from
"llm-self-refusal" for audit clarity).

**Code change:** ~15 lines in `rag_leis/rag.py` (insertion after the
self-refusal check + reason-string branch).

**Risk:** Could false-refuse a legitimate in-scope query whose answer
genuinely needs no citation. **Verification:** `false_refusal_rate`
stayed at 0.000 on the internal answer-eval (29 rows, 14 in-scope) —
no in-scope query in our existing eval set produces a non-citing
answer.

**Impact:** +6-8 new refusals (variable run-to-run).

### Fix #3 — SYSTEM_PROMPT category (e) + dispositivo-specificity rule (REVERTED)

**Problem (Pattern B from phase-7.5.3 findings):**
The model produces answers with citations to *real* URNs from the
corpus, but those URNs are semantically irrelevant to the query.
Example: query about CPC petição inicial requirements; model cites
Lei 9.507/97 Habeas Data art.8 (a different procedural law that
happens to be indexed). Fix #2 doesn't catch this — the answer DOES
have citations, just wrong ones.

**Fix attempted:** Added a new refusal category (e) explicitly
naming "wrong law as substitute for the named law" failure mode, plus
a positive heuristic ("REGRA DE ESPECIFICIDADE DO DISPOSITIVO") asking
the model to verify dispositivo-relevance before citing.

**Result: NET NEGATIVE on the gate metric.** Total refusals went 21 →
18. The breakdown shifted in an unexpected way:

- llm-self-refusals: 10 → 13 (+3, good — model now explicitly refuses
  some rows it previously answered)
- empty-citations refusals: 8 → 3 (-5, bad — model now produces SOME
  citations on rows that previously had none, removing them from the
  Fix #2 catch but not making them correct)

Net: −2 refusals on the OOS surface, plus −1 attributable to
LLM-stochastic noise = 21 → 18 (−3 observed).

The intervention made the model **more confident in some wrong
answers** without making it refuse the rest. The dispositivo-specificity
rule was supposed to make the model refuse rather than analogize; in
practice it just gave the model new vocabulary for producing the same
type of answer with more citations.

**Disposition:** Reverted. SYSTEM_PROMPT returned to the (a-d)
taxonomy from Phase 5.1.

**Lesson:** prompt iteration in a direction that the LLM finds easy
to satisfy textually but hard to satisfy substantively often produces
worse outcomes than the unchanged prompt. The mechanism-side fixes
(#1 and #2) attack the gap structurally; the prompt-side fix tried
to change the model's *behavior* without structural backing, and lost.

## Pre-locked gate verdict

D2 (Phase 7.7 gate): `oos_a_refusal_rate` must reach ≥0.48 (≥+0.30pp
from the 0.184 baseline). **Result: 0.388-0.429 (avg ~0.41), gate
NOT met.**

Per the discipline pattern (same shape as Phase 7.6.2's negative
gate): the partial improvement (+0.20pp average, ~3.4× the pre-7.5
baseline of 0.122) is meaningful and ships, but does not justify
declaring "refusal discipline solved." Phase 8 hosting cannot ship
under the original SLO assumption that refusal accuracy is at
production grade.

**Cumulative improvement from original Phase 7.5 baseline:**
0.122 → 0.41 (avg) = **+0.29pp absolute, 3.4× improvement**.

The honest framing: refusal discipline is materially better than
where we started, but the 49-row external benchmark still has ~58%
of OOS queries producing non-refused answers. Further work is
needed before Phase 8 hosting.

## What's left in the OOS gap

The ~28-30 rows still not refused after Phase 7.7 fall into two
categories that the implemented fixes don't reach:

1. **Sophisticated Pattern B**: model cites real URNs from the
   adjacent corpus and produces a coherent-sounding answer. Fix #3
   tried and failed to address this with prompts alone.
2. **Borderline OOS topics** where the corpus genuinely has tangential
   coverage (e.g., a CPC question where MCI has procedural language
   that could be arguably applicable).

Neither yields to simple SYSTEM_PROMPT changes. Candidates for
future phases:

- **Per-citation relevance gating** (~3-5 days): after cite-and-verify,
  pass each cited URN + the query through a small LLM judge that asks
  "does this citation address the specific question, or just the
  topic?" Reject the answer if zero citations pass. Significant
  engineering surface (new gate, new costs, new eval) — would need
  its own pre-locked gate.
- **Per-document scope tagging with finer grain** (= BACKLOG #1, the
  full concept KG demoted in Phase 7.6.2): with D7 lawyer-reviewed
  ontology, the scope-check from 7.6.2 would have richer vocabulary
  to fire on. Dependent on D7 engagement (Phase 9 scope).
- **Fine-tuning the generator** on refusal examples (large surface,
  cost, deferred to Phase 9+).

These move to BACKLOG as remaining Phase 8 entry candidates.

## Implementation summary

**Files modified (final state — Fix #3 reverted):**
- `rag_leis/rag.py`:
  - `_SELF_REFUSAL_PREFIXES` → `_SELF_REFUSAL_PHRASES` (renamed)
  - `_is_self_refusal()` widened from 120-char prefix to full-text substring scan
  - `RAGPipeline.answer()`: empty-citations implicit refusal branch (~15 lines)
  - `refusal_reason` field distinguishes "llm-self-refusal" from "empty-citations-implicit-refusal" for audit
- `tests/test_rag_self_refusal.py`: 8 → 12 tests (Pattern A coverage)
- SYSTEM_PROMPT: unchanged (Fix #3 reverted)

**Suite: 390 → 390 passing** (Fix #1+#2 tests landed before Fix #3, suite count includes them).

**API spend Phase 7.7:** ~$0.60 (4 legalbench OOS eval runs + 2 in-scope regression checks).

**Time:** ~2h focused.

## Phase 7.7 close decision

- ✅ **Fix #1 ships** — clean improvement, ~5 lines + 4 tests
- ✅ **Fix #2 ships** — meaningful improvement with no in-scope regression
- ❌ **Fix #3 reverted** — prompt iteration alone was insufficient; documented as tried+failed for future-me's reference
- **Gate not met** — Phase 7.7 does NOT close as "refusal discipline solved"; the gap remains a Phase 8 entry blocker that requires structural (not prompt-only) intervention

This is the **same shape as Phase 7.6.2's outcome**: pre-locked gates produce honest decisions even when the answer is "got partway but not enough." The mechanism worked; the result was less than hoped; the discipline preserved scope.

## Cross-references

- [`phase-7.5.3-legalbench-oos-findings.md`](phase-7.5.3-legalbench-oos-findings.md) §3 — original 3-fix documentation that this phase implemented
- [`phase-7.6-findings.md`](phase-7.6-findings.md) — preceding phase, established the pre-locked-gate pattern this phase reused
- [`phase-7.6.2-scope-tags-findings.md`](phase-7.6.2-scope-tags-findings.md) — produced the 0.184 baseline this phase started from
- [`BACKLOG.md`](../BACKLOG.md) — Phase 8 entry candidates (per-citation relevance gate, fine-tuning) get added
- `eval/runs/phase-7.7-fix1-fulltext-scan.json` — Fix #1 measurement
- `eval/runs/phase-7.7-fix2-combined.json` — Fix #2 measurement (0.429 run)
- `eval/runs/phase-7.7-fix3-all-combined.json` — Fix #3 measurement showing regression
- `eval/runs/phase-7.7-final-fix12.json` — final ship state (0.388 run)
