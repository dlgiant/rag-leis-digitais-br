# Post-Review Plan — Production-Level Roadmap

**Status**: design (não-implementado). 2026-05-15. **Production framing
ativada nesta data** — cada decisão sob lente de reproducibilidade,
compliance, audit trail, multi-dev handover, automação.

Reviewer round 2 (legal-domain) flagged 12 items. Phase 3 (P0)
está fechada em `main`. Este plan agora estende para Phase 4-9 sob
production lens, não learning lens.

A diferença não é cosmética: cada "good enough" do learning project
vira "documentado como dívida técnica + plan pra fechar" no production.
Ver [[project-purpose-production]] em memory.

## Princípios production que mudaram desde v1 deste plan

1. **Builds 100% reproducíveis** — sem manual steps no caminho de CI/CD
2. **Audit trail jurídico** — toda peça (chunk, prompt, gold) tem source + version
3. **Cadência de update automatizada** — ANPD/STF publicam → ingestão sem humano
4. **Multi-dev / handover** — workflows que exigem "Claude Code in the loop" são dívida
5. **Compliance LGPD do próprio sistema** — query logs, retention, DPA, residency
6. **Test discipline maior** — golden tests por documento, não smoke; CI integration tests
7. **Operational readiness** — Docker, monitoring, rate limiting, fallback model, retry/backoff

## Mapping atualizado — reviewer item → phase → sizing (production)

Sizing entre parêntesis = `(learning estimate → production estimate)`.

| # | Reviewer item | Phase | Pri | Size (learn → prod) | Mudança |
|---|---|---|---|---|---|
| 1 | Vigência overlay | **3 ✓** | P0 | (1d → 1d) | done |
| 2 | ANPD resoluções (Tier-3 PDF parser) | 4 | P1 | (1wk → **2wk**) | + golden tests por resolução, + audit metadata |
| 3 | Normative hierarchy (`legal_rank`) | 5 | P2 | (2h → 4h) | + tests + integration com retriever |
| 4 | Cross-doc undersized (8 → ≥30) | 5 | P2 | (1d → **3-5d**) | curadoria por advogado, não eu |
| 5 | Citation precision tier 3 | 5 | P2 | (1d → **5-7d**) | validação jurídica humana, não auto |
| 6 | Human-citation regex check | 5 | P2 | (2h → 1d) | + reject-and-reprompt loop + tests adversariais |
| 7 | Source-as-of-date | 5 | P2 | (3h → 1d) | + audit log + per-chunk version, não só per-doc |
| 8 | Input PII redactor | 4 | P1 | (2h → **2-3d**) | regex + NER pt-BR + comprehensive tests + adversariais |
| 9 | OOS taxonomy (3 → ≥15) | 5 | P2 | (½d → **3d**) | ≥50 rows, adversarial, validados |
| 10 | Query-type classifier + adaptive top_k | 4 | P1 | (½d → 1d) | + observability hooks |
| 11 | ADCT + EC linkage (`amended_by`) | 5 | P2 | (½d → 1d) | + golden tests + versioning |
| 12a | Add Lei 9.507/97 | **3 ✓** | P0 | (1h → 1h) | done |
| 12b | Decreto 8.771 cross-test query | 5 | P2 | (30m → 30m) | trivial |
| 12c | Update README declared scope | **3 ✓** | P0 | (5m → 5m) | done |
| (4) | STF/STJ jurisprudência (Tier-4) | 6 | P3 | (2wk → **4-6wk**) | scraper + scheduler + parser + audit |

## Novas phases — production-only

| Phase | Scope | Sizing |
|---|---|---|
| **7** | Production infra (Docker, CI/CD, monitoring, rate limiting, model fallback) | ~2 sem |
| **8** | Operations (deploy, runbooks, on-call, rollback, DR) | ~1-2 sem |
| **9** | Compliance (DPA Anthropic, retenção logs LGPD, security review, ToS) | ~2-3 sem + custos legais |

Total roadmap atualizado: **~3-4 meses** de trabalho até v1 production
(antes: ~3-5 semanas pra learning demo).

