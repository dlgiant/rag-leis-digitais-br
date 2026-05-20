# Backlog

Itens identificados mas não-aplicados — pra retomar quando for prioridade.

## 📌 State snapshot (2026-05-17, post-Phase 7.5)

**Phases completed:**
- ✅ Phase 0 (parser foundations, dedup logging, cache)
- ✅ Phase 1 (TIER_1+TIER_2 corpus)
- ✅ Phase 2 (RAGPipeline + cite-and-verify + answer-eval v0)
- ✅ Phase 3 (vigência overlay + Lei 9.507 + Decreto cross-test)
- ✅ Phase 4 (LLM provider abstraction; Sabiá-3.1 vs Sonnet-4-5 cross-validation; PII redactor; query-type classifier; ANPD pdfplumber parser; Tier-3)
- ✅ Phase 5 (legal_rank + hierarchy_warning; prose-citation check + retry; source-as-of-date; EC linkage; OOS subtype taxonomy a-e)
- ✅ Phase 6 (Tier-4 jurisprudência v0: 7 chunks; URN spec §9.5)
- ✅ Phase 7 (production infra: SHA-256 diff + F5 WAF strip + parser §-suffix/inc-suffix fixes + title-prefix default + orchestrator with gate+rollback + GitHub Actions weekly cron + smoke + runbook)
- ✅ **Phase 7.5 (eval expansion — closed 2026-05-17)** — see [`study/phase-7.5-findings.md`](study/phase-7.5-findings.md). 6 of 7 sub-steps shipped (7.5.6 LGPD manual deferred to D7 lawyer engagement). Eval surface grew 45 → 139 rows (+209%). Headline finding: **internal OOS refusal accuracy of 93.8% overstated external measurement (12.2%) by 6.7×** — selection bias quantified.

**Phases pending (large blocks):**
- ⏸ Phase 8 — hosting/API/observability. **Entry priority shifted post-Phase 7.5**: refusal-discipline SYSTEM_PROMPT iteration against 49 legalbench OOS rows BEFORE hosting (see `phase-7.5-findings.md` §4 — "the load-bearing Phase 8 priority shifted"). SRE Golden Signals now instrumented (no longer Phase 8 dependency).
- ⏸ Phase 9 — compliance / lawyer review (depends on D7 contracting); Phase 7.5.6 (LGPD manual curation) folded into D7 scope.

**Corpus current:** ~7200 chunks across 4 tiers (13 Tier-1 + 4 Tier-2 + 2 Tier-3 + 7 Tier-4).

**Eval current (post-Phase 7.5):** 104 retrieval queries + 29 internal answer queries + 16 concurso pilot + **49 legalbench OOS + 40 legalbench rule recall + 5 oab-bench discursive** = 243 total eval rows.
- Production retrieval: nDCG@10=0.7235, MRR@10=0.7996 (unchanged from pre-7.5 — no corpus/embedder change)
- **External rule recall (citation precision):** 97.5% (40 rows)
- **External OOS refusal:** 12.2% (49 rows) — **the headline refusal-discipline gap**
- **External discursive (OAB 2ª fase):** 54% mean (5 rows, bimodal — confirms gap)
- **Latency p50/p95:** 6.8s / 13.5s (first instrumented 7.5.7)
- **Cost per query:** $0.075 discursive / ~$0.002 short-answer (judge cost now correctly attributed)

**Gold-standard metrics audit** (full at `study/rag-eval-metrics-audit.md`, post-Phase 7.5):
- **22** ✅ Covered (was 17; +4 from 7.5.7 SRE; +1 rule recall external; +1 from 7.5.1 false_refusal_rate row-20 reconciliation; +1 from 7.6.1 Answer Relevance via judge_explanation_quality)
- **8** 🟡 Partial
- **9** ❌ Missing (claim-level Context Recall, provider availability/fallback, throughput QPS, jailbreak resistance, cache hit rate first-class, citation entailment, MAP, Recall@100, LegalBench external anchor)
- Top remaining ROI gaps: (1) RAGAS Answer Relevance ~1d; (2) refusal-discipline SYSTEM_PROMPT iteration (NEW priority from 7.5 findings); (3) LegalBench US adaptation (future external anchor).

