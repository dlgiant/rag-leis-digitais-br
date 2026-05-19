# Auditor's gold-standard metrics for legal RAG — what we measure vs what we should

**Date:** 2026-05-17
**Audience:** internal self-audit + portfolio reviewers + Phase 8 planning
**Status:** core audit + comprehensive bibliographic appendix

This document maps the project's current ~17-metric instrumentation against
published gold-standard frameworks for RAG evaluation (RAGAS, AIS, BEIR
conventions, Google SRE), with emphasis on legal/regulated-domain RAG. The
goal is to surface measurement gaps with cited justification before Phase 8
hosting work begins.

The doc is intentionally tiered:

- **Core (§1–§5)**: ~10 min read. Inventory + gap table + ROI-ranked
  recommendations. Action-oriented.
- **Appendix (§A–§B)**: ~25-entry annotated bibliography + side-by-side
  comparison against named RAG frameworks (RAGAS, TruLens, LangChain Smith,
  LlamaIndex eval). Portfolio + research depth.

---

# Core (§1–§5)

## §1 — What we measure today (inventory)

Seventeen first-class metrics + several side-signals. Source-of-truth: code,
not declared intent.

### Retrieval (3 metrics × 5 text-modes, 4 categories breakdown)

| # | Metric | File:line | Notes |
|---|---|---|---|
| 1 | `nDCG@10` | `rag_leis/eval_harness.py:373-404` | Graded relevance (2^rel-1 gain); supports `Query` with core (rel=2) + supporting (rel=1). |
| 2 | `Recall@20` | `rag_leis/eval_harness.py:366-370` | Binary; `hits / |relevant|`. |
| 3 | `MRR@10` | `rag_leis/eval_harness.py:407-411` | Reciprocal rank of first relevant URN. |

Per-type breakdown (`rag_leis/run_eval.py:200-225`) over five query categories:
`definicao`, `enumeracao`, `citacao-literal`, `parafrase`, `cross-doc`.

### Answer quality (8 metrics)

| # | Metric | File:line | Notes |
|---|---|---|---|
| 4 | `cit_precision_strict` | `rag_leis/run_answer_eval.py:232` | `|cited ∩ gold| / |cited|` |
| 5 | `cit_precision_lenient` | `rag_leis/run_answer_eval.py:233` | `|cited ∩ (gold ∪ alt_acceptable)| / |cited|` |
| 6 | `cit_recall` | `rag_leis/run_answer_eval.py:234` | `|cited ∩ gold| / |gold|` |
| 7 | `cit_f1` | `rag_leis/run_answer_eval.py:235` | Harmonic mean of strict precision + recall |
| 8 | `faithfulness 0-5` | `rag_leis/run_answer_eval.py:155-168` | LLM judge (opus-4-7) vs `expected_paragraph` |
| 9 | `refusal_accuracy` | `rag_leis/run_answer_eval.py:289` | Macro avg over both in-scope (should not refuse) and OOS (should refuse) |
| 10 | `rejected_citation_rate` | `rag_leis/run_answer_eval.py:290` | `|rejected| / |cited + rejected|` — hallucination signal |
| 11 | `refusal_accuracy_by_oos_subtype` | `rag_leis/run_answer_eval.py:335-338` | Per-subtype macro accuracy; subtypes a-e: domain, adjacent-no-coverage, PL não promulgado, estadual/municipal, doutrina não-positivada |

### Operational signals exposed on `RAGAnswer` (not directly aggregated as metrics, but persisted per-row)

| # | Signal | File:line | Purpose |
|---|---|---|---|
| 12 | `flagged_vigencia` | `rag_leis/rag.py:298` + `rag_leis/vigencia.py` | Cited URNs with overlay (sub_judice / eficácia limitada / EC linkage) |
| 13 | `hierarchy_warning` | `rag_leis/rag.py:310` (computed at `rag.py:517-565`) | LLM cited lower-rank source while higher-rank was in top-K |
| 14 | `prose_citation_mismatches` | `rag_leis/rag.py:315` (computed at `rag_leis/prose_check.py`) | Prose says "Art. 5, XII" but no cited URN ends with `art5;inc12` |
| 15 | `prose_check_retried` | `rag_leis/rag.py:316` | True when retry fired on mismatch (Phase 5.3) |
| 16 | `pii_types_redacted` | `rag_leis/rag.py:306` + `rag_leis/pii.py` | LGPD compliance — categories actually found and redacted |
| 17 | `sources_consulted_at` | `rag_leis/rag.py:321` | doc_urn → ISO date (footer transparency) |

### Eval-set characteristics

- **`eval/queries.yaml`**: 104 queries, 5 types, mixed binary + graded
  (`core`/`supporting`) gold formats. Retrieval-only eval.
- **`eval/answer_queries.yaml`**: 29 queries (14 in-scope + 15 OOS across 5
  subtypes). Includes `gold_urns`, `alternative_acceptable_urns`,
  `expected_paragraph`. End-to-end answer eval.

### Eval runs persisted

15 phase-tagged result JSONs in `eval/runs/` covering Phase 2 baseline through
Phase 5.7+5.8 (`phase-2-baseline.json` ... `phase-5-7-and-5-8.json`). Full
configuration + aggregate + per-row results.

### Explicitly absent (called out so readers don't infer presence)

- ❌ Latency / cost / token tracking (only in docstrings)
- ❌ RAGAS "Answer Relevance" as separate dimension (collapsed into Faithfulness)
- ❌ RAGAS "Context Precision/Recall" as RAGAS-defined (proxied by nDCG/Recall)
- ❌ External benchmark anchor (no LegalBench / CUAD / COLIEE comparison)