## Phase 4 — practitioner-grade infra (~3-4 sem production)

**Goal mudou**: de "TCC para ferramenta supervisionada" para "componente
deployável com observability e PII compliance interna".

### 4.1 Query-type classifier + adaptive top_k (~1d)

Mesmo design técnico do v1. Mudanças production:

- **Observability obrigatória**: cada query loga `{query_type, top_k_used,
  retrieve_latency_ms, llm_latency_ms, total_tokens_in, total_tokens_out}`
- **Métrica nova**: `classification_accuracy` mensurada contra eval set
  (se classificar errado, top_k errado, eval reflete)
- **Fallback**: se classifier não bate confiança mínima, usar default
  conservador (top_k=15)

### 4.2 Input PII redactor (~2-3d, era 2h)

Production framing aumenta MUITO o escopo:

- **Regex base** (CPF, CNPJ, email, phone, RG, CEP) — 2h, igual antes
- **NER pt-BR** pra nomes próprios — adiciona spaCy `pt_core_news_md` ou
  HF model. ~1d integrating + benchmarking precisão
- **Testes adversariais**: queries com edge cases (CPF formatado vs sem
  formato, nomes pouco comuns, endereços, datas que parecem documentos).
  ~½d
- **Audit log**: cada redação registra `{original_hash, redacted_text,
  pii_types_found}` em log local (não no Anthropic). LGPD requirement.
- **Reverse mapping** durável (não só in-memory) pra reinjetar no answer
  se UI quiser. Cache + TTL.
- **Test coverage**: ≥85% das categorias de PII LGPD (art.5 II) listadas
  com pelo menos 1 caso positivo + 1 falso-positivo controlado.

### 4.3 ANPD Tier-3 — híbrido production-acceptable (~3-4d agora + 1 sem depois)

**Decision**: híbrido (Claude-Code-assisted ingestion now → real parser
antes de production deploy). Não é dívida silenciosa — é roadmap.

Stages:

**4.3.a (now, ~3-4d): manual ingestion com discipline production**
- Eu leio cada PDF da ANPD (Res. 1/2021, 2/2022, 4/2023, 15/2024) via Read tool
- Estruturo em LCP-95 (artigo → § → inciso → alínea), respeitando capítulos
- Escrevo JSONL diretamente em `data/chunks/tier-3/<file>.jsonl`
- **Cada chunk carrega metadata**:
  ```json
  {
    "urn": "...",
    "text": "...",
    "source": "claude-code-2026-05-15",
    "source_pdf_sha256": "<hash>",
    "ingestion_method": "manual-transcription-v0",
    "ingestion_provenance": "Read tool, single Claude session"
  }
  ```
- **Stub `rag_leis/parsers/anpd_pdf.py`** implementa `Parser` protocol
  mas internamente apenas re-lê o JSONL produzido. Wiring `corpus.py` +
  `parse_all_tier --tier 3` funciona end-to-end.
- **URN scheme** documentado em `study/lexml-urn-spec-resumo.md`:
  `urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:<date>;<num>`
- **Smoke tests**: 1 golden test por resolução (4 total) checando que
  artigos críticos foram capturados (ex: prazo 3 dias úteis na Res. 15/2024)
- **Eval gold NÃO inclui chunks ANPD ainda** — preserva o eval anchored
  no parser canônico, evita "eval rewards what I wrote"

**4.3.b (production gating, ~1 sem): parser real**
- Implementar `AnpdPdfParser` real (pdfplumber + heurísticas pra ANPD layout)
- Run `parse_all_tier --tier 3 --rebuild` → produz NOVO JSONL
- **DIFF script** (`rag_leis/scripts/diff_parsed_vs_manual.py`) compara
  v0 (manual) vs v1 (parser). Cada diff é bug em uma das duas pontas.
- Golden tests por resolução em `tests/test_parser_anpd.py`
- `source` field flipa para `pdfplumber-v1`, `ingestion_method` para `automated`
- **GATE**: 4.3.b é hard requirement antes de Phase 8 production deploy.
  Documentado em ROADMAP.md (a ser criado em Phase 7).

