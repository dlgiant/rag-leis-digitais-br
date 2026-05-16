# Phase 7 — Production Infra (scheduler + diff + scrapers)

**Status:** plan (não-implementado). 2026-05-16. Production framing.

Phase 7 entrega a infra que destrava Phase 6.3 (real scrapers STF/STJ) e
**fecha o loop de manutenção** do corpus — sem ela, o RAG silently fica
desatualizado conforme Brasil edita/revoga normas. É a transição de
"RAG funcional num snapshot" para "produto que se mantém vivo".

A diferença prática:
- **Hoje**: corpus é congelado no dia que rodei `fetch_tier`. Se EC 130
  alterar CF amanhã, o RAG continua respondendo com texto antigo —
  sem aviso.
- **Pós Phase 7**: scheduler roda semanalmente, fetcher diff'a SHA-256,
  alerta humano em mudanças, opcionalmente re-embeda e re-eval'a antes
  de promover.

## Decisões a travar antes de codar (D1-D6)

### D1 — Onde o scheduler roda?

| Opção | Setup | Custo | Pros | Cons |
|---|---|---|---|---|
| **GitHub Actions** | `.github/workflows/*.yml` + cron | gratuito até 2000 min/mês | versionado no repo; logs UI; cron nativo | precisa secrets pra Voyage; runner timeout 6h |
| Cron na VM | systemd-timer + script | custo de VM ($5-20/mês) | sem timeout; controle total | requer VM dedicada; logs externos |
| Cloudflare Workers Cron | `wrangler` + cron | gratuito até 100k req/dia | gratuito real | sem Python; precisa reescrever fetch_tier em JS |
| Não rodar (manual) | nada | zero | zero risco automático | derrota o propósito de Phase 7 |

**Recomendação:** GitHub Actions. Versionado, gratuito, Python suportado.
Tradeoff aceito: secrets em `repo secrets`, runner pode timeout em
re-embeds grandes (mitigável com job split).

### D2 — Cadência do scheduler

| Cadência | Para quem é demais | Para quem é pouco |
|---|---|---|
| Diário | Planalto raramente muda; desperdício | Não — Planalto sim publica leis/MPs ad-hoc |
| **Semanal** | Razoável pra leis federais | Pode atrasar publicações urgentes em até 7d |
| Mensal | Cobre tier-1 ok | ANPD/STF temas urgentes ficam invisíveis 30d |
| Sob demanda (push from RSS) | Ideal | Sem RSS oficial da Planalto |

**Recomendação:** semanal (domingo 02:00 UTC). Custo: ~5-10 min runner
por execução. Aceita lag máximo 7d, bem dentro da janela legal típica
(`vacatio legis` mínima é 45d para leis federais).

### D3 — O que acontece quando diff detectar mudança?

| Estratégia | Auto-promote? | Custo humano | Custo $ |
|---|---|---|---|
| **PR auto** com diff anexado | Não — humano revisa | ~5min/semana review | grátis |
| Issue auto + tag | Não | ~5min/semana | grátis |
| Slack/email alert | Não | dispara reação | grátis |
| Auto-merge se tests pass | Sim | zero (até quebrar) | $0.50/Voyage re-embed |
| Auto-merge + canary eval | Sim com gate | zero | $0.50 + tempo do test |

**Recomendação inicial:** PR auto + issue. Humano revisa o diff antes
de mergear. Razão: corpus é load-bearing pra production answers; um
diff malformado (parser regression silenciosa, vide §-suffix e
inc-suffix bugs recentes) pode envenenar respostas. Vale a fricção dos
~5min/semana de review. Auto-merge fica para Phase 8 quando tivermos
mais confiança nos gates.

### D4 — Re-embed automático ou manual?

Re-embed Voyage custa ~$0.50 por corpus completo. Triggers possíveis:
- (a) Sempre que qualquer chunk muda
- (b) Só quando humano aprovar diff PR
- (c) Threshold (>N chunks mudaram → auto; ≤N → defer)

**Recomendação:** (b). Re-embed dentro do PR auto, condicional a
aprovação humana. Pull request mostra: chunks mudados + diff de texto +
custo estimado + nova métrica eval prevista. Humano decide se merge.

### D5 — Prioridade dos scrapers 6.3 dentro de 7

Dois alvos no plan Phase 6:
- **STJ Súmulas** (`scon.stj.jus.br`) — HTML estável, ~1d eng
- **STF Temas** (`portal.stf.jus.br`) — SPA JS-heavy, ~3-5d eng

Os 7 chunks Tier-4 atuais são curados; scrapers só fazem sentido se
houver whitelist do D7 para expansão (sem isso, scraping é noise).

**Recomendação:** scrapers ficam **gated em D7 explicitamente**, fora
do escopo Phase 7. Phase 7 entrega INFRA (scheduler + diff +
notification) que receberia esses scrapers quando existirem. Foco em
tier-1/2 que JÁ existem e precisam de manutenção.

