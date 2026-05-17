# Phase 7.5.4 findings — 97.5% external-anchored citation precision

**Date:** 2026-05-17
**Eval set:** `eval/legalbench_br_rule_recall.yaml` (40 rows, 20 CF + 20 CP)
**Source:** `celsowm/legalbench.br` `closed_book_qa` task, CC BY-SA 4.0
**Run log:** `eval/runs/phase-7.5.4-legalbench-rule-recall.json`
**Cost:** $0.067 (44 LLM calls, 107k input + 7k output tokens)

## Headline result

**rule_recall_hit_rate = 97.5% (39/40)** with answered_rate = 100%.

Given the verbatim text of an article, the pipeline (a) retrieved the
correct chunk and (b) cited the correct URN in 39 of 40 cases. The one
miss was an adjacent-article confusion (CP art.234-A cited as CP
art.226 — both "aumento de pena nos crimes contra dignidade sexual").

This is an **externally anchored citation precision metric** — the gold
URNs came from a third-party benchmark we didn't author. Adds the first
non-self-curated citation-quality signal to the project's measurement
surface.

## The 1 miss (analytical)

**Query:** "Qual é o artigo do Código Penal Brasileiro... com o texto:
'Nos crimes previstos neste Título a pena é aumentada: (Incluído pela
Lei nº 12.015, de 2009)... I (VETADO)' ?"

**Gold:** `urn:lex:br:federal:decreto.lei:1940-12-07;2848~art234-a`

**Pipeline cited:** `~art226`, `~art226;inc4;ali-a`, `~art226;inc4;ali-b`

**Why it missed:**
- art.226 is the OLDER "aumento de pena nos crimes contra dignidade
  sexual" article (pre-existing in CP).
- art.234-A was added by Lei 12.015/2009 with the same shape (aumento
  de pena, same Título).
- The verbatim text has "(VETADO)" inside it — a sparse, ambiguous
  signal. The dense embedder anchored on the broader semantic
  ("aumento de pena nos crimes deste Título") and found art.226 first.

Reasonable failure — adjacent article in the same chapter — but a real
miss against the strict-URN metric.

## Contrast with 7.5.3 (OOS refusal collapse)

| Capability | Eval | Score |
|---|---|---|
| In-corpus citation precision (given verbatim text) | rule_recall 7.5.4 | **97.5%** |
| OOS refusal (queries from non-corpus domains) | OOS-A 7.5.3 | **12.2%** |

These are different and complementary capabilities. The pattern that
emerges:

**The pipeline is excellent at finding what's in-corpus + citing it
correctly.** When the right article exists, it almost always lands the
right URN.

**The pipeline is bad at recognizing what's NOT in-corpus + refusing.**
When the right article doesn't exist, the model tries to be helpful
with adjacent material instead of refusing cleanly.

This is coherent diagnosis: it's not a "retrieval fails" problem nor a
"citation accuracy" problem. It's a **refusal-discipline** problem
specifically. The pipeline's response to absent-coverage is
"approximation" instead of "refusal."

## Implications for the audit doc

`study/rag-eval-metrics-audit.md` §3 row 13 ("Citation precision strict")
is marked ✅ Covered with project-internal metric. Add a row for external
rule_recall:

| 13b | C. Attribution | Rule recall (external) | Lege benchmark — Guha 2023 conceptual | ✅ NEW | `eval/legalbench_br_rule_recall.yaml` 97.5% |

Update §B comparison matrix row "Citation accuracy (strict)" — we're
now externally validated against benchmark gold, not just self-curated.

## What this means for portfolio narrative

External anchor metric: **the pipeline gets 39/40 article identifications
correct on a benchmark we didn't construct**. That's the strongest
quality claim the project can make: "this is not eval-set overfitting;
benchmark data confirms the pipeline finds + cites correctly."

Combined with the 7.5.3 finding (12% OOS refusal), the honest story:
- ✅ Retrieval + citation precision: excellent (97.5% on external)
- 🚨 Refusal discipline: needs work (12% on external)
- The two are diagnosable as the same root: model defaults to
  "help, don't refuse" — fine when correct article exists, bad when
  it doesn't.

## Cost reporting (first run with Phase 7.5.2 instrumentation fully wired)

  Total run cost:   $0.0672
  Cost per query:   $0.001679  (40 queries)
  LLM calls:        44 (40 initial + 4 prose-check retries)
  Tokens:           107,011 input / 6,831 output

  Sabiá-3.1 input rate: $0.50/1M; output: $2.0/1M
  Calculated: 107k * 0.5 / 1M + 7k * 2 / 1M = $0.0535 + $0.0136 = $0.0671 ✓

The retry rate (4/40 = 10%) is meaningful — prose-citation check fired
on 10% of rule_recall rows, doubling LLM cost for those rows.
Investigation candidate: which rows triggered retry?

## Cross-references

- `study/phase-7.5.3-legalbench-oos-findings.md` — the contrast case
  (12% refusal)
- `study/query-expansion-plan.md` §4 sub-phase B — this work's design
- `study/rag-eval-metrics-audit.md` §3 row 13 — needs the new external
  rule_recall entry added
- `eval/legalbench_br_rule_recall.yaml` — eval set (40 rows)
- `scripts/extract_legalbench_rule_recall.py` — reusable extractor
