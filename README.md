# rag-leis-digitais-br

RAG production-grade sobre direito digital brasileiro. Indexa **legislação
federal + jurisprudência STF/STJ** usando URN LEX (RFC 9676) como ID estável
de chunk. Hierarquia de chunking respeita LCP-95 (artigo → parágrafo → inciso
→ alínea → item) e o sistema **exige citação literal por URN** com verificação
em duas camadas, vigência sub judice flagada com ⚠️ na resposta, e redação
de PII (CPF/CNPJ/email/telefone/CEP/RG) **antes** de qualquer chamada a
provider US-hosted (LGPD compliance).

**Stack atual:** Voyage-3-large (embedding, `title+label+nav+caput+text`
mode), Marítaca Sabiá-3.1 (gerador production, BR-hosted), Anthropic
Claude Opus 4.7 (LLM-as-judge para eval). Pipeline com OOS gating em dois
níveis (cosine fast-path + LLM self-refusal), prose-vs-URN consistency
check com retry, hierarchy warning quando o gerador cita fonte de rank
inferior tendo superior em contexto, e footer de transparência
"Fontes consultadas em DD/MM/AAAA".

## Cobertura indexada (2026-05-17)

**Tier 1 — núcleo (13 docs, ~6500 chunks):** CF/88, CDC (8.078/1990),
CP (Decreto-Lei 2.848/1940), Lei do Software (9.609/1998), Lei de Direitos
Autorais (9.610/1998), LAI (12.527/2011), Lei Carolina Dieckmann
(12.737/2012), MCI (12.965/2014), Decreto 8.771/2016, Lei 9.507/1997
(habeas data), LGPD (13.709/2018), Lei 13.853/2019 (ANPD), Lei 14.155/2021
(crimes cibernéticos pós-Estelionato Eletrônico).

**Tier 2 — complementar (4 docs):** Lei 11.419/2006 (processo eletrônico),
Lei 14.063/2020 (assinaturas eletrônicas), Lei 14.129/2021 (Governo Digital),
**Código Civil arts. 11-21** (Direitos da Personalidade, escopo cirúrgico).

**Tier 3 — resoluções ANPD (2 ativos):** Res. CD/ANPD 15/2024 (Comunicação
de Incidente), Res. CD/ANPD 4/2023 (Dosimetria de Sanções). Phase 4.3.a
manual + 4.3.b pdfplumber backed.

**Tier 4 — jurisprudência STF/STJ (7 itens):** STJ Súmulas 227/403/479
(verbatim), STF Tema 786 (direito ao esquecimento, tese verbatim), Temas
987/533/815 (stubs descritivos com `status=pendente_*` — substituição
verbatim aguardando revisão D7).

**Total:** ~7200 chunks indexados via Voyage-3-large.

## Eval discipline

Dois eval sets distintos + 15 runs phase-tagged preservados em `eval/runs/`:

- **`eval/queries.yaml`** (104 queries) — retrieval-only. Gold gradeado
  (core/supporting). Métricas: nDCG@10, Recall@20, MRR@10, com breakdown
  por 5 tipos (definicao, enumeracao, citacao-literal, parafrase,
  cross-doc).
- **`eval/answer_queries.yaml`** (29 queries: 14 in-scope + 15 OOS) —
  end-to-end com LLM judge. Gold inclui `gold_urns`,
  `alternative_acceptable_urns`, `expected_paragraph`. OOS subtype
  taxonomy a-e (domínio outro / adjacente sem cobertura / PL não
  promulgado / estadual ou municipal / doutrina sem positivação).

**Métricas hoje:** nDCG@10 0.7235 / Recall@20 0.871 / MRR@10 0.7996
(Voyage, 104 queries, post-title-prefix + parser fixes 2026-05-16).

**Auditor's gold-standard analysis:** [`study/rag-eval-metrics-audit.md`](study/rag-eval-metrics-audit.md)
— mapeia as 17 métricas instrumentadas vs RAGAS/AIS/BEIR/SRE com
gap analysis ROI-ranked (top 5 gaps + LegalBench como external anchor
futuro).

## Production infra (Phase 7)

`.github/workflows/refresh-corpus.yml` roda semanalmente (domingos 02:00
UTC). Pipeline: fetch Planalto + diff SHA-256 (com F5 WAF strip) → se
mudança detectada: parse + pytest + Voyage re-embed + eval threshold gate
(nDCG@10 não pode cair > 0.02) → backup-then-restore se gate falha → PR
auto com diff summary + métricas before/after pra review humano.