### D6 — Hosting do RAG em produção (in/out de Phase 7?)

O RAG hoje roda local. Para uso real precisa:
- API endpoint (FastAPI?)
- Frontend (CLI? web?)
- LLM key management (rotation, rate limit)
- Observability (latência, custo por query, refusal rate)

**Recomendação:** **OUT** de Phase 7. Phase 7 = manutenção do CORPUS,
não deploy do RAG. Hosting é Phase 8 distinta. Manter escopo apertado.

## Sub-fases

### 7.0 — Plan + decisões D1-D6 (este doc) [meio-dia]

### 7.1 — Diff detection + audit log (~1d)

- Estender `fetch_tier.py` para computar SHA-256 do HTML pós-fetch
- Persistir SHA-256 em `data/metadata/<tier>/<urn>.json` (`html.sha256`)
- Detectar mudança: nova fetch vs último SHA-256 → flag
- Audit log: `data/audit/corpus_updates.jsonl` com `{date, urn, old_sha, new_sha, byte_delta}`
- Saída: relatório de "que mudou desde a última fetch"

### 7.2 — Re-parse e re-embed gates (~1d)

- Pipeline post-diff: se chunk_text muda → re-embed obrigatório
- Pre-flight checks: `pytest` deve passar antes de re-embed
- Eval threshold: nDCG@10 não pode cair > 0.02 pós-re-embed (gate)
- Rollback: se eval cair, restaurar `data/index/*.npz` do backup

### 7.3 — GitHub Actions scheduler (~½d)

- `.github/workflows/refresh-corpus.yml`
  - `schedule: cron: '0 2 * * 0'` (domingo 02:00 UTC)
  - steps: fetch all tiers → detect diff → if change: parse + re-embed + eval
  - on success: open PR with diff body + metric report
  - on failure: open issue tagged `corpus-update-failed`

### 7.4 — Notification + PR template (~½d)

- PR body template: lista de URNs mudados, byte-delta, eval before/after
- Markdown table com proposta de approve/reject
- Pre-merge auto-comment do bot com gates passed

### 7.5 — Smoke test post-merge (~½d)

- GitHub Action on `push` to main
- Roda `pytest` + um query suite de 10 queries canônicas via Sabiá
- Se quebrar, abre issue `production-degradation`
- Custo: ~$0.10 por push (Sabiá é barato)

### 7.6 — Documentação operacional (~½d)

- `docs/runbook-corpus-refresh.md` para humano que recebe PR
- Como ler diff, quando aprovar, quando rejeitar
- Como reverter se algo der errado

**Total Phase 7 (sem scrapers 6.3):** ~3-4 dias com Claude Code
multiplier; ~5-7 dias sem. Implementação iterativa, cada sub-phase
fecha um loop testável.

## Decisões já travadas (de fora do Phase 7)

- **Scrapers STF/STJ** ficam para Phase 7+ (após D7 lawyer fornecer
  whitelist canônica)
- **Hosting do RAG** é Phase 8 distinta — out of Phase 7 escopo
- **D7 lawyer engagement** continua bloqueante para expansão de
  jurisprudência (não para Phase 7 infra em si)

## Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Planalto muda HTML structure → parser quebra silenciosamente | Média | Smoke test + chunk count delta alert |
| Voyage API outage durante scheduled run | Baixa | Retry com backoff; falha → issue, não merge |
| Re-embed escalando custo | Baixa | Re-embed só on chunk_text change (não nav-only) |
| Human review burnout (~5min/semana) | Média | Auto-merge candidato em Phase 8 |
| GitHub Actions runner timeout 6h | Baixa | Split em multi-job se >30min |

## Critério de "Phase 7 done"

1. Scheduler roda automaticamente semanalmente
2. Mudança em qualquer doc Tier-1/2/3 dispara PR auto
3. PR contém eval before/after + chunk diff legível
4. Suite + eval threshold são gates duros (não merge se quebrar)
5. Runbook humano-legível existe
6. Rollback testado (intencionalmente quebrar; rollback funciona)
7. ~1 mês de operação sem intervenção manual além dos PRs semanais

## Out of scope explícito

- Scrapers STF/STJ (Phase 7+, gated D7)
- API/frontend (Phase 8)
- LLM rotation/observability (Phase 8)
- Multi-region/HA (Phase 9?)
- Versionamento de corpus (`@<data>` LexML) — pode entrar Phase 7 se
  o diff infra suportar, mas começa fora

## Próximo passo imediato

User confirma D1-D6 (especialmente D1 GitHub Actions, D2 semanal, D3 PR
auto, D5 scrapers out, D6 hosting out). Confirmados → começa 7.1 (diff
detection + audit log) em branch dedicada.
