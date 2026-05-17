# Backlog

Itens identificados mas não-aplicados — pra retomar quando for prioridade.

## 📌 State snapshot (2026-05-17)

**Phases completed:**
- ✅ Phase 0 (parser foundations, dedup logging, cache)
- ✅ Phase 1 (TIER_1+TIER_2 corpus)
- ✅ Phase 2 (RAGPipeline + cite-and-verify + answer-eval v0)
- ✅ Phase 3 (vigência overlay + Lei 9.507 + Decreto cross-test)
- ✅ Phase 4 (LLM provider abstraction; Sabiá-3.1 vs Sonnet-4-5 cross-validation; PII redactor; query-type classifier; ANPD pdfplumber parser; Tier-3)
- ✅ Phase 5 (legal_rank + hierarchy_warning; prose-citation check + retry; source-as-of-date; EC linkage; OOS subtype taxonomy a-e)
- ✅ Phase 6 (Tier-4 jurisprudência v0: 7 chunks; URN spec §9.5)
- ✅ Phase 7 (production infra: SHA-256 diff + F5 WAF strip + parser §-suffix/inc-suffix fixes + title-prefix default + orchestrator with gate+rollback + GitHub Actions weekly cron + smoke + runbook)

**Phases pending (large blocks):**
- ⏸ Phase 8 — hosting/API/observability (need SRE Golden Signals from audit doc §4 gap #1 before)
- ⏸ Phase 9 — compliance / lawyer review (depends on D7 contracting)

**Corpus current:** ~7200 chunks across 4 tiers (13 Tier-1 + 4 Tier-2 + 2 Tier-3 + 7 Tier-4).

**Eval current:** 104 retrieval queries + 29 answer queries (14 inscope + 15 OOS) + 16 concurso pilot (7 inscope + 9 OOS). Production metrics: nDCG@10=0.7235, MRR@10=0.7996, internal refusal_accuracy=0.938, external (concurso pilot) refusal_accuracy=**0.625** — the divergence motivates the query expansion below.

**Gold-standard metrics audit** (full at `study/rag-eval-metrics-audit.md`):
- 17 ✅ Covered metrics across retrieval IR / RAGAS Faithfulness / AIS citation / OOS refusal / hierarchy+vigência / LGPD compliance / prose-citation check
- 9 🟡 Partial (context precision proxied, false-refusal computable but not surfaced, etc.)
- 13 ❌ Missing (mostly SRE Golden Signals: latency p50/p95/p99, cost/q, error rate, throughput; plus RAGAS Answer Relevance and claim-level Context Recall)
- Top 5 ROI-ranked gaps: (1) SRE Golden Signals ~1d → required for Phase 8; (2) cost-per-query ~2h; (3) false_refusal_rate ~30min; (4) RAGAS Answer Relevance ~1d; (5) **superseded by query expansion plan below**.

---

## 🎯 Query expansion (post-pilot, post-audit)

**Full plan:** [`study/query-expansion-plan.md`](study/query-expansion-plan.md).

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

## OOS hardening (NEW — exposed by concurso pilot, 2026-05-17)

- 🚨 **OOS-B refusal 0/2 in concurso pilot** — ECA + Código Ética OAB queries over-answered using LGPD/MCI tangential context. SYSTEM_PROMPT subtype "d" (normas não-indexadas adjacentes) not firing. Phase 5.1b-style prompt iteration warranted using expanded OOS set from query expansion sub-phase A as adversarial training.
- 🚨 **OOS-A refusal 43%** in concurso pilot vs 100% expected. Tax/labour-procedure queries pass cosine fast-path and LLM judges context applicable. Investigation needed: was the cosine top-1 above 0.40? If yes, threshold too lenient OR context retrieval too broad.
- ⏸ **OOS-C category** (intentionally tricky CRIMINAL questions deceptively close to crimes cibernéticos) — propose adding via curated subset of CRIMINAL questions from `eduagarcia/oab_exams` and/or `legalbench.br`.

## Production observability (NEW — from gold-standard audit, 2026-05-17)

Full audit at `study/rag-eval-metrics-audit.md`. Top 4 implementable ROI gaps:

- ⏸ **SRE Four Golden Signals** (~1d eng) — latency p50/p95/p99, traffic QPS, error rate per provider, saturation. **Required for Phase 8 hosting** (audit doc §4 gap #1). Add `latency_ms` + `latency_breakdown` + `tokens_used` to `RAGAnswer` dataclass + module-level `rag_leis.metrics` counters.
- ⏸ **Cost-per-query tracker** (~2h) — `rag_leis/cost.py` pricing table + `RAGAnswer.cost_estimate_usd` + `Aggregate.cost_mean_usd`. Promotes docstring estimates to first-class signal.
- ⏸ **False refusal rate as first-class metric** (~30 min) — extract from existing `refusal_accuracy` mean; split into `false_refusal_rate` (in-scope refused / in-scope) + `oos_refusal_recall` (OOS refused / OOS) for honest refusal confusion matrix.
- ⏸ **RAGAS Answer Relevance** (~1d, ~$0.10/run) — separate LLM-judge call: reverse-question method (Es et al. 2023, arxiv 2309.15217). Distinct from Faithfulness; catches "faithful but evasive" answer mode.

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