`.github/workflows/smoke-test.yml` (workflow_dispatch) — 10 queries
canônicas através do pipeline Voyage + Sabiá. Custo ~$0.55/invocação.

Runbook: [`docs/runbook-corpus-refresh.md`](docs/runbook-corpus-refresh.md).

## Architecture decisions

Cada phase tem doc precedendo implementação:

- [`study/RETRIEVAL-JOURNEY.md`](study/RETRIEVAL-JOURNEY.md) — master doc:
  9 second-stage techniques (3 open rerankers + 2 commerciais + hybrid
  sparse RRF + ColBERT RRF + gated router) testadas e empiricamente
  refutadas. **Tese:** fix the data > second-stage tricks em corpus
  jurídico-pt-br denso.
- [`study/llm-provider-decision-2026-05-15.md`](study/llm-provider-decision-2026-05-15.md)
  — Marítaca Sabiá vs Anthropic Claude (3 runs cada): Sabiá ganhou
  faithfulness +0.15, citation precision +0.09. Plus LGPD residency.
  Decisão data-driven.
- [`study/lexml-urn-spec-resumo.md`](study/lexml-urn-spec-resumo.md) —
  URN LEX (RFC 9676) aplicado ao corpus brasileiro, incluindo §9.5 sobre
  jurisprudência (sumula.vinculante=rank 2, tema=rank 3, sumula simples
  =rank 5).
- [`study/phase-6-findings.md`](study/phase-6-findings.md) — jurisprudência
  Tier-4 v0 findings.
- [`study/phase-7-production-infra-plan.md`](study/phase-7-production-infra-plan.md)
  — Phase 7 design + 6 sub-phases.
- [`study/lawyer-review-checklist.md`](study/lawyer-review-checklist.md)
  — handoff doc para o D7 consultor jurídico (substituir 3 stubs de tema
  STF + validar curadoria + expandir whitelist).

Posts (drafts em `posts/`, gitignored): `01-fix-the-data-not-the-model`,
`02-stronger-reranker-worse-performance`, `03-hybrid-rrf-didnt-work`,
`04-title-prefix-broke-my-routing-intuition`.

## Run locally

```bash
git clone github.com/dlgiant/rag-leis-digitais-br
cd rag-leis-digitais-br
uv sync --extra voyage

# .env precisa de VOYAGE_API_KEY (obrigatório), MARITACA_API_KEY
# (recomendado), ANTHROPIC_API_KEY (opcional para judge eval)

# Fetch + parse o corpus (Planalto HTML, ~2 min, free):
uv run python -m rag_leis.fetch_tier --tier all
uv run python -m rag_leis.parse_all_tier --tier 1
uv run python -m rag_leis.parse_all_tier --tier 2
uv run python -m scripts.filter_cc_personalidade   # filtra CC arts.11-21

# Run retrieval eval (104 queries, ~$0.50 Voyage re-embed primeira vez):
uv run python -m rag_leis.run_eval --model voyage-3-large \
    --text-mode title+label+nav+caput+text --by-type

# Run answer-quality eval (29 queries, ~$0.50 LLM cost):
uv run python -m rag_leis.run_answer_eval

# Run weekly refresh orchestrator (no-op se nada mudou no Planalto):
uv run python -m scripts.refresh_corpus

# Run tests (skipping ANPD-PDF dependent tests; full suite needs PDFs):
uv run pytest -m "not requires_anpd_pdf"
```

## Project posture

Production-grade (não learning project). Production-grade signals:

- Cross-provider validation real (Anthropic + Marítaca medidos em produção)
- PII redaction antes de provider boundary (LGPD compliance)
- Cite-and-verify em duas camadas (URN ∈ corpus, URN ∈ top-K)
- Prose-vs-URN consistency check com retry (defesa contra LLM citar
  Art. X na prosa mas não no campo citations[])
- Hierarchy warning quando o gerador cita Decreto tendo a Lei-mãe em
  contexto
- Vigência overlay com ⚠️ literal trigger no system prompt
- Source-as-of-date footer "Fontes consultadas em DD/MM/AAAA"
- Audit log persistido (`data/audit/`)
- Weekly cron + diff + gate + rollback infra
- 347 tests (pytest)
- Refresh orchestrator com pytest gate + nDCG threshold + backup/restore

Out of scope até decisão de hosting (Phase 8):

- API/frontend deploy
- Latency / cost / throughput observability (Four Golden Signals — ver
  audit doc §4 gap #1)
- Sabiá rotation + rate limit handling

## License

TBD.