---

## 🎯 Query expansion (post-pilot, post-audit) — ✅ MOSTLY COMPLETE via Phase 7.5

**Full plan:** [`study/query-expansion-plan.md`](study/query-expansion-plan.md).
**Findings:** [`study/phase-7.5-findings.md`](study/phase-7.5-findings.md).

**Status:** Sub-phases A (legalbench OOS), B (rule recall), C (oab-bench discursive) all shipped via Phase 7.5.3/4/5. Sub-phase D (OAB 39-44 LGPD manual) deferred to D7 lawyer engagement per Phase 7.5 closure rationale.

**Why:** Concurso pilot (2026-05-17) exposed that internal answer-eval refusal_accuracy (93.8%) overstates production behavior by ~31pp — real external queries hit 62.5%. Plus our OOS coverage is too small (15 internal + 9 pilot = 24) for tight CI. Plus no LGPD-rich queries despite LGPD being core to our corpus pitch.

**Datasets identified** (web search 2026-05-17, all post-2020 except eduagarcia):

| Dataset | Records | License | Use case |
|---|---|---|---|
| `eduagarcia/oab_exams` | 2210 MCQ 2010-2018 | public OAB | ✅ already used |
| `maritaca-ai/oab-bench` v2 | 105 discursive 2023-2024 | Apache-2.0 | ✅ post-LGPD, has ≥1 explicit LGPD |
| `celsowm/legalbench.br` | 1000, 4 task types | CC BY-SA 4.0 | ✅ BR-native, 72 rule-recall + 285 classification |
| `celsowm/simulado_oab` | 1010 MCQ 2025 | unspec | ❌ grok3-generated, discard |
| Rabula (FGV) | 1201 criteria | TBD | ⏸ paper at CEUR-WS Vol-4089, dataset URL not yet located |

**4 sub-phases ordered by ROI (detail in study doc):**

- **A. legalbench.br OOS expansion** (~2h eng + ~$1.50 API) — sample 30-50 from `text_classification` task, areas outside our corpus. Tightens refusal accuracy CI from ±15pp to ±5pp.
- **B. legalbench.br rule recall as external citation eval** (~3h + ~$1.50) — 30-50 rows where `answer="Art. N, CF/88"` mapped to our URN scheme. Adds defensible external `rule_recall_precision` metric.
- **C. oab-bench discursive subset** (~4-5h + ~$3-5) — 10 questions including the LGPD one. First discursive measurement; needs new LLM-judge against external rubric (RAGAS-extension style).
- **D. OAB 39-44 manual LGPD curation** (~4-6h human + ~$1 API, deferred) — only path to LGPD-rich eval; manual extraction from official OAB PDFs. Defer until A-C signal warrants.

**Expected outcome:** OOS test surface grows ~24 → ~60-75 rows; new external citation metric exists; first discursive eval baseline; LGPD coverage starts being measured separately.

---

## 🧪 Graph RAG concepts — Phase 7.6 closure (2026-05-19)