### Phase 4 entregáveis (production)

- 5 novos módulos (`query_type.py`, `pii.py`, `parsers/anpd_pdf.py`, etc.)
- 1 nova dependência prod (spaCy pt) + 1 dev (pdfplumber)
- ~50-100 chunks ANPD indexados
- ~15-20 testes novos (incluindo adversariais PII + 4 goldens ANPD)
- Re-run answer-eval com 5-8 queries operacionais ANPD novas
- Re-eval cost: ~$5-10 (production observability adds tokens)
- README atualizado com Phase 4 deliverables + Phase 4.3.b gating note

## Phase 5 — robustez production (~2-3 sem)

Cada item do v1 cresceu sob production lens.

### 5.1 OOS taxonomy + 3 → ≥50 expansion (~3d, era ½d)

- 5 subtypes (a-e) — schema preservado
- **Mas**: ≥50 rows totais, ≥10 por subtype, com adversarial cases
  (queries que parecem in-scope mas não são; queries que parecem OOS mas têm answer parcial)
- Validação cruzada: 2-3 OOS rows revisados por advogado consultor

### 5.2 `legal_rank` + tie-breaker (~4h, era 2h)

- Auto-derive da URN type — igual antes
- **Production add**: `RAGAnswer.hierarchy_warning: str | None` quando
  resposta cita rank≥4 enquanto rank≤3 estava no top-K. Renderizado no answer.
- Integration test: query que retrieva CF + Decreto verifica que CF wins tie

### 5.3 Human-citation regex check (~1d, era 2h)

- Extração regex igual ao v1
- **Production add**: reject-and-reprompt loop (não só flag). Se mismatch,
  re-chama LLM com instrução "você citou Art. X, Y mas o URN é Z; corrija."
- Max 1 retry, depois aceita com flag explícita
- Adversarial tests: queries que tendem a soltar Art. errado (cross-doc
  com numeração compartilhada, ex: art. 5 da CF vs art. 5 da LGPD)

### 5.4 Cross-doc expansion 8 → ≥30 (~3-5d, era 1d)

- Curadoria precisa **validação jurídica externa**. Não posso curar 22
  novas cross-doc rows sozinho com production rigor.
- **Decision pendente** (ver "Open decisions" abaixo): advogado consultor?
  Externalizar pra firma? Crowdsource via reviewer?

### 5.5 Source-as-of-date (~1d, era 3h)

- `fetched_at` per doc — igual v1
- **Production add**: `chunk_version` per chunk (hash do texto na ingestão).
  Permite "este chunk mudou desde quando? quando o usuário leu, qual versão?"
- Audit log no Postgres/SQLite local: cada answer registra `{query, answer,
  citations, sources_consulted_at, chunk_versions, anthropic_model_version,
  prompt_version_hash}`
- Footer no answer: "Fontes: LGPD (consultada em 2026-05-15, versão chunk
  hash a3f...); Marco Civil (...); ..."

### 5.6 3rd precision tier ("juiz aceitaria") (~5-7d, era ½d)

- **Production-blocking**: precisa validação jurídica humana, não eu
- Mesma decisão pendente do 5.4

### 5.7 ADCT + EC linkage (~1d, era ½d)

- Parser change pra capturar `(Redação dada pela EC X)` — igual v1
- **Production add**: golden test por amend (CF art. 5 LXXIX → EC 115/2022,
  art. 5 § 3 → EC 45/2004, etc.). Cada chunk constitucional com EC anotada
  precisa teste positivo.

### 5.8 Decreto 8.771 cross-test query (~30m)

Trivial, não muda.

## Phase 6 — pesquisa-jurídica completa (~4-6 sem production)

### 6.1 STF/STJ jurisprudência Tier-4 (~4-6 sem, era 2 sem)