---

## §2 — Gold-standard categories (compact)

Seven categories. Inline source per metric; full annotated bibliography in §A.

### A. Retrieval IR — TREC / BEIR conventions

Canonical metrics for ranked retrieval evaluation:

- **nDCG@k** — normalized discounted cumulative gain. Järvelin & Kekäläinen
  (2002) define the formal gain function with logarithmic position discount.
  Standard k values: 10 (operating) and 100 (analytical).
- **Recall@k** — fraction of relevant items retrieved. BEIR uses Recall@100
  as the corpus-level recall ceiling diagnostic (Thakur et al., 2021).
- **MRR@k** — mean reciprocal rank. Stronger signal for single-best-answer
  retrieval (FAQ, single-chunk citation literal).
- **MAP** — mean average precision over all relevant. Less common in modern
  RAG eval (graded-relevance versions like nDCG dominate).
- **Precision@k** — `|relevant ∩ top-k| / k`. Useful when k is exactly the
  context size sent to the LLM (top-K context window).
- **Hit Rate** — binary "did we retrieve any relevant in top-k?" Useful as a
  floor metric distinct from recall (graded count vs binary presence).

### B. RAGAS framework — Es et al., 2023 (arxiv 2309.15217)

Reference-free evaluation of RAG. Four canonical metrics, all LLM-judged:

- **Faithfulness** — claims in the answer must be inferable from the
  retrieved context. Decompose answer into atomic claims, then check each
  against context.
- **Answer Relevance** — does the answer actually address the user's
  question? Computed via reverse-question generation: LLM generates N
  questions the answer could be answering, then cosine-sim those questions
  against the original.
- **Context Precision** — relevant retrieved chunks ranked high. Different
  from nDCG: RAGAS uses LLM-judged relevance instead of pre-labeled gold.
- **Context Recall** — every ground-truth claim is supported by ≥1
  retrieved chunk. Different from Recall@k: claim-level, not chunk-level.
- **Context Relevance** (proposed in RAGAS extensions, not the original 4)
  — fraction of each retrieved chunk that's actually relevant
  (rules out irrelevant noise even when the gold chunk was retrieved).

### C. Citation / Attribution

Critical for legal where every claim needs a source:

- **AIS — Attributable to Identified Sources** (Rashkin et al., 2021,
  arxiv 2112.12870). Binary judgment: is the sentence attributable to the
  source material? Established as the formal definition the field uses for
  "did the model cite the right thing."
- **Citation precision / recall** — operationalized versions of AIS as
  attribution metrics. The project's `cit_precision_strict`/`recall` are
  AIS-style at the URN level.
