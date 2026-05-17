# OAB concurso pilot — first baseline findings

**Date:** 2026-05-17
**Eval set:** `eval/oab_concurso_pilot.yaml` (16 rows: 7 inscope + 7 oos_a + 2 oos_b)
**Run config:** Voyage-3-large + Sabiá-3.1 + `title+label+nav+caput+text` + top_k=10
**Run log:** `eval/runs/concurso-pilot-baseline.json`
**Source:** [`eduagarcia/oab_exams`](https://huggingface.co/datasets/eduagarcia/oab_exams) (2210 OAB MCQ 2010-2018); 19 candidates filtered by digital-law keywords, 7 curated as in-scope.

## Headline numbers

| Metric | Value | Interpretation |
|---|---|---|
| **In-scope answer rate** | **7/7 (100%)** | Pipeline correctly didn't refuse any in-scope query |
| **In-scope any-gold-cited rate** | **5/7 (71%)** | Found at least one correct article in 71% of cases |
| **In-scope coverage mean** | **53.6%** | When gold has multiple articles, model cited ~half on avg |
| **In-scope coverage Jaccard** | **20.7%** | Set similarity between cited and gold |
| **OOS-A refusal rate** | **3/7 (43%)** | ⚠️ Should refuse all tax/labour-procedure/international |
| **OOS-B refusal rate** | **0/2 (0%)** | ⚠️ Both adjacent-without-coverage over-answered |
| **Overall refusal accuracy** | **10/16 (62.5%)** | Significantly below answer-eval baseline (93.8%) |

## What the data tells us

### ✅ In-scope citation quality is OK but not great

5 of 7 in-scope queries got at least one gold URN cited. The 2 misses are
both CDC questions:

- **Row 6 (CDC art.30/31/35 — oferta vincula)**: model answered correctly but
  cited CC/CF articles instead of CDC. Citation gap, not answer gap.
- **Row 7 (CDC art.14/17 — risco da atividade)**: same pattern.

This suggests the retrieval found correct law generally but CDC isn't
strongly anchored. Worth a per-query investigation of which CDC chunks
were in top-K.

### 🚨 OOS refusal is notably worse on concurso questions vs answer-eval set

The existing `eval/answer_queries.yaml` measures 93.8% refusal accuracy
on its 15 OOS rows. This pilot measures **62.5% overall**:

- TAXES queries (3 of 4 not refused): pipeline over-answered IPTU, ação
  rescisória trabalhista, execução trabalhista, extradição.
- INTERNATIONAL: 1 of 2 not refused.

**Hypothesis:** answer-eval OOS rows are curated by us to be "obviously"
out-of-scope (PL não promulgado, doutrina pura). Real concurso questions
are more domain-adjacent — the model finds tangentially relevant chunks
(LGPD overlaps with tax data protection in adjacent ways, labour law has
data protection clauses), passes the cosine fast-path threshold, and
the LLM judges the context "enough" to attempt an answer.

This is a **real production gap** — the answer-eval OOS measurement
was optimistic because we constructed it ourselves.

### 🚨 OOS-B adjacent-without-coverage: 0/2 refusal

Both "adjacent" cases over-answered:

- **2016-19_44** (ECA — corrupção de menores via internet): pipeline
  hallucinated answer using LGPD/MCI context, even though the operative
  norm is ECA art.244-B which isn't in our corpus. Pipeline should have
  recognized "topic touches my corpus but specific norm absent."
- **2017-22_1** (Código de Ética OAB — advogado em mídia digital):
  same pattern, used MCI/CDC context to answer a question whose answer
  is in the OAB Ethics Code (not indexed).

**This is the highest-priority finding.** The pipeline's refusal taxonomy
(OOS subtypes a-e in SYSTEM_PROMPT) explicitly enumerates this case
(subtype "d" — normas não-indexadas adjacentes), but the model isn't
firing it on these queries. SYSTEM_PROMPT iteration (Phase 5.1-style)
seems warranted.

## Concrete next steps

### Immediate (~1 hour each)

1. **Investigate the 4 OOS-A misses** — was the cosine top-1 above
   threshold? If yes, the LLM judged the context applicable when it
   shouldn't have. Iterate the SYSTEM_PROMPT to harden subtype "a"
   detection on tax/labour/international topics.
2. **Investigate the 2 OOS-B misses** — same diagnostic. Subtype "d"
   detection clearly underperforming on real adjacent questions.
3. **Investigate the 2 CDC in-scope misses** — were CDC art.14/17/30/31/35
   in top-K? If yes, model picked wrong articles to cite. If no,
   retrieval gap.

### Short-term (~3-5 hours)

4. **Expand pilot to ~30 in-scope + ~25 OOS**:
   - Re-run extraction with more permissive filters
   - Specifically target CDC + Lei do Software questions (currently
     under-represented)
   - Add `OOS-C` category for "intentionally tricky" (CRIMINAL questions
     about non-digital crimes — pipeline should refuse but they're
     deceptively close to crimes cibernéticos)
5. **Track concurso eval as separate metric** alongside answer-eval:
   the divergence is the signal.

### Mid-term (~1-2 weeks)

6. **System prompt iteration cycle** (Phase 5.1b pattern): use the
   pilot misses as adversarial training set, iterate SYSTEM_PROMPT,
   re-run, measure improvement. Cross-validate against Anthropic to
   ensure prompt changes don't regress on Anthropic provider.
7. **Acquire post-2018 OAB exams** (LGPD-era): the eduagarcia dataset
   stops at 2018-25, just before LGPD was tested. Newer exams (2019+)
   should have LGPD-specific questions. Source: OAB official PDFs.

## Methodology notes (for the audit doc cross-reference)

- This pilot **does not replace** the existing `eval/answer_queries.yaml`
  — it's a separate eval against external curated content (real OAB
  questions, real answer keys).
- Coverage of OOS subtypes is intentionally narrower than the answer-eval
  taxonomy (a-e): pilot covers subtype "a" (other domain) and "b"
  (adjacent without coverage). Subtypes c (PL não promulgado), d
  (estadual/municipal), e (doutrina) require domain-specific queries
  not present in OAB exams.
- Cost per pilot run: ~$0.30-0.50 Sabiá + ~$0.001 Voyage queries. Cheap
  enough to re-run on prompt iterations.
- The eduagarcia dataset is HF-hosted under unspecified license; our
  eval yaml stores only `source_id` references + operator-curated query
  text (close to the original but reformulated when needed) + gold_urns
  manually mapped to our corpus. No verbatim copyright issue.

## Cross-references

- `study/rag-eval-metrics-audit.md` §4 — concurso pilot is the "external
  benchmark anchor" alternative to LegalBench (US common-law focus)
- `eval/oab_concurso_pilot.yaml` — pilot eval set
- `rag_leis/run_concurso_eval.py` — runner
- `scripts/extract_oab_pilot.py` — extraction tool (re-runnable)
- `eval/runs/concurso-pilot-baseline.json` — full per-row results