Production lens dobra/triplica:
- Scraper STF + STJ (não há API estável; HTML scraping com tolerância)
- Scheduler (cron job ou Cloud Scheduler) pra pickup de novos súmulas/temas
- URN scheme + parser por tipo de fonte
- Audit pipeline (jurisprudência tem alta cadência de update; precisa monitoring)

### 6.2 Lei 12.414/2011, Decreto 10.474/2020 (~1d cada)

Iguais ao v1. Triviais.

## Phase 7 — Production infra (NOVA, ~2 sem)

Pré-requisito pra deploy.

### 7.1 Containerization (~3d)

- `Dockerfile` multi-stage (build voyage cache em build time? Ou volume mount?)
- `docker-compose.yml` pra dev local
- Health-check endpoint
- Read-only filesystem onde possível (chunks, index)

### 7.2 CI/CD GitHub Actions (~3d)

- Workflow: PR → lint + tests + golden eval (sem network) + parser tests
- Workflow: push to main → build image + push registry
- Tag-based release workflow
- **Eval gate**: PR não merged se faithfulness mean drops > X%
- Live integration test (network-marked) roda nightly em staging, não por PR

### 7.3 Observability (~3d)

- Structured logs (JSON) por query
- Metrics (Prometheus-compatible): per-query cost, latency p50/p95, error rate
- Trace (OpenTelemetry?): retrieve → LLM → verify spans
- Dashboard (Grafana? Datadog?) com alertas

### 7.4 Resiliência LLM (~3d)

- Retry com exponential backoff (Anthropic 429s)
- Model fallback: sonnet 429 → haiku (com flag `degraded=True` no answer)
- Circuit breaker se Anthropic down > N min
- Token budget cap per query

### 7.5 Rate limiting (~2d)

- Per-IP / per-user rate limit (nginx ou app-level)
- Cost cap diário/mensal (parar antes de explodir)

## Phase 8 — Operations (NOVA, ~1-2 sem)

### 8.1 Deploy strategy (~3d)

- Decision: Cloud Run (GCP), Lambda (AWS), bare ECS, ou self-hosted (Hetzner/Render)?
- Region: Brazil (data residency LGPD-friendly)?
- Setup environment: dev / staging / prod

### 8.2 Runbooks (~2d)

- "ANPD published new resolução": passo-a-passo de ingestão
- "STF emitiu nova súmula": passo-a-passo
- "Anthropic API down": fallback procedures
- "Eval regression in production": rollback procedure
- "PII redactor missed something": incident response

### 8.3 On-call setup (~1d)

- Pager (PagerDuty? OpsGenie?)
- Alert thresholds
- Initial responder = solo dev; plan pra escalar

### 8.4 Disaster recovery (~2d)

- Index backup (S3? Blob storage?)
- Chunks versioned em git (já é o caso — confirmar)
- Restore drill: rebuild from scratch in < 30 min

## Phase 9 — Compliance (NOVA, ~2-3 sem + custos legais)

### 9.1 DPA com Anthropic (~3-5d incluindo lawyer review)

- Negotiate Data Processing Agreement
- Confirm data retention de Anthropic side (zero-retention possível?)
- Document for ANPD audit purposes

### 9.2 Query log retention (~2d)

- Política: queries armazenadas N dias, depois aggregated/deleted
- LGPD compliance (queries podem conter dados pessoais mesmo com PII redactor)
- Right-to-deletion endpoint

### 9.3 ToS / Privacy Policy (~3d, lawyer-drafted)

- ToS específico do serviço (não é genérico SaaS — RAG jurídico tem responsabilidades específicas)
- Privacy Policy LGPD-compliant
- Disclaimer: "ferramenta auxiliar, não substitui parecer humano"

### 9.4 Security review (~5-7d, externalized?)

- Pentesting (OWASP top 10)
- Dependency scanning (Snyk, GitHub Dependabot)
- Secrets management review (não tem secrets no repo já — confirmar)
- API auth strategy (mTLS? OAuth? simple bearer?)

### 9.5 Data residency (~2d)

