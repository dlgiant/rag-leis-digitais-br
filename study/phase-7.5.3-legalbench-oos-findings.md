# Phase 7.5.3 findings — legalbench.br OOS expansion exposes 6× refusal gap

**Date:** 2026-05-17
**Eval set:** `eval/legalbench_br_oos.yaml` (49 rows, sampled from
`celsowm/legalbench.br` `multiple_choice_qa` task, 7 non-corpus legal areas)
**Run config:** Voyage-3-large + Sabiá-3.1 + `title+label+nav+caput+text`
+ top_k=10
**Run log:** `eval/runs/phase-7.5.3-legalbench-oos.json`
**Cost:** ~$1.50 Sabiá (not measured in this run; serialize_record patched
post-hoc for next runs).

## Headline finding

The pipeline correctly refuses **only 12.2% (6/49)** of OOS queries from
legitimately-OOS legal domains (Processual Civil, Processual Penal,
Tributário, Trabalhista, Empresarial, Ambiental, Internacional).

Comparison across eval surfaces:

| Eval surface | n | OOS refusal accuracy | Selection method |
|---|---|---|---|
| `eval/answer_queries.yaml` | 15 OOS | **93.8%** | Curated by us as "obviously" OOS |
| `eval/oab_concurso_pilot.yaml` | 7 OOS-A | **43%** | External OAB content, manual filter |
| `eval/legalbench_br_oos.yaml` | 49 OOS-A | **12.2%** | External benchmark, semi-random sample |

**The internal eval set overstated production OOS behavior by 6.7× vs the
external benchmark.** This is a definitive measurement of selection bias
in self-curated eval sets.

## Failure mode characterization

Inspection of 3 sample not-refused records reveals a consistent pattern:

### Pattern A — "Verbal refusal without flagged refusal"

**Example (`celsowm/legalbench.br/182`, Direito Processual Civil):**

> Query: "Durante um processo, a parte ré levanta a questão de
> incompetência territorial do juízo. Qual é o momento adequado para
> arguir essa incompetência?"
>
> Pipeline answer (paraphrased): "O momento adequado... está previsto
> no Código de Processo Civil, **norma que não está presente nas fontes
> fornecidas**. As fontes constitucionais... não disciplinam o momento
> processual... Portanto, **não há informação suficiente nas fontes
> fornecidas** para responder à pergunta..."
>
> `refused = False`, `citations = []`

The model EXPLICITLY says "não há informação suficiente nas fontes
fornecidas" — but the `refused` flag is False.

**Root cause:** `rag_leis.rag._is_self_refusal()` only matches the
canonical phrase as a **PREFIX** of the answer (rag.py:142-146). Here
the canonical phrase appears mid-answer; detection misses it.

```python
def _is_self_refusal(answer_text: str) -> bool:
    head = answer_text.strip().lower()[:120]
    return any(head.startswith(p) for p in _SELF_REFUSAL_PREFIXES)
```

The model has been complying with the SYSTEM_PROMPT's refusal mandate
substantively but in the wrong textual position. Pipeline classifies it
as a regular answer.

### Pattern B — "Citation hallucination toward adjacent corpus"

**Example (`celsowm/legalbench.br/149`, CPC requisitos petição inicial):**

> Query: "Quais são os requisitos essenciais da petição inicial,
> segundo o CPC?"
>
> Pipeline answer: "Os requisitos essenciais da petição inicial,
> conforme o Código de Processo Civil (CPC), estão previstos nos
> artigos 282 a 285, conforme indicado no **Art. 8 da Lei nº
> 9.507/1997 (Habeas Data)**. Embora o..."
>
> `citations = ["urn:lex:br:federal:lei:1997-11-12;9507~art8", ...]`

The model invented a connection between CPC (not in corpus) and Lei 9.507
(in corpus) — citing the habeas data procedural law as if it informed
CPC. Pure hallucination using corpus-adjacent material.

`hierarchy_warning` didn't catch this because the cite IS a real corpus
URN; the warning fires on lower-rank citations when higher-rank were
available, not on subject-irrelevant citations.

### Pattern C — "Answer with no citations"

Many of the not-refused records show `citations = []` but `answer` text
that attempts to address the question with general legal knowledge. This
is the model exploiting that the cite-and-verify check passes vacuously
when `citations = []` (nothing to verify).

## Implications

**For SYSTEM_PROMPT iteration:** the refusal mandate is clear (subtypes
a-d in Phase 5.1) but the model is producing structurally non-compliant
outputs. Two fixes worth testing:

1. Tighten `_is_self_refusal` to scan the FULL answer (not just first 120
   chars) for the canonical phrase. Catches Pattern A.
2. Require `len(citations) > 0` AND `not is_self_refusal()` for a valid
   non-refusal answer. Answers with empty citations should be treated as
   refusals (or refused-but-tried). Catches Pattern C.
3. SYSTEM_PROMPT instruction: "if you would say 'não está presente nas
   fontes' anywhere in the answer, START the answer with that phrase
   followed by `Não há informação suficiente nas fontes fornecidas.`"
   Reinforces the prefix convention the detector relies on.

**For Phase 7.5 plan execution:** sub-phase 7.5.3 originally targeted "CI
tightens from ±15pp to ±5pp at n=60". CI did tighten dramatically — the
9-row pilot wouldn't have surfaced this 12% refusal rate confidently. But
the bigger finding is that **the metric we tightened reveals a 6× worse
reality than the internal eval claimed.** Sub-phases 7.5.4-7.5.6 will
continue eval expansion; the FIX for the refusal-detection bug is
out-of-scope for Phase 7.5 but should be a top Phase 8 (or pre-Phase 8)
priority.

**For the audit doc (`study/rag-eval-metrics-audit.md`):** §3 row 19
"OOS refusal accuracy" was marked ✅ Covered. It still is — the metric
IS implemented — but the **measurement quality on internal eval was
selection-biased**. Update the row note to surface this caveat.

## What to NOT do (explicit non-goals from this finding)

- ❌ Don't iterate SYSTEM_PROMPT mid-Phase-7.5 — finish the eval
  expansion first (sub-phases 7.5.4-7.5.6), then iterate prompt against
  the full expanded test surface. Iterating against a partial set risks
  over-fitting to the 49 legalbench.br rows.
- ❌ Don't relax the `refused_correctly` scoring to count Pattern A
  ("verbal refusal") as correct. That would hide the bug; we want the
  metric to surface the gap, not paper over it.
- ❌ Don't add Pattern B detection inside this PR — proper fix requires
  measuring against in-scope rows too (to ensure we don't false-positive
  legitimate corpus citations).

## Cost (from this run, partial — accounting fix landed mid-Phase 7.5.2)

- Estimated: 49 Sabiá calls × ~$0.03 = ~$1.50 (matches plan estimate)
- Actual: not measured by this specific run (`run_concurso_eval.py`
  serialize_record didn't propagate the Phase 7.5.2 cost fields).
  Patched post-hoc; next runs will report.

## Cross-references

- `study/concurso-pilot-findings.md` — the 16-row pilot that motivated
  this expansion
- `study/query-expansion-plan.md` §4 sub-phase A — this work's design
- `study/phase-7.5-eval-expansion-plan.md` — parent plan
- `study/rag-eval-metrics-audit.md` §3 row 19 — needs caveat update
  (selection bias on internal OOS)
- `BACKLOG.md` § OOS hardening — these findings update the priority
  estimates from 43% to "actually 12% on broad external set"