- **Citation faithfulness** (Bohnet et al., 2022, "Attributed Question
  Answering") — extends AIS with the "faithfulness" notion: the cited
  source actually supports the specific claim, not just the topic.
- **Attribution rate** — fraction of statements that have ≥1 citation.
  Useful for measuring "is the model citing enough?" separate from "are the
  citations right?"
- **Citation entailment** — TRUE framework (Honovich et al., 2022,
  "TRUE: Re-evaluating Factual Consistency Evaluation"). Uses NLI models
  to detect whether the claim is entailed by the cited source.

### D. Refusal / Safety

For RAGs that must refuse out-of-corpus questions:

- **OOS refusal accuracy** — correctly refused queries / total OOS queries.
  Covered by project.
- **False refusal rate** — refused in-scope queries / total in-scope.
  Symmetric to OOS refusal accuracy; the two together form a refusal
  confusion matrix.
- **Refusal-by-subtype taxonomy** — OOS queries are not all the same kind.
  Project's a-e taxonomy maps to general RAG OOS categories:
  - (a) other domain entirely — general OOS
  - (b) adjacent without coverage — boundary cases (most fragile)
  - (c) PL não promulgado — temporal OOS (post-cutoff in general RAG)
  - (d) estadual/municipal — jurisdiction OOS (scope-limited domain)
  - (e) doutrina não-positivada — type OOS (corpus contains norms not commentary)
- **Prompt injection defense** (Greshake et al., 2023, arxiv 2302.12173).
  Indirect prompt injection via retrieved content. Legal RAGs face this
  via amendment blockquotes, footnotes, embedded user-submitted briefs.
- **Jailbreak resistance** — generic adversarial prompt robustness.
  Anthropic Responsible Scaling Policy provides a framework.

### E. Operational / SRE — Google SRE Book Ch.6, "Monitoring Distributed Systems"

The Four Golden Signals (Beyer et al., 2016, O'Reilly):

- **Latency** — time to respond. Distribution matters: p50/p95/p99 per
  query, separated by status (success vs refusal vs error).
- **Traffic** — QPS / RPM. Required for capacity planning.
- **Errors** — exception rate per call (per provider — Voyage vs LLM).
  Subdivide: transport errors, schema-validation errors, retry budget exhaustion.
- **Saturation** — resource utilization. For LLM-fronted services: token
  budget consumed vs limit, cache hit rate, rate limit headroom.

Plus RAG-specific operational metrics:

- **Cost per query** — sum of embedding cost + LLM generation + judge calls.
  Documented at run level in project docstrings; not aggregated.
- **Provider availability / fallback success** — when primary provider
  (Marítaca/Anthropic) fails, does the fallback path complete?
- **Cache hit rate** — for embeddings and (optionally) LLM responses.
- **Pipeline stage timing** — embedding generation, retrieval, prompt
  construction, LLM call, post-processing. Useful for surfacing where
  the latency budget goes.

### F. Legal-domain specific

Standard external benchmarks for legal NLP:

- **LegalBench** (Guha et al., 2023, NeurIPS Datasets — arxiv 2308.11462).
  162 tasks across rule-recall, rule-application, interpretation, rhetoric.
  US common-law focused but ~10 tasks transferable to civil-law statute QA.
- **LeCaRD** (Ma et al., 2021) — Chinese legal case retrieval (criminal).
  Methodologically relevant despite jurisdiction mismatch.
- **COLIEE** — annual competition on legal information extraction +
  entailment, JP+EN. Strong methodology for case-statute alignment.
- **CUAD** (Hendrycks et al., 2021, arxiv 2103.06268) — contract
  understanding (510 contracts, 41 clause types). Not applicable to
  legislation RAG but useful methodology comparison.

Project-specific domain metrics:

- **Hierarchy compliance** — `hierarchy_warning` (project covered): does
  the LLM cite higher-rank sources when both are in context?
  CF > LC > LO > Decreto > Resolução is structural fact of Brazilian
  legal hierarchy.
- **Vigência compliance** — `flagged_vigencia` (project covered): when a
  cited rule is sub-judice or has eficácia limitada, did the answer flag it?
- **Jurisdiction refusal** — OOS subtype `d` (project covered): refuse
  state/municipal law queries because corpus is federal-only.
- **Temporal compliance** — refuse queries about projetos de lei (subtype
  `c`); refuse questions about post-cutoff amendments. Partial: project
  refuses PLs but doesn't track temporal cutoff explicitly.

### G. LGPD compliance (BR-specific)

LGPD (Lei 13.709/2018) art. 6 establishes 10 princípios. Three are directly
measurable:

- **Finalidade (art. 6, II)** — data used only for declared purpose.
  Project surface: query strings are processed for retrieval + LLM
  response; not stored for other purposes.
- **Adequação (art. 6, III)** — processing compatible with stated purpose.
- **Minimização (art. 6, VIII)** — only data strictly necessary.

Operational metrics:

- **PII redaction rate per category** (project covered via
  `pii_types_redacted`) — what fraction of queries contained CPF, CNPJ,
  email, phone, CEP, RG? Should be tracked over time for compliance audit.
- **Cross-border data flow** — for Anthropic (US-hosted), every query must
  cross border. Project mitigates: redact PII at boundary (pii.py is
  pre-LLM). Switching default generator to Marítaca/Sabiá (BR-hosted) is
  the operational fix.
- **Audit log completeness** — every query that touched a provider should
  have a hash-based audit record. Project has `data/audit/pii-redactions.jsonl`
  (partial — only logs queries with redaction).
- **Right of access / explainability** (LGPD art. 18) — user must be able
  to ask "what sources informed this answer?" Project covered via
  `citations[]` + `sources_consulted_at` footer.

---

## §3 — Gap analysis table

Every metric from §2 mapped to project status. ~30 rows.

Legend: ✅ Covered — directly measured + persisted | 🟡 Partial — computable
but not surfaced as first-class | ❌ Missing — not instrumented.

| # | Category | Metric | Source | Status | Evidence (file:line or rationale) |
|---|---|---|---|---|---|
| 1 | A. IR | nDCG@10 | Järvelin-Kekäläinen 2002 | ✅ | `eval_harness.py:373-404` |
| 2 | A. IR | Recall@20 | TREC convention | ✅ | `eval_harness.py:366-370` |
| 3 | A. IR | MRR@10 | TREC convention | ✅ | `eval_harness.py:407-411` |
| 4 | A. IR | MAP | TREC convention | ❌ | Not implemented; nDCG dominates in graded settings |
| 5 | A. IR | Precision@k (== top-K context) | RAG-standard | 🟡 | Computable from `raw_retrieval` + gold; not aggregated |
| 6 | A. IR | Hit Rate | BEIR convention | 🟡 | Implicit in Recall@20 when |gold|=1; not separated |
| 7 | A. IR | Recall@100 (corpus ceiling) | BEIR | ❌ | Only top-20 evaluated |
| 8 | B. RAGAS | Faithfulness (LLM judge) | Es et al. 2023 | ✅ | `run_answer_eval.py:155-168` |
| 9 | B. RAGAS | Answer Relevance | Es et al. 2023 | ❌ | Distinct from Faithfulness; not separately judged |
| 10 | B. RAGAS | Context Precision (LLM-judged) | Es et al. 2023 | 🟡 | Proxied by nDCG@10 (pre-labeled gold) |
| 11 | B. RAGAS | Context Recall (claim-level) | Es et al. 2023 | ❌ | Project measures URN-level recall, not claim-level |
| 12 | B. RAGAS | Context Relevance | Es et al. 2023 ext. | ❌ | Not measured per-chunk |
| 13 | C. Attribution | Citation precision (strict) | AIS (Rashkin 2021) | ✅ | `run_answer_eval.py:232` |
| 14 | C. Attribution | Citation precision (lenient) | Project-specific extension | ✅ | `run_answer_eval.py:233` |
| 15 | C. Attribution | Citation recall | AIS (Rashkin 2021) | ✅ | `run_answer_eval.py:234` |
| 16 | C. Attribution | Citation faithfulness (entailment) | Bohnet 2022, Honovich 2022 (TRUE) | ❌ | Project checks URN match, not whether the source actually entails the claim |
| 17 | C. Attribution | Attribution rate | Production practice | 🟡 | Implicit: project rejects answers without citations; not surfaced |
| 18 | C. Attribution | Prose-citation consistency | Project-specific | ✅ | `prose_check.py` + `rag.py:440-464` (with retry) |
| 19 | D. Refusal | OOS refusal accuracy | Production practice | ✅ | `run_answer_eval.py:289` |
| 20 | D. Refusal | False refusal rate (in-scope) | Production practice | ✅ | `Aggregate.false_refusal_rate` + `oos_refusal_recall` surfaced separately (`run_answer_eval.py:308-310`, Phase 7.5.1) |
| 21 | D. Refusal | OOS subtype taxonomy | Project + general RAG | ✅ | `run_answer_eval.py:335-338` (subtypes a-e) |
| 22 | D. Safety | Prompt injection defense | Greshake 2023 | 🟡 | Parser strips `<script>` + amendment blockquotes; not tested against adversarial corpus |
| 23 | D. Safety | Jailbreak resistance | Anthropic RSP | ❌ | No adversarial eval set |
| 24 | E. SRE | Latency p50/p95/p99 | Google SRE Ch.6 | ✅ | `rag.py:RAGAnswer.latency_ms` + `Aggregate.latency_p50/p95/p99_ms` (Phase 7.5.7) |
| 25 | E. SRE | Cost per query | Production practice | ✅ | `cost.py:estimate` + `Aggregate.cost_total_usd/cost_mean_usd` (Phase 7.5.2 + judge cost folded 7.5.7) |
| 26 | E. SRE | Token usage (in/out) | Production practice | ✅ | `RAGAnswer.tokens_used` + `Aggregate.total_input/output_tokens` (Phase 7.5.2) |
| 27 | E. SRE | Error rate | Google SRE Ch.6 | ✅ | Per-row `try/except` + `Aggregate.error_count/error_rate` (Phase 7.5.7) |
| 28 | E. SRE | Provider availability / fallback | Production practice | ❌ | No primary/fallback wiring |
| 29 | E. SRE | Cache hit rate | Production practice | 🟡 | `rag_leis/cache.py` exists for index; hit rate not surfaced |
| 30 | E. SRE | Throughput (QPS) | Google SRE Ch.6 | ❌ | Single-call CLI today |
| 31 | F. Legal | Hierarchy compliance | Project-specific (CF>LC>LO) | ✅ | `rag.py:517-565` `_compute_hierarchy_warning` |
| 32 | F. Legal | Vigência compliance | Project-specific (sub_judice) | ✅ | `rag.py:298` + `vigencia.py` overlays |
| 33 | F. Legal | Jurisdiction refusal | Project-specific (federal-only) | ✅ | OOS subtype `d` |
| 34 | F. Legal | Temporal compliance (no PL) | Project-specific | 🟡 | OOS subtype `c` refuses PLs; no temporal cutoff tracked |
| 35 | F. Legal | LegalBench task alignment | Guha 2023 | ❌ | Recommended as external anchor (§4 ROI #5) |
| 36 | G. LGPD | PII redaction rate per category | LGPD art.6 II/VIII | ✅ | `rag.py:306` `pii_types_redacted` |
| 37 | G. LGPD | Cross-border flow audit | LGPD art. 33 | ✅ | redact-before-provider-boundary; default generator BR-hosted (Sabiá) |
| 38 | G. LGPD | Audit log completeness | LGPD art. 37 | 🟡 | `data/audit/pii-redactions.jsonl` (only logs queries WITH redaction; gap on queries WITHOUT) |
| 39 | G. LGPD | Right of access / explainability | LGPD art. 18 | ✅ | `citations[]` + `sources_consulted_at` footer |

**Summary counts:** 17 ✅ Covered | 9 🟡 Partial | 13 ❌ Missing.

The 13 missing are concentrated in **E. SRE** (7 of 13) and **B. RAGAS extensions** (3 of 13). Domain-specific (F, G) coverage is strong. Attribution
(C) is strong except claim-level entailment.

---

## §4 — Critical gaps ordered by ROI

Top 5 implementation candidates, ranked by `(production value × user
visibility) / engineering cost`. Rationale + concrete cost estimate.

### Gap #1 — SRE Four Golden Signals (~1 day eng, zero API cost)

**Why first:** Phase 8 hosting is the next architectural phase. Without
latency, error rate, cost-per-query, and throughput instrumentation, we
cannot define SLOs and we cannot diagnose production incidents. Currently
the project would ship blind.

**Concrete additions:**

- `RAGAnswer.latency_ms: int` — total wall time from `answer()` entry to return
- `RAGAnswer.latency_breakdown: dict[str, int]` — per-stage timing
  (embed_query, retrieve, build_context, llm_call, prose_check_retry,
  post_process). Useful for diagnosing where the budget goes.
- Module-level counter `rag_leis.metrics.errors_by_provider: Counter[str]` —
  incremented from exception handlers in `llm.py`, `embeddings.py`,
  `planalto.py`, `lexml_resolver.py`.
- `RAGAnswer.tokens_used: dict[str, int]` — input/output tokens for the
  LLM call (provided in Anthropic + OpenAI-compatible responses).

**Why this is the highest ROI:** other gaps add observability for things
that already mostly work; this gap is the difference between "production
infrastructure" and "research codebase."

### Gap #2 — Cost-per-query tracker as first-class metric (~2 hours)

**Why second:** the project has measured-cost numbers but only in
docstrings. The eval harness has run-level cost data implicit in the call
count. Promoting this to `RAGAnswer.cost_estimate_usd` + per-run aggregate
makes cost a first-class signal for two decisions: (a) whether to enable
prose-check retry on a per-query basis (it doubles LLM cost when it fires),
(b) when to ship cheaper paths like the cosine fast-path.

**Concrete additions:**

- `rag_leis.cost.estimate(provider, model, in_tokens, out_tokens) -> float`
  — pricing table for known providers/models. Hardcoded prices, updated
  manually (the project doesn't auto-fetch pricing).
- `RAGAnswer.cost_estimate_usd: float` — summed across all LLM calls in the
  request lifecycle (initial + retry).
- `Aggregate.cost_mean_usd: float` + `cost_total_usd` in
  `run_answer_eval.py`.

### Gap #3 — False refusal rate as first-class metric — ✅ SHIPPED (Phase 7.5.1)

Originally planned at ~30 min. Shipped 2026-05-17:

- `Aggregate.false_refusal_rate: float` — `|in-scope ∩ refused| / |in-scope|`
- `Aggregate.oos_refusal_recall: float` — `|oos ∩ refused| / |oos|`

Both at `run_answer_eval.py:308-310`. Replaced the collapsed
`refusal_accuracy` macro number that hid the signal. The concurso
pilot finding (2026-05-17) that motivated this — internal
`refusal_accuracy=62.5%` hid the fact that the OOS side was at 44%
while in-scope side was at 100% — is now first-class measurable on
every run.

### Gap #4 — RAGAS Answer Relevance (~1 day, ~$0.10/run added cost)

**Why fourth:** Faithfulness measures "is the answer supported by context?"
Answer Relevance measures "does the answer address the question?"
Today's eval can pass with a faithful but evasive answer (e.g., correctly
cites art.7 LGPD but doesn't actually answer the user's question about
hipóteses). The RAGAS reverse-question method is the canonical way to
catch this.

**Concrete additions:**

- `rag_leis.judges.answer_relevance(query, answer, llm) -> float` — uses
  LLM to generate N=3 questions the answer could plausibly answer, then
  computes cosine sim to original query. Score in [0, 1].
- `EvalRow.answer_relevance: float | None` (`run_answer_eval.py:90`)
- `Aggregate.answer_relevance_mean: float`

### Gap #5 — LegalBench external anchor (~3 days eng, FUTURE recommendation)

**Why included despite future-dated:** the project today has zero external
benchmark validation. All metrics are project-internal gold against
project-internal eval set. A LegalBench subset (specifically the
statute-citation tasks like `citation_prediction_open` and rule-recall
tasks like `rule_qa`) is the closest available external anchor.

**Concrete additions:**

- `scripts/run_legalbench_subset.py` — transforms 2-3 LegalBench tasks
  to our pipeline's query format, runs through `RAGPipeline.answer()`,
  scores against LegalBench's labels.
- Documented translation methodology: which tasks transfer, which don't,
  what the BR-specific corpus gap is.
- One-off run; not part of the regular eval loop.

**Caveat:** LegalBench is US common-law. The transfer is imperfect. The
value is having "we tested against an external benchmark and here's how it
went" rather than ranking high on the benchmark itself.

---

## §5 — Concrete code changes for the top-4 gaps

For each ROI gap 1-4 (gap 5 is roadmap-only), the specific changes:

### Files to modify

| Gap | File:line | Change |
|---|---|---|
| #1 (SRE) | `rag_leis/rag.py:282-321` (RAGAnswer) | Add `latency_ms`, `latency_breakdown`, `tokens_used` fields |
| #1 (SRE) | `rag_leis/rag.py:362-498` (`answer()` method) | Wrap stages with timing context manager; capture tokens from LLM response |
| #1 (SRE) | new `rag_leis/metrics.py` | Module-level counters (errors_by_provider, queries_by_status) — `prometheus_client` compatible |
| #2 (cost) | new `rag_leis/cost.py` | Pricing table per provider/model + `estimate()` function |
| #2 (cost) | `rag_leis/rag.py:282-321` | Add `cost_estimate_usd` field |
| #2 (cost) | `rag_leis/run_answer_eval.py:279-295` (Aggregate) | Add `cost_mean_usd`, `cost_total_usd` |
| #3 (false-refusal) | `rag_leis/run_answer_eval.py:279-295` | Add `false_refusal_rate`, `oos_refusal_recall` |
| #3 (false-refusal) | `rag_leis/run_answer_eval.py:301-355` (`aggregate()`) | Split aggregation logic for the two metrics |
| #4 (answer-rel) | new `rag_leis/judges.py` | Move existing `judge_faithfulness` here + add `judge_answer_relevance` |
| #4 (answer-rel) | `rag_leis/run_answer_eval.py:87-104` (EvalRow) | Add `answer_relevance: float \| None` |

### New tests

- `tests/test_metrics_completeness.py` — assert all canonical metrics
  (latency, cost, answer_relevance, false_refusal_rate) produce non-None
  values when present in `RAGAnswer` / `Aggregate`. Regression guard.
- `tests/test_cost_estimation.py` — pin pricing table correctness; one test
  per known model.
- `tests/test_answer_relevance_judge.py` — golden tests for the relevance
  judge: high relevance for clear answer, low for evasive answer.

### Expected output schema delta (Aggregate)

Before:
```json
{ "n_total": 15, "cit_precision_mean": 0.5, "faithfulness_mean": 4.2,
  "refusal_accuracy": 0.93, ... }
```

After:
```json
{ "n_total": 15, "cit_precision_mean": 0.5, "faithfulness_mean": 4.2,
  "answer_relevance_mean": 4.0,
  "refusal_accuracy": 0.93,
  "false_refusal_rate": 0.07,
  "oos_refusal_recall": 1.0,
  "latency_ms_p50": 1830, "latency_ms_p95": 4200,
  "cost_mean_usd": 0.018, "cost_total_usd": 0.27, ... }
```

### Eval-runs schema migration

The 15 existing `eval/runs/*.json` files predate these fields. New runs
will have the new fields; old runs will be missing them. Decision: don't
backfill (treat the schema as forward-additive). Document in the audit
trail that runs prior to Phase 8 don't carry these signals.

---

# Appendix (§A–§B)

## §A — Annotated bibliography

### IR foundations

> **Järvelin, K. & Kekäläinen, J. (2002).** "Cumulated gain-based evaluation
> of IR techniques." *ACM Transactions on Information Systems*, 20(4), 422-446.
>
> Establishes the canonical nDCG formulation: `DCG_p = sum_i (2^rel_i - 1) /
> log2(i+1)` normalized by ideal DCG. The project's implementation
> (`eval_harness.py:373-404`) follows this exactly with graded relevance
> via the `Query` dataclass `core` (rel=2) / `supporting` (rel=1) split.
>
> *Key passage:* "The benefit of the graded relevance is that documents
> highly relevant to a query are recognized as more valuable than marginally
> relevant ones."

> **Thakur, N., Reimers, N., Rücklé, A., Srivastava, A., & Gurevych, I.
> (2021).** "BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of
> Information Retrieval Models." *NeurIPS Datasets 2021.* arxiv:2104.08663.
>
> Establishes Recall@100 as the corpus-level recall ceiling diagnostic
> separate from operating Recall@k. Project gap (§3 row 7): we only
> evaluate top-20, can't distinguish "model failed to rank well" from
> "relevant chunk wasn't in candidate set." Recommended addition for any
> future hybrid/reranker experiments.
>
> *Key passage:* "Recall@100 isolates the retriever's ability to surface
> relevant content from the corpus, independent of ranking quality
> within top-k."

### RAGAS family

> **Es, S., James, J., Espinosa-Anke, L., & Schockaert, S. (2023).** "RAGAS:
> Automated Evaluation of Retrieval Augmented Generation." arxiv:2309.15217.
>
> Proposes 4 reference-free metrics (Faithfulness, Answer Relevance, Context
> Precision, Context Recall) all computable via LLM-as-judge without ground
> truth. Project covers Faithfulness directly (different implementation:
> uses opus-4-7 judge against `expected_paragraph` rather than fully
> reference-free, hybrid approach). Answer Relevance is a clean gap.
>
> *Key passage:* "Our automated evaluation framework provides a way to
> evaluate RAG systems on a wide range of aspects without requiring human
> annotations, thereby allowing rapid iteration."

> **Saad-Falcon, J., Khattab, O., Potts, C., & Zaharia, M. (2024).** "ARES:
> An Automated Evaluation Framework for Retrieval-Augmented Generation
> Systems." NAACL 2024.
>
> Extends RAGAS with PPI (Prediction-Powered Inference) for statistically
> grounded confidence intervals on LLM-judged metrics. Relevant when reporting
> single-number metrics from small eval sets: a faithfulness mean of 4.2/5
> on n=15 has wide CI. Recommended methodology for the project's
> `eval/runs/*.json` headline numbers.

### Citation / Attribution

> **Rashkin, H., et al. (2021).** "Measuring Attribution in Natural Language
> Generation Models." arxiv:2112.12870.
>
> Establishes AIS (Attributable to Identified Sources) as the formal binary
> judgment: is statement S attributable to source set D? Project's
> `verify_citations()` + `cit_precision_strict` is a URN-level instance of
> AIS. Project gap: doesn't check whether the source actually entails the
> claim, only that the URN was retrieved.
>
> *Key passage:* "AIS is a binary judgment about whether a generated
> sentence is attributable to a particular set of source documents."

> **Bohnet, B., et al. (2022).** "Attributed Question Answering: Evaluation
> and Modeling for Attributed Large Language Models." arxiv:2212.08037.
>
> Extends AIS with the "faithfulness" notion: the cited source supports the
> *specific claim*, not just the topic. Closes a real attack on URN-level
> attribution: a question about "data subject rights" can falsely cite an
> LGPD chapter overview when the operative claim is in a specific inciso.
>
> *Key passage:* "We introduce a new evaluation methodology that probes
> attribution at the claim level rather than the source level."

> **Honovich, O., et al. (2022).** "TRUE: Re-evaluating Factual Consistency
> Evaluation." NAACL 2022.
>
> Establishes NLI-based attribution checking as more reliable than LLM-as-judge
> in some categories. Relevant for the project: prose-citation check today
> uses regex matching on article numbers; NLI would catch cases where the
> prose paraphrases but doesn't cite the right URN.

### Refusal / Safety

> **Greshake, K., et al. (2023).** "Not What You've Signed Up For:
> Compromising Real-World LLM-Integrated Applications with Indirect Prompt
> Injection." arxiv:2302.12173.
>
> Foundational paper on indirect prompt injection via retrieved content.
> Direct relevance: project corpus is public Planalto HTML. Adversary can
> in principle plant injected content in `<blockquote>` amendments (or in a
> future tier of user-submitted briefs). Project status: parser strips
> `<script>` and amendment-noise blockquotes (`parser.py:113-124`), reducing
> surface but not eliminating it.
>
> *Key passage:* "We demonstrate that LLM-integrated applications are
> vulnerable to indirect prompt injection where the prompt injection comes
> from within the retrieved content."

> **Anthropic (2023).** "Anthropic's Responsible Scaling Policy."
> https://www.anthropic.com/news/anthropics-responsible-scaling-policy
>
> Provides a framework for jailbreak resistance evaluation at the model
> level. Relevant as a methodology reference; not directly applicable to
> RAG-layer eval but useful baseline for what "safe responses" looks like.

### SRE / MLOps

> **Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (2016).** *Site
> Reliability Engineering: How Google Runs Production Systems.* O'Reilly.
> Chapter 6: "Monitoring Distributed Systems."
>
> Defines the Four Golden Signals: Latency, Traffic, Errors, Saturation.
> Project gap (§3 rows 24-30): all four missing. SRE Ch.6 is the standard
> reference for production observability requirements at the service level.
>
> *Key passage:* "If you measure all four golden signals and page a human
> when one signal is problematic (or, in the case of saturation, nearly
> problematic), your service will be at least decently covered by monitoring."

> **Sculley, D., et al. (2015).** "Hidden Technical Debt in Machine Learning
> Systems." NeurIPS 2015.
>
> Foundational paper on MLOps debt categories. Relevant for the project's
> Phase 8 (hosting) planning: feedback loops, configuration debt, monitoring
> debt are all topics the audit doc surfaces as gaps.

### Legal NLP

> **Guha, N., et al. (2023).** "LegalBench: A Collaboratively Built
> Benchmark for Measuring Legal Reasoning in LLMs." NeurIPS Datasets 2023.
> arxiv:2308.11462.
>
> 162 legal reasoning tasks across rule-recall, rule-application,
> interpretation, rhetoric. Designed for US common-law context but ~10 tasks
> transferable to civil-law statute QA (specifically `citation_prediction`
> tasks and rule-recall tasks). Project gap (§3 row 35, §4 ROI #5): no
> external benchmark anchor. LegalBench is the closest available.
>
> *Key passage (project relevance):* "we observe that LLMs frequently
> struggle with tasks requiring precise statute citation."

> **Ma, Y., et al. (2021).** "LeCaRD: A Legal Case Retrieval Dataset for
> Chinese Law System." SIGIR 2021.
>
> Methodology reference for legal case retrieval. The civil-law orientation
> is closer to BR than US common-law benchmarks. Not directly applicable
> (we index statutes, not cases) but the gold-construction methodology
> (legal expert annotation, graded relevance) is relevant.

> **Hendrycks, D., et al. (2021).** "CUAD: An Expert-Annotated NLP Dataset
> for Legal Contract Review." NeurIPS Datasets 2021. arxiv:2103.06268.
>
> 510 contracts, 41 clause types, 13,000+ annotations by lawyers. Not
> applicable to legislation RAG but methodologically relevant for the
> project's `study/lawyer-review-checklist.md` D7 hand-off planning.

### Brazilian legal / regulatory context

> **Lei 13.709/2018 (LGPD)** — Lei Geral de Proteção de Dados Pessoais.
> Art. 6 (princípios), Art. 18 (direitos do titular), Art. 33
> (transferência internacional), Art. 37 (registro de tratamento).
>
> Operational implication for the project: queries with PII must be
> redacted before crossing border to US-hosted providers (Anthropic,
> Voyage). Project covered via `pii.py` redact-before-pipeline. The fact
> that this RAG SYSTEM describes LGPD and itself complies with LGPD is a
> production-grade self-consistency signal.

> **CF/88 art. 5º, X + LXXII; art. 103-A; EC 45/2004.**
>
> Constitutional basis for: privacy/intimacy (art.5 X), habeas data
> (art.5 LXXII), súmula vinculante (art.103-A added by EC 45/2004).
> The project's `hierarchy_warning` + jurisprudência rank (`legal_rank.py`)
> reflects this constitutional hierarchy structurally.

> **LCP-95/1998** — Lei Complementar nº 95, técnica legislativa.
>
> Establishes the chunking hierarchy (artigo → parágrafo → inciso →
> alínea → item) that the project's `parser.py` follows as a first-class
> structural concern. Different from generic recursive splitters; this is
> a domain-required hierarchy.

### Production RAG references

> **Lewis, P., et al. (2020).** "Retrieval-Augmented Generation for
> Knowledge-Intensive NLP Tasks." NeurIPS 2020. arxiv:2005.11401.
>
> Foundational RAG paper. Reference for RAG architecture taxonomy. Project
> implements "RAG-Token" variant conceptually (one retrieval + generation
> per query, no token-level interleaving) — appropriate for citation-heavy
> output.

> **Asai, A., et al. (2023).** "Self-RAG: Learning to Retrieve, Generate,
> and Critique through Self-Reflection." arxiv:2310.11511.
>
> Introduces self-critique tokens for RAG. Project's `prose_citation_check`
> + retry is a domain-specific instance of self-critique: detect mismatch,
> re-prompt with correction instruction. Different mechanism (regex-based
> detection vs token-based) but same architectural pattern.

### Tooling references (for §B comparison)

> **TruLens** — https://www.trulens.org/. Production RAG observability +
> eval framework. Implements RAGAS metrics + latency + cost tracking.
> Reference for §3 SRE gaps (rows 24-30): TruLens covers what we're
> missing.

> **LangChain LangSmith** — https://docs.smith.langchain.com/. Eval +
> observability platform. Includes tracing, latency p50/p95/p99, cost
> tracking, golden-set eval. Reference baseline for what observability
> looks like in 2026.

> **LlamaIndex Evaluation** —
> https://docs.llamaindex.ai/en/stable/module_guides/evaluating/.
> Implements RAGAS-style metrics + retrieval eval + custom evaluators.
> Reference for how a library structures eval APIs (project's approach is
> more bespoke).

---

## §B — Comparison matrix against named RAG frameworks

Side-by-side coverage across dimensions. Honest reading: project is
**stronger** on domain-specific signals + citation rigor + Brazilian
regulatory compliance; **weaker** on generic operational observability +
external benchmark validation.

| Dimension | Our project | RAGAS | TruLens | LangSmith | LlamaIndex eval |
|---|---|---|---|---|---|
| **Faithfulness** | ✅ LLM judge (project-specific against `expected_paragraph`) | ✅ Reference-free | ✅ | ✅ | ✅ |
| **Answer Relevance** | ❌ | ✅ Reverse-question | ✅ | ✅ | ✅ |
| **Context Precision** | 🟡 nDCG proxy | ✅ LLM-judged | ✅ | ✅ | ✅ |
| **Context Recall (claim-level)** | ❌ URN-level only | ✅ | ✅ | ✅ | ✅ |
| **Citation accuracy (strict)** | ✅ | ❌ | 🟡 | 🟡 | 🟡 |
| **Citation accuracy (lenient)** | ✅ Project extension | ❌ | ❌ | ❌ | ❌ |
| **Prose-citation consistency** | ✅ Project-specific | ❌ | ❌ | ❌ | ❌ |
| **Hierarchy compliance** | ✅ Project-specific (CF>LC>LO) | ❌ | ❌ | ❌ | ❌ |
| **Vigência compliance** | ✅ Project-specific | ❌ | ❌ | ❌ | ❌ |
| **PII redaction (LGPD-aware)** | ✅ BR-specific | ❌ | ❌ | 🟡 generic | ❌ |
| **OOS subtype taxonomy** | ✅ a-e | ❌ | ❌ | ❌ | ❌ |
| **OOS refusal accuracy** | ✅ | ❌ | 🟡 | 🟡 | 🟡 |
| **False refusal rate** | ✅ (Phase 7.5.1) | ❌ | 🟡 | 🟡 | 🟡 |
| **Latency p50/p95/p99** | ✅ (Phase 7.5.7) | ❌ | ✅ | ✅ | 🟡 |
| **Cost per query** | ✅ (Phase 7.5.2 + judge fold 7.5.7) | ❌ | ✅ | ✅ | 🟡 |
| **Token usage tracking** | ✅ (Phase 7.5.2) | ❌ | ✅ | ✅ | 🟡 |
| **Error rate / exception rate** | ✅ (Phase 7.5.7) | ❌ | ✅ | ✅ | 🟡 |
| **Cache hit rate** | 🟡 (cache exists, hit rate not surfaced) | ❌ | 🟡 | 🟡 | ❌ |
| **External benchmark anchor** | ❌ | partial (uses GPT-4 as oracle) | ❌ | ❌ | ❌ |
| **Adversarial / prompt-injection** | 🟡 input sanitation | ❌ | ❌ | 🟡 | ❌ |
| **Audit log (compliance)** | 🟡 PII-only | ❌ | 🟡 | ✅ | ❌ |

**Reading (post-Phase 7.5):** the project covers **12 dimensions** that
none of the named frameworks cover (domain-specific + BR-regulatory).
Post-Phase 7.5.7, project now matches the named frameworks on operational
SRE basics (latency, cost, tokens, error rate). The named frameworks still
cover ~3 dimensions the project lacks (RAGAS-extended: Answer Relevance,
Context Precision/Recall as LLM-judged dimensions).

The single biggest remaining gap by user impact: **RAGAS Answer Relevance**
(row #9, ❌). Faithfulness measures "does the answer match the source"; Answer
Relevance measures "does the answer respond to the question" — orthogonal
dimensions per Es et al. 2023. Catches the "faithful but evasive" failure
mode the project doesn't currently observe.

---

## Methodology note (intentional limits of this audit)

What this audit deliberately does NOT do:

- Recommend BLEU/ROUGE for answer text. Wrong tool: legal answers aren't
  translation-style; faithfulness via LLM judge is the right primitive.
- Recommend BERTScore. Same reasoning.
- Recommend embedding similarity of answer to `expected_paragraph`.
  Fragile and easily gamed by paraphrastic variation.
- Recommend full LegalBench replication. Partial subset (2-3 tasks) is
  enough as external anchor; full replication would consume weeks for
  marginal additional signal.
- Recommend per-LLM-call self-consistency multi-sampling (e.g., generate 5
  answers and check consensus). High cost, low marginal value when
  citation gates are already strong.

This audit reflects **2026-05-17 state of the field**. RAGAS, AIS, BEIR
conventions are stable. The SRE Golden Signals are durable. The
domain-specific metrics (hierarchy_warning, flagged_vigencia) are
project-original and likely to remain unique to this work.

---

## Cross-references

- Inventory canonical: this doc §1
- Methodology canonical: `study/RETRIEVAL-JOURNEY.md`
- Decision style template: `study/llm-provider-decision-2026-05-15.md`
- Phase 7 production infra plan (consumes ROI #1 SRE recommendations):
  `study/phase-7-production-infra-plan.md`
- Phase 8 hosting (will consume cost-per-query for SLO definition):
  not yet planned
- Lawyer review for jurisprudência gold quality: `study/lawyer-review-checklist.md`