- Brazilian users → answer tokens não saem do BR? Anthropic não tem region BR ainda
- Mitigation: documentar isso em ToS, dar opção de opt-out

## Cronograma agregado (production)

| Phase | Foco | Wall clock |
|---|---|---|
| 4 | Practitioner-grade (classifier + PII + ANPD híbrido) | ~3-4 sem |
| 5 | Robustez (OOS, hierarchy, prose check, cross-doc, etc.) | ~2-3 sem |
| 6 | Jurisprudência (STF/STJ Tier-4) | ~4-6 sem |
| 7 | Production infra | ~2 sem |
| 8 | Operations | ~1-2 sem |
| 9 | Compliance | ~2-3 sem |
| **Total v1 production** | | **~3-4 meses** |

## Decisões pendentes — production lens

| # | Decisão | Default learning | Default production |
|---|---|---|---|
| D1 | Quem cura legal-domain (vigência overlay v2, cross-doc, 3rd precision tier)? | eu rascunho, user revisa | **advogado consultor pago** ou parceria com firma |
| D2 | `flagged_vigencia` bloqueia ou anota? | anota | anota + audit log |
| D3 | Phase 4.3 path — manual now / parser later? | manual ok | **híbrido com gating em 4.3.b** (ver acima) |
| D4 | Lei 9.507 → Tier-1? | Tier-1 (done) | done |
| D5 | Phase 4 ordem? | curtos primeiro | curtos primeiro (mantém) |
| **D6 NEW** | Quando é production launch? | (n/a) | **precisa data clara pra gating de Phase 4.3.b/9.x** |
| **D7 NEW** | Compliance budget? Lawyer disponível? | (n/a) | **precisa SIM/NÃO antes de Phase 9** |
| **D8 NEW** | Multi-tenancy ou single-tenant production? | (n/a) | impacta Phase 7 (auth, rate limit) e Phase 8 (deploy) |
| **D9 NEW** | Brazilian region requirement? | (n/a) | impacta Phase 8 deploy + Phase 9 ToS |
| **D10 NEW** | SLA target (uptime, latency)? | (n/a) | impacta Phase 7 (resiliência) e Phase 8 (on-call) |

D6-D10 são pré-requisitos de planejamento real. **Recomendação: scoping
conversation** antes de começar Phase 7+ pra travar essas variáveis.

## O que do v1 deste plan continua válido sem mudança

- Princípio "fix the data, not the model" continua sendo a mola da Phase 5
- Faithfulness (LLM-as-judge) continua sendo a métrica anchor
- 4 phases originais (3, 4, 5, 6) preservadas — mudanças são internas (sizing + escopo)
- Reviewer round 2 não fica obsoleto — adiciona-se Phase 7-9 ao invés de re-arquivar

## O que do v1 está **obsoleto**

- "Aceitar gold estreito + acrescentar `alternative_acceptable_urns` v0" como solução final → production precisa do 3rd tier "judicial acceptable" hand-curated por advogado
- Eval set de 16 rows v0 como "small but useful" → production blocking ≥100 rows curados
- "Phase 2.8 write-up substitui doc formal de design" → production precisa changelog formal por release; posts/findings é suplementar
- "Posts no posts/ gitignored" → talvez review se vão pra blog/docs.example.com production
- Library de prompts (SYSTEM_PROMPT inline em código) → production prefere prompts versionados em arquivos separados com hash em audit log

## Primeira ação operacional

Antes de começar Phase 4 efetivamente, recomendo:

1. **Travar D6-D10** (scoping conversation, ~1h)
2. **Criar `ROADMAP.md`** com gates explícitos (production date, 4.3.b parser deadline, etc.)
3. **Atualizar CLAUDE.md** removendo "treat as learning project" — substitui por "production-track project com fases learning passadas"
4. **Decidir D1**: advogado consultor disponível? Se não, certas tasks de Phase 5 (cross-doc curation, 3rd precision tier, OOS validation) ficam blocked

Sem D1 resolvido, posso entregar Phase 4 inteira mas algumas Phase 5 items
ficam pendurados.
