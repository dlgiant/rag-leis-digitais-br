# Query expansion plan (post-pilot + post-audit)

**Date:** 2026-05-17
**Status:** plan (not yet implemented)
**Inputs:** `study/concurso-pilot-findings.md` (pilot baseline) +
`study/rag-eval-metrics-audit.md` (gold-standard gaps) + web research
(post-2020 BR legal datasets)
**Tracked in:** `BACKLOG.md` § Query expansion

---

## 1. Why expand

The OAB concurso pilot (2026-05-17, `eval/oab_concurso_pilot.yaml`, 16 rows)
surfaced **two real production gaps** that the internal eval set
(`eval/answer_queries.yaml`, 29 rows) had hidden through selection bias:

| Metric | Internal answer-eval | Concurso pilot | Gap |
|---|---|---|---|
| Overall refusal accuracy | 93.8% | **62.5%** | **-31pp** |
| OOS-B (adjacent-without-coverage) | not measured | **0/2 (0%)** | new failure mode surfaced |
| In-scope CDC citation coverage | n/a (no CDC queries) | 0/2 on CDC questions | new gap surfaced |

**Diagnosis** (per `study/concurso-pilot-findings.md` §"What the data tells us"):

- Our internal OOS rows were curated by us to be "obviously" out-of-scope.
- Real concurso queries are more adjacent (LGPD overlaps tangentially with
  tax data protection; labour law has data clauses) — the model
  over-answers when context is "close enough."
- The current eval set therefore **overstates production refusal quality**
  by ~31 percentage points.

The fix isn't just iteration on SYSTEM_PROMPT — we need a **larger and
more diverse OOS test surface** to honestly measure refusal behavior, and
we need **more in-scope queries from external authoritative sources**
(OAB official exams) to ground citation quality against the kind of
fact-pattern lawyers actually encounter.

---

## 2. Recap — current project state

### Phases completed (2026-05-11 → 2026-05-17)