**Source:** [`study/paper-evaluation-graph-rag-2025.md`](study/paper-evaluation-graph-rag-2025.md) evaluating Springer 2025 ["A Graph RAG Approach to Enhance Explainability in Dataset Discovery"](https://link.springer.com/article/10.1007/s41019-025-00313-x). Three 🟢 GO concepts entered the BACKLOG; Phase 7.6 shipped two of them.

**Phase 7.6 outcomes:**

- ✅ **#3 — Explanation-quality eval dimension** (Phase 7.6.1, [findings](study/phase-7.6.1-explanation-quality-findings.md)) — shipped 2026-05-19. Closes audit Gap #4 (RAGAS Answer Relevance, now ✅). Headline: on internal eval, coherence=4.93/5 and quality=5.00/5 are nearly saturated; **compactness=3.57/5 is the discriminating axis** — answers are faithful but bloated. New diagnostic the project didn't have.
- ✅ **#2 — Per-document scope tags** (Phase 7.6.2, [findings](study/phase-7.6.2-scope-tags-findings.md)) — shipped 2026-05-19. Production-default-on (`RAGPipeline.scope_check_enabled=True`). **Negative gate result:** moved oos_a_refusal_rate from 0.122 → 0.184 (+0.062pp); gate threshold was +0.10pp. Real but underpowered signal. false_refusal_rate stayed at 0.000 — mechanism is conservative + correct. Kept in production because it adds +0.04 attributable refusal lift with no regression cost.
- ❌ **#1 — Static legal concept KG** — **PARKED in [EXPERIMENTS.md](EXPERIMENTS.md)** per D3 decision (negative gate result). The cheap version (#2) is underpowered for the same reason the expensive version would be — vocabulary needs D7 lawyer-reviewed depth, which makes #1 a Phase 9 project, not Phase 7.6.

**Net signal change from Phase 7.6:** audit Gap #4 closed; eval surface gained a new dimension (compactness); production pipeline gained a conservative scope-check that adds +2/49 OOS refusal cases.

**Phase 8 entry priority unchanged:** refusal-discipline SYSTEM_PROMPT iteration vs `eval/legalbench_br_oos.yaml` remains the load-bearing path. The 7.6.2 scope-check is a complementary +0.04 contribution; SYSTEM_PROMPT iteration is the path to the remaining 0.66 of the gap.

---

## ⚠️ Pre-launch dependency: lawyer review

Antes de Phase 9 (compliance) acontecer, há trabalho de validação
jurídica externa acumulando. Lista priorizada está em
**`study/lawyer-review-checklist.md`** — referência canônica desse
escopo. Inclui:

- 🔴 Bloqueadores: hierarquia normativa quando fontes secundárias
  mascaram primárias (ex: row 7 sanções), vigência overlay
  insuficiente, cross-doc gold incompleto
- 🟡 Importantes: 3rd precision tier, OOS adversariais, PII coverage
- 🟢 Refinamentos: citation prose check, source-as-of-date

D7 do `study/post-review-plan.md`: "vou conseguir antes de Phase 9 mas
não agora". Quando contratar, esse doc é o handoff list.

## Eval / gold

- **Revisar gold da query Tier-2 [T8] cross-doc** — "interação digital com o governo: proteção de dados e princípios". Proposta original em `eval/tier-2-queries-proposal.md` listava core = `14129 art.3 inc17` + `LGPD art.6` + `LGPD art.6;inc7`, supporting = `LGPD art.46` + `14063 art.5`. Cross-doc Tier-1×Tier-2 precisa validação manual: a query é abrangente e o gold pode estar incompleto (mesma classe de queries onde [13] foi corrigido em sessão anterior). Aplicar T1-T7 sem este, voltar com revisão dedicada.

- ✅ **DONE 2026-05-16** — ~~Investigar 597 dedups silenciosos no parser CF~~ — `_dedup_keep_last` warning era sintoma de dois bugs: **§-suffix** (Lei 14.155/21 §2-A/§4-B do CP perdidos) e **inciso-suffix** (CF art.92 inc I-A=CNJ, II-A=TST + art.93 VIII/VIII-A/VIII-B + LGPD art.55-C V-A/V-B perdidos). Ambos fixados via regex extension `(?:[-–]([A-Z])(?=[.\s,;:]|$))?` + alternation com mandatory separator. Ver memória `project-parser-bug-dedup` + commits `0effdc8` (§-suffix) + `796b179` (inc-suffix).

## Parser

- **Refatorar parser.py** — atualmente monolítico, regex-heavy. Quebrar em estágios menores testáveis (extract paragraphs → classify partition → assign parents → strip notes). Fazer junto com 0.2 Parser protocol pra Tier-3 PDFs.

## Tier-3 (✅ Phase 4.3 done)

- ✅ **DONE Phase 4.3.a-b** — ~~AnpdPdfParser~~ — Res 15/2024 (manual transcription) + Res 4/2023 (pdfplumber-extracted). 286 chunks total.
- ✅ **DONE** — ~~Documentar synthetic URN scheme da ANPD~~ — em `study/lexml-urn-spec-resumo.md` §9 (ANPD `resolucao.cd`).
- ⏸ Res 1/2021 + Res 2/2022 gated por (i) PDF cleanup OCR para a Res 2/2022 (`(cid:XXX)` font issue), (ii) page_range curation para Res 1/2021.

## Tier-4 jurisprudência (✅ Phase 6 done)

- ✅ **DONE Phase 6.1** — 7 chunks manualmente curados: 3 STJ Súmulas (227/403/479) + 4 STF Temas (786 verbatim, 987/533/815 stubs)
- ⏸ **D7 lawyer review** — substituir 3 stubs por tese verbatim + expandir curadoria. Ver `study/lawyer-review-checklist.md` item 5.
- ⏸ Phase 6.3 real scrapers (STF/STJ) — gated em D7 (precisa whitelist canônica) + Phase 7 infra (cron) — Phase 7 já feita; gate restante é só D7.

## LLM stage (Phase 2-5 done)

Most items below superseded by subsequent phases. Status updates:

- ✅ **DONE Phase 4.1** — query-type classifier + adaptive top_k (TOP_K_PER_TYPE). The "sonnet refuses row 7 inconsistently" item should be re-tested with the adaptive top_k; if still flipping, escalate.
- 🟡 **PARTIAL** — Lenient precision sweep: `alternative_acceptable_urns` set on more rows now (post Phase 5.1+ gold audits). Continued sweep is valid maintenance work.
- ✅ **SUPERSEDED Phase 5.1 + query expansion plan** — "OOS test set is tiny (3 rows)" — now 15 internal + 9 concurso pilot = 24 OOS, with subtype taxonomy a-e. Query expansion plan above grows to ~60-75 with legalbench.br.
- ⏸ **Cosine fast-path threshold (0.40) calibration** — still uncalibrated; LLM self-refusal is primary signal but cosine gate worth a synthetic adversarial test.
- ⏸ **Phase 3 candidates** (most superseded): retry policy ✅ via prose_check_retry; per-query latency/cost reporting ❌ (audit doc §4 gap #1+#2); hybrid generator (route enumeração to opus) ❌ still open.

## OOS hardening (refusal-discipline) — Phase 8 entry UNBLOCKED post-7.8

Phase 7.5.3+4+5 converged on the same diagnosis across 3 eval surfaces: pipeline is excellent at finding in-corpus content (97.5% rule recall) and bad at refusing out-of-corpus content (12.2% OOS refusal). Four phases of structural interventions (7.6.2 → 7.7 → 7.8) raised this to **0.633 = 5.2× lift**. Phase 8 hosting is no longer blocked by refusal discipline.

**Shipped:**

- ✅ **Phase 7.6.2 concept-scope tag gate** ([findings](study/phase-7.6.2-scope-tags-findings.md)) — +0.062pp
- ✅ **Phase 7.7 Fix #1 — `_is_self_refusal()` full-text scan** ([findings](study/phase-7.7-refusal-discipline-findings.md)) — +0.10pp
- ✅ **Phase 7.7 Fix #2 — `citations=[]` as implicit refusal** — +0.14pp
- ❌ **Phase 7.7 Fix #3 — SYSTEM_PROMPT iteration** — TRIED + REVERTED (net negative). Documented for reference.
- ✅ **Phase 7.8 per-citation relevance gate** ([findings](study/phase-7.8-citation-relevance-findings.md)) — **+0.22pp; gate CLEARED at 0.633**. Largest single-phase lift in the series. Catches Pattern B (wrong-law citations that pass cite-and-verify).

**Remaining work (no longer blocking; production-acceptable):**

- ⏸ **Audit doc updates** — Pattern B detection rows can flip ✅; cumulative arc deserves a §3 note
- ⏸ **Per-citation relevance as first-class eval metric** — currently a pipeline-internal signal; could be surfaced in Aggregate for telemetry
- ⏸ **Cost optimization** — relevance gate adds ~1.6s p50 latency; parallelize with main answer call if Phase 8 SLO requires
- ⏸ **Sabiá-as-its-own-judge sanity** — re-validate with Opus for the relevance gate if signal weakens over time
- ⏸ **Per-document scope tagging with finer grain** — = BACKLOG #1 still parked in EXPERIMENTS.md, no longer a critical path
- ⏸ **OOS-C category** (intentionally tricky CRIMINAL questions deceptively close to crimes cibernéticos) — propose adding via curated subset from `eduagarcia/oab_exams` and/or `legalbench.br`. Lower priority now.

## Production observability — ✅ MOSTLY COMPLETE via Phase 7.5.2 + 7.5.7

Full audit at `study/rag-eval-metrics-audit.md`. Findings: [`study/phase-7.5.7-sre-golden-signals-findings.md`](study/phase-7.5.7-sre-golden-signals-findings.md).

- ✅ **SRE Four Golden Signals: Latency + Errors** (Phase 7.5.7) — `RAGAnswer.latency_ms` + `Aggregate.latency_p50/p95/p99_ms` + per-row try/except + `error_count/rate`. Saturation/Throughput require Phase 8 HTTP harness.
- ✅ **Cost-per-query tracker** (Phase 7.5.2 + judge-cost fix in 7.5.7) — `cost.py` pricing table + `RAGAnswer.cost_estimate_usd` + `Aggregate.cost_mean_usd`. Judge spend now correctly attributed (was 13× under-reported pre-7.5.7).
- ✅ **False refusal rate as first-class metric** (Phase 7.5.1) — `Aggregate.false_refusal_rate` + `oos_refusal_recall` separately surfaced.
- ⏸ **RAGAS Answer Relevance** (~1d, ~$0.10/run) — separate LLM-judge call: reverse-question method (Es et al. 2023, arxiv 2309.15217). Still ❌ in audit doc; defer until Phase 8 entry items above resolve.

## Posts (`posts/`, gitignored)

- ✅ **DONE** — ~~Atualizar 3 drafts existentes~~ — drafts 01/02/03 reflect current numbers; new draft 04 (`04-title-prefix-broke-my-routing-intuition.md`) added 2026-05-16.
- 🟡 **READY-TO-WRITE candidates** (per `study/concurso-pilot-findings.md` + `study/rag-eval-metrics-audit.md`):
  - "Selection bias no seu eval set: como questões OAB reais expuseram 31pp de gap" (concurso pilot finding)
  - "Auditor's gold-standard checklist para legal RAG: 39 métricas, 17 que cobrimos, 13 que faltam" (audit doc summary)
  - "Parser dedup warning é signal, não ruído: dois bugs de cobertura silenciosa em um dia" (§-suffix + inc-suffix narrative)

---

## Cross-references (live docs to consult before starting any item)

- `study/RETRIEVAL-JOURNEY.md` — master methodology doc (9 second-stage techniques refuted)
- `study/rag-eval-metrics-audit.md` — full audit of 39 gold-standard metrics with sources
- `study/concurso-pilot-findings.md` — concurso pilot baseline + investigation TODOs
- `study/query-expansion-plan.md` — 4-sub-phase plan to grow eval set
- `study/llm-provider-decision-2026-05-15.md` — Sabiá vs Sonnet data-driven decision
- `study/lawyer-review-checklist.md` — D7 handoff list
- `study/phase-7-production-infra-plan.md` — Phase 7 design + decisions D1-D6
- `docs/runbook-corpus-refresh.md` — operator runbook for weekly cron PRs
- Memory `project-parser-bug-dedup` — triage guide for dedup_keep_last warnings
- Memory `feedback-paid-api-caution` — don't burn Voyage/Anthropic/Marítaca speculatively
- Memory `project-purpose-production` — project framing is production-level (2026-05-15+)