| Phase | Status | Key deliverable |
|---|---|---|
| Phase 0 | ✅ | Parser foundations, dedup logging, cache content-hash gate |
| Phase 1 | ✅ | TIER_1 + TIER_2 corpus (16 docs federal + state-civil) |
| Phase 2 | ✅ | RAGPipeline + cite-and-verify + answer-eval set v0 |
| Phase 3 | ✅ | Vigência overlay + Lei 9.507 + Decreto cross-test |
| Phase 4 | ✅ | LLM provider abstraction; Sabiá-3.1 vs Sonnet-4-5 cross-validation; PII redactor; query-type classifier; ANPD pdfplumber parser; Tier-3 ingestion |
| Phase 5 | ✅ | legal_rank + hierarchy_warning; prose-citation check + reprompt; source-as-of-date footer; EC linkage; OOS subtype taxonomy a-e |
| Phase 6 | ✅ | Tier-4 jurisprudência (7 chunks: 3 STJ súmulas + 4 STF temas); URN scheme §9.5 |
| Phase 7 | ✅ | Production infra: SHA-256 diff + audit log + F5 WAF strip + parser §-suffix + inc-suffix fixes + title-prefix text-mode + orchestrator with gate+rollback + GitHub Actions weekly cron + smoke test workflow + runbook |
| Phase 8 | ⏸ | Hosting/API/observability (deferred; see audit doc §4 gap #1) |
| Phase 9 | ⏸ | Compliance / lawyer review (depends on D7) |

### Corpus current state

- **Tier 1** (13 docs): CF/88, CDC, CP, Lei Software, LDA, LAI, Lei
  Carolina Dieckmann, MCI, Decreto 8.771, Lei 9.507 (habeas data), LGPD,
  Lei 13.853 (ANPD), Lei 14.155 (crimes cibernéticos pós-Estelionato
  Eletrônico).
- **Tier 2** (4 docs): Lei 11.419 (processo eletrônico), Lei 14.063
  (assinaturas), Lei 14.129 (Gov Digital), CC arts. 11-21 (Cap.II
  Personalidade).
- **Tier 3** (2 docs): ANPD Res 15/2024 (incidentes), Res 4/2023 (dosimetria).
- **Tier 4** (7 chunks): STJ Súmulas 227/403/479, STF Temas 786 (verbatim)
  + 987/533/815 (stubs pendentes D7).
- **Total:** ~7200 chunks, indexed via Voyage-3-large
  + `title+label+nav+caput+text`.

### Eval current state

| Set | Count | Purpose | Status |
|---|---|---|---|
| `eval/queries.yaml` | 104 | Retrieval-only (nDCG/Recall/MRR) | Mature |
| `eval/answer_queries.yaml` | 29 (14 inscope + 15 OOS) | End-to-end with LLM judge | Mature but biased (see §1) |
| `eval/oab_concurso_pilot.yaml` | 16 (7 inscope + 9 OOS) | External OAB anchor | **Pilot — needs expansion** |

### Production metrics (latest known, 2026-05-17)

- nDCG@10 = 0.7235
- Recall@20 = 0.871
- MRR@10 = 0.7996
- Answer-eval refusal_accuracy = 0.938
- Concurso-pilot refusal_accuracy = **0.625** (the divergence motivating this expansion)

### Gold-standard metrics audit (full at `study/rag-eval-metrics-audit.md`)

**Coverage status (39 metrics across 7 categories):**

- 17 ✅ Covered (retrieval IR, RAGAS Faithfulness, AIS citation precision/recall,
  OOS refusal, hierarchy/vigência/LGPD compliance, prose-citation check)
- 9 🟡 Partial (Context Precision proxied by nDCG; false refusal rate computable
  but not surfaced; cache hit rate exists but not measured; etc.)
- 13 ❌ Missing (mostly SRE Four Golden Signals: latency p50/p95/p99, cost
  per query, error rate, throughput; plus RAGAS Answer Relevance and
  claim-level Context Recall; plus jailbreak/adversarial test surface)

**Top 5 gaps ROI-ranked** (audit doc §4):

1. SRE Golden Signals (~1d) — required for Phase 8 hosting
2. Cost-per-query tracker (~2h)
3. False refusal rate as first-class metric (~30min)
4. RAGAS Answer Relevance separate judge (~1d, ~$0.10/run)
5. ~~LegalBench external anchor~~ — **superseded by this expansion plan**
   (BR-native concurso pilot proves higher signal than US common-law
   LegalBench would)

---

## 3. External datasets identified (post-2020 web research, 2026-05-17)

Web search + HF inspection (full citations at end). Five datasets evaluated:

| Dataset | Records | Year | License | Fit verdict |
|---|---|---|---|---|
| `eduagarcia/oab_exams` | 2210 MCQ | 2010-2018 | unspecified (public OAB content) | ✅ Already used in pilot (eval/oab_concurso_pilot.yaml). Pre-LGPD. Adequate for non-LGPD digital topics + OOS sampling. |
| `maritaca-ai/oab-bench` v2 | 105 questions + 105 guidelines | 2023-2024 (editions 39-44) | Apache-2.0 | ✅ **Post-LGPD**; ≥1 explicit LGPD question; **discursive format** (harder eval, needs LLM judge adaptation) |
| `celsowm/legalbench.br` | 1000 (4 task types) | 2025 | CC BY-SA 4.0 | ✅ **BR-native legal benchmark**; covers 15 areas including 8 not-in-our-corpus (Eleitoral, Internacional, Tributário, Previdenciário, Ambiental, ...); has 72 **closed-book rule recall** (perfect for citation eval) + 285 classification + 443 MCQ |
| `celsowm/simulado_oab` | 1010 MCQ | 2025 | unspecified | ❌ **Discard** — `fonte=grok3` (AI-generated, not real OAB); spot-check shows zero digital coverage |
| Rabula (FGV) | 1201 evaluation criteria | 2024 | unclear | ⏸ Investigate later — paper at CEUR-WS Vol-4089; dataset URL not yet located |

### Why no public dataset has substantial post-2020 LGPD coverage

- OAB started actively testing LGPD only ~2019-2020 (LGPD effective Aug 2020)
- Most public datasets stop at 2018 or focus on broader law areas
- Commercial banks (Qconcursos, Tec Concursos, Estratégia) have hundreds
  of LGPD questions but **are not redistributable**
- Realistic path to LGPD-rich eval: **manual curation from OAB editions
  39-44 official PDFs** (public on OAB site)

---

## 4. Expansion proposal — 4 sub-phases ordered by ROI

Each sub-phase is independently shippable. Run in order; stop if signal
plateau or budget exhausted.

### Sub-phase A — `legalbench.br` OOS expansion (~2h eng, zero API cost)

**What:** Sample 30-50 rows from `celsowm/legalbench.br` `text_classification`
task (285 available) where `legal_area` is **outside our corpus**: Direito
Eleitoral, Direito Internacional, Direito Tributário, Direito Previdenciário,
Direito Ambiental, Direito Empresarial, Direito Trabalhista, Direito
Processual (Civil+Penal).

**Why:** Concurso pilot proved OOS-A refusal is 43% (should be near 100%).
Internal OOS set (15 rows) is too small + curated to be "obviously" OOS.
Sampling 30-50 from a benchmark we didn't construct removes selection bias.

**Output:** `eval/legalbench_br_oos.yaml` — same schema as `oab_concurso_pilot.yaml`
(category=oos_a, expected refused=True, no gold_urns needed). Update
`rag_leis/run_concurso_eval.py` to optionally load this file as additional rows.

**Expected outcome:** total OOS test surface grows from 9 (current pilot) to
~40-60 rows. Refusal accuracy measurement becomes statistically meaningful
(±3-5pp CI at n=50 vs ±15pp at n=9).

**Cost:** ~$1.50 Sabiá calls for the new OOS rows (50 × $0.03). Within budget.

### Sub-phase B — `legalbench.br` rule recall as citation eval (~3h eng)

**What:** Use the 72 `closed_book_qa` rows from `celsowm/legalbench.br`
where `answer` is formatted as `"Art. N, Inc. X, CF/88"` etc. Filter to
those whose articles are **in our corpus** (CF, CC, CP — likely 30-50
rows out of 72). Transform `answer` → our URN scheme. Use as eval
queries with strict citation matching: pipeline must return citation
URN equal to the parsed gold URN.

**Why:** This is the cleanest possible citation evaluation — single
correct article, parsed from a labeled dataset. Currently our citation
precision uses `gold_urns` lists from human curation; legalbench.br gives
us EXTERNAL gold that we didn't write, which is more rigorous.

**Output:** `eval/legalbench_br_rule_recall.yaml` + scoring extension in
`run_concurso_eval.py` (new category `rule_recall`; metric: exact citation
match rate).

**Expected outcome:** new external-anchored metric `rule_recall_precision`
reportable alongside our existing internal citation precision. Gives
defensible answer to "how does this RAG do on a third-party-labeled task?"

**Cost:** ~$1.50 Sabiá calls.

### Sub-phase C — `maritaca-ai/oab-bench` discursive subset (~4-5h eng)

**What:** Curate ~10 discursive questions from `oab-bench` v2 (editions
39-44, post-LGPD), specifically including:
- `39_direito_civil_questao_4` (explicit LGPD art.8 §5 — consent revocation)
- Any others touching MCI / dados pessoais / direito digital (need
  manual inspection of all 105 questions)

Adapt `run_concurso_eval.py` to handle discursive scoring (LLM-judge
against the provided `guidelines` rubric instead of `gold_urns`
comparison). This is closer to the answer-eval `faithfulness` pattern but
against an external rubric.

**Why:** Discursive format stresses different parts of the pipeline than
MCQ: (a) longer answer generation, (b) multi-aspect coverage, (c) the
"peça jurídica" format (legal drafting). MCQ tests retrieval+citation;
discursive tests generation quality.

**Output:** `eval/oab_bench_discursive_subset.yaml` + new
`rag_leis.judges.discursive_rubric_judge()` function (RAGAS-extension
style; reuses opus judge infrastructure).

**Expected outcome:** first measurement of project pipeline on discursive
format. Likely lower scores than MCQ initially — that's the signal.

**Cost:** ~$3-5 (sabia generation + opus judge × 10 rows × multiple aspects).

### Sub-phase D — OAB 39-44 manual LGPD curation (~4-6h, deferred)

**What:** Download official OAB exam PDFs editions 39-44 from oab.org.br
(public). Manually extract questions touching LGPD, MCI, crimes
cibernéticos, dados pessoais. Estimate: 15-30 questions across 6 editions.

**Why:** This is the only path to a LGPD-rich eval (no public dataset has
this coverage). 2023-2024 OAB has actively tested LGPD post-effectivity.

**Defer condition:** only execute if sub-phases A-C don't surface enough
LGPD-specific signal. Manual curation is expensive labor; we should
exhaust automated/dataset options first.

**Output:** `eval/oab_lgpd_curated.yaml` — manually-curated LGPD-focused
in-scope set. Format: paraphrased query (copyright caution) + `gold_urns`
mapped to LGPD chunks (we already index LGPD entirely).

**Cost:** human time only (~4-6h). Negligible API cost.

---

## 5. Out of scope / explicit non-goals

To prevent scope creep:

- ❌ **Full Rabula integration** until dataset URL is located and license
  confirmed
- ❌ **Adding `celsowm/simulado_oab`** — grok3-generated, quality risk
- ❌ **Indexing additional non-digital legal areas** (Tributário,
  Eleitoral) to "support" the legalbench.br tasks — those tasks are
  meant as OOS, indexing them defeats the purpose
- ❌ **Full LegalBench (US) integration** — superseded by these BR-native
  options
- ❌ **Building our own concurso prep platform** — that's a product, not
  an eval task. Stay focused on measurement.

---

## 6. Verification — how to know expansion worked

After all 4 sub-phases:

1. **Refusal accuracy CI tightens** — total OOS rows ~60 (9 current + 50
   new), CI on refusal_accuracy drops from ±15pp to ±5pp at 95% confidence
2. **OOS-A refusal rate improves measurably** — current 43% is the
   baseline; target ≥80% after SYSTEM_PROMPT iteration informed by the
   expanded OOS set
3. **External rule recall metric exists** — `rule_recall_precision`
   reportable alongside internal citation precision; if both move
   together on prompt iterations, internal eval is honest signal; if
   they diverge, internal eval has selection bias
4. **First measurement on discursive format** — provides anchor for
   future generation-quality work (Phase 8+ may need RAGAS Answer
   Relevance, audit doc gap #4)
5. **LGPD-specific in-scope metric** (after sub-phase D) —
   `lgpd_inscope_citation_coverage` becomes its own report line; surfaces
   whether LGPD chunks are well-indexed vs not

---

## 7. Connection to existing roadmap

This expansion plan connects to:

- **`study/rag-eval-metrics-audit.md` §4 gap #5** — LegalBench external
  anchor; this plan supersedes with BR-native alternatives
- **`study/concurso-pilot-findings.md` §"Concrete next steps" #4** —
  "Expand pilot to ~30 in-scope + ~25 OOS" — sub-phases A+C deliver this
- **`study/phase-7-production-infra-plan.md`** — refresh orchestrator's
  pytest gate could include the new eval files; currently only includes
  `eval/queries.yaml` retrieval metrics
- **`study/lawyer-review-checklist.md`** D7 — sub-phase D's manual
  curation could be a lawyer-validated subset rather than operator-only

---

## 8. Sources (datasets + research)

- [eduagarcia/oab_exams](https://huggingface.co/datasets/eduagarcia/oab_exams)
- [maritaca-ai/oab-bench](https://huggingface.co/datasets/maritaca-ai/oab-bench)
  + [GitHub](https://github.com/maritaca-ai/oab-bench)
- [celsowm/legalbench.br](https://huggingface.co/datasets/celsowm/legalbench.br)
- [celsowm Brazilian legal datasets collection](https://huggingface.co/collections/celsowm/brazilian-legal-datasets)
- [Rabula paper (CEUR-WS Vol-4089)](https://ceur-ws.org/Vol-4089/paper6.pdf)
- [Automatic Legal Writing Evaluation of LLMs (arxiv 2504.21202, ICAIL 2025)](https://arxiv.org/abs/2504.21202)
- [Sabiá-4 Technical Report (arxiv 2603.10213)](https://arxiv.org/html/2603.10213v1)
- [JUÁ Benchmark (arxiv 2604.06098)](https://arxiv.org/abs/2604.06098) — BR IR benchmark, leaderboard
- [JurisTCU (arxiv 2503.08379)](https://arxiv.org/html/2503.08379v1) — TCU jurisprudence
- [LegalBench.PT (arxiv 2502.16357)](https://arxiv.org/html/2502.16357v1) — Portugal not Brazil
