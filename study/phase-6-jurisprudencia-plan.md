# Phase 6 — Jurisprudência Tier-4 (STF/STJ)

**Status**: design (não-implementado). 2026-05-15. Production framing.

Reviewer round 2 item 4 + post-review-plan Phase 6: jurisprudência
vinculante + temas de repercussão geral. Sem isso, o RAG entrega "letra
fria da lei" — incompleto pra qualquer prática jurídica séria.

A diferença prática:
- Hoje, query "direito ao esquecimento na internet" → modelo refusa
  (subtype `e` doutrina) ou acha LGPD art. 18 IV (eliminação) e
  responde com aviso "não é direito ao esquecimento como princípio".
- Com Tier-4: query encontra **STF Tema 786** (rejeitado em 2021 como
  princípio autônomo) + LGPD art. 18 IV. Resposta autoritativa com
  status atual.

## Decisões já travadas (Phase 5.1 cross-validation reuse)

- **URN scheme** será sintético, registrado em `study/lexml-urn-spec-resumo.md`.
  LexML resolver não cobre toda jurisprudência (já confirmado).
- **Hybrid ingestion path** (Phase 4.3.a/b padrão): manual JSONL com
  audit metadata source="claude-code-*" → parser real depois.
- **Generator stays Sabiá-3.1** (D9). Phase 6 não muda.
- **Cross-provider validation** vai rodar pra cada eval iteração.

## Escopo MVP (~3-4 semanas production)

### Items canônicos a indexar

**STJ Súmulas** (~3 chunks):
- Súmula 227 — "A pessoa jurídica pode sofrer dano moral"
- Súmula 403 — "Independe de prova do prejuízo a indenização pela
  publicação não autorizada da imagem de pessoa"
- Súmula 479 — "As instituições financeiras respondem objetivamente
  pelos danos gerados por fortuito interno relativo a fraudes e
  delitos praticados por terceiros no âmbito de operações bancárias"

**STF Temas com repercussão geral** (~4 itens, 1-3 chunks cada):
- Tema 786 — Direito ao esquecimento (REJEITADO em 11/02/2021)
  - Tese: "É incompatível com a Constituição a ideia de um direito ao
    esquecimento..."
- Tema 987 — Constitucionalidade do art. 19 do MCI (PENDENTE,
  julgamento iniciado)
- Tema 815 — Bloqueio judicial de aplicações de internet por
  descumprimento de ordem (decisões parciais)
- Tema 533 — Sigilo bancário e Receita Federal (já cobrado em
  decisões anteriores, relevante pra Marco Civil)

**Total chunks v0**: ~10-15. Pequeno mas meaningful — fecha o gap
mais visível (Tema 786 + Tema 987).

### Scope ABERTO até decisão D7 (advogado consultor)

- Quais OUTRAS súmulas/temas são canônicos pra direito digital BR?
  (lawyer-review-checklist.md item 5 já registra essa pergunta)
- Acórdãos individuais relevantes (ex: caso Daniella Cicarelli pre-Tema 786)
- Informativos STF/STJ — alta cadência (semanais), defer pra v2

## URN scheme proposto

Estende `study/lexml-urn-spec-resumo.md`:

```
# Súmulas
urn:lex:br:superior.tribunal.justica:sumula:1985-04-25;227
urn:lex:br:supremo.tribunal.federal:sumula:1969-12-03;473
urn:lex:br:supremo.tribunal.federal:sumula.vinculante:2008-08-13;11

# Temas de repercussão geral
urn:lex:br:supremo.tribunal.federal:tema:786
urn:lex:br:supremo.tribunal.federal:tema:987

# Partition para temas (chunk dentro do tema):
urn:lex:br:supremo.tribunal.federal:tema:786~tese
urn:lex:br:supremo.tribunal.federal:tema:786~ementa
urn:lex:br:supremo.tribunal.federal:tema:786~processo
```

**Caveats**:
- LexML resolver retorna 404 nessas (mesmo problema do ANPD); fallback
  documentado: link pra portal.stf.jus.br ou stj.jus.br
- Súmulas têm data de aprovação no formato DOU; usamos como o `<date>`
- Temas têm número sequencial sem data; usar `;<num>` direto sem date
  (divergência da convenção LexML padrão — documentar)

## Sub-fases

### 6.0 — URN scheme + chunk schema (½ d)

Decisões:
- `Chunk.kind = "jurisprudencia"` adicionado a `ChunkKind` Literal
- `IndexChunk.legal_rank` recebe rank pra súmulas:
  - Súmula vinculante (CF art. 103-A): rank 2 (efeito vinculante geral)
  - Súmula simples (orientativa): rank 5 (infralegal)
  - Tema com tese de repercussão geral: rank 3 (vinculação difusa,
    proximidade da lei)
  - Tema pendente (sem tese fixada): rank 5 (orientação preliminar)
- LEGAL_RANK_BY_TYPE update (rag_leis/legal_rank.py)
- Documentação em study/lexml-urn-spec-resumo.md

### 6.1 — Manual ingestion v0 (~2 d)

Padrão Phase 4.3.a: Claude Code lê fontes web + escreve JSONL com
audit metadata.

- 3 súmulas STJ + 4 temas STF = ~10-15 chunks
- Source URLs salvos em metadata
- Build script `rag_leis/tier4_ingest/build_*.py` por item
- Schema:
  ```json
  {
    "document_urn": "urn:lex:br:supremo.tribunal.federal:tema:786",
    "partition": "tese",
    "kind": "jurisprudencia",
    "label": "Tese (Tema 786)",
    "text": "É incompatível com a Constituição a ideia de um direito ao esquecimento...",
    "parent_partition": null,
    "nav": {
      "tribunal": "STF",
      "tipo": "Tema de Repercussão Geral",
      "numero": "786",
      "status": "julgado",
      "data_julgamento": "2021-02-11"
    },
    "notes": ["RE 1010606", "Relator Min. Dias Toffoli"],
    "is_revoked": false,
    "source": "claude-code-2026-05-XX",
    "source_url": "https://portal.stf.jus.br/...",
    "ingestion_method": "manual-transcription-v0"
  }
  ```

### 6.2 — Stub Parser (½ d)

Mirror do `AnpdPdfParser` pattern: `JurisprudenciaParser` com
`Parser` protocol. Stub re-lê JSONL produzido pelo build script.
Wire em `corpus.py` `TIER_4`.

### 6.3 — Scrapers reais (~5-7 d, gated em D6/D8)

Production scope. Scrapers pra STJ + STF:

- STJ Súmulas: `stj.jus.br/sites/portalp/Inicio/Jurisprudencia/Sumulas` —
  HTML estável, parseable com BeautifulSoup
- STF Temas: `portal.stf.jus.br/jurisprudenciaRepercussao/...` —
  JavaScript-heavy, pode precisar Playwright/Selenium
- Diff detection vs JSONL existente
- Cron job (Phase 7 production infra)

**Gated**: real scrapers ficam pra Phase 6.3.b, similar ao 4.3.b
gating. v0 (6.1) usa manual ingestion.

### 6.4 — Eval expansion (~2 d)

Add ~8-10 queries cobrindo jurisprudência:

**Queries diretas sobre jurisprudência**:
- "STF se pronunciou sobre direito ao esquecimento na internet?" → Tema 786
- "Marco Civil art. 19 é constitucional segundo o STF?" → Tema 987 (pendente)
- "Banco responde por fraude em conta? STJ tem súmula?" → Súmula 479
- "Pessoa jurídica pode sofrer dano moral?" → Súmula 227 + jurisprudência LGPD

**Queries cross-doc com jurisprudência**:
- "Vazamento de dados com dano moral em pessoa jurídica" → LGPD art. 42 +
  Súmula 227 STJ + jurisprudência
- "Direito ao esquecimento + LGPD art. 18 IV" → Tema 786 + LGPD art. 18 IV

**Queries que devem CITAR jurisprudência mesmo sem ser perguntado**:
- "Posso processar provedor por conteúdo de terceiros?" → MCI art. 19 +
  hierarchy_warning + Tema 987 contextual

### 6.5 — Hierarchy warning extension (½ d)

Hoje warning fires quando rank cited > rank em top-K. Pra jurisprudência:

- Se cited tem só Lei mas top-K tinha Súmula Vinculante: warning?
  Súmula vinculante TEM efeito sobre a interpretação da lei.
- Decisão: NÃO emitir warning quando lei é cited mas súmula está em
  top-K — a lei é a fonte; a súmula é interpretação.
- Mas DEVE emitir aviso textual no answer:
  "Esta interpretação está sujeita à Súmula X do STJ que..."
- Implementação: novo campo `RAGAnswer.related_jurisprudencia` —
  para cada doc cited, surface jurisprudência relacionada que estava
  em top-K mas não foi cited.

### 6.6 — Cross-provider validation + write-up (½ d)

Padrão Phase 5.1: rodar Anthropic + Marítaca, comparar
faithfulness + refusal + per-tipo. Marítaca historicamente weaker em
recall jurisprudência (treino menos centrado em corpus brasileiro).

### 6.7 — Lawyer-review-checklist update

Adicionar à 🔴 (blockers):
- "Validação da curadoria de jurisprudência" — quais súmulas/temas são
  canônicos? STF/STJ têm milhares; selecionamos ~7 — defensável?
- "Tese de repercussão geral pendente vs decided" — Tema 987 (MCI 19)
  está pendente; como tratar a tese parcial?

## Cronograma

### Estimativa original (single dev sem AI)

| sub | sizing | wall clock |
|---|---|---|
| 6.0 URN scheme + schema | ½ d | day 1 |
| 6.1 Manual ingestion v0 | 2 d | day 1-3 |
| 6.2 Stub parser + corpus wiring | ½ d | day 3 |
| 6.4 Eval expansion + cross-validation | 2 d | day 4-5 |
| 6.5 Hierarchy warning extension | ½ d | day 5 |
| 6.6 Re-run eval + findings | ½ d | day 6 |
| 6.7 Doc updates | ¼ d | day 6 |
| **6.3 Real scrapers** (gated) | 5-7 d | LATER |

**v0 (manual hybrid)**: ~6 dias úteis
**Real scrapers gating**: depende de Phase 7+ (cron infra) ou D6 launch date

### Estimativa revisada (Claude-Code-assisted)

Empirical baseline (Phases 2-5): trabalho técnico comprime 5-10x;
curadoria comprime ~2x. Phase 6 v0 é mais técnica que curatorial
(7 itens canônicos pré-definidos no plan).

| sub | original | **revisada** | o que comprime |
|---|---|---|---|
| 6.0 URN scheme | ½ d | **15 min** | só edição em doc existente |
| 6.1 Manual ingestion (7 itens) | 2 d | **2-3h** | curadoria leve (textos curtos), build scripts repetitivos |
| 6.2 Stub parser + wiring | ½ d | **30 min** | mirror do AnpdPdfParser pattern já existente |
| 6.4 Eval expansion (8 queries) | 2 d | **1-2h** | similar ao 5.1 OOS — Claude rascunha, você revisa |
| 6.5 Hierarchy ext | ½ d | **30 min** | extensão pequena ao pipeline |
| 6.6 Cross-validation + write-up | ½ d | **1h** | 2 eval runs + comparação |
| 6.7 Docs | ¼ d | **15 min** | trivial |
| **v0 total** | **6 dias** | **~½-1 dia** ⭐ | (5-10x compression) |
| **6.3 scrapers real** (gated) | 5-7 d | **~2-3 d** | scraping + Playwright tem inerente exploração |

## Decisões pendentes

| # | decisão | recomendação |
|---|---|---|
| **D11 NEW** | Quais jurisprudência incluir no v0? | 3 STJ súmulas + 4 STF temas (lista acima); validar com advogado depois (D7) |
| **D12 NEW** | Súmula vinculante como rank 2 ou 3? | rank 2 (efeito vinculante geral, próximo de LC) |
| **D13 NEW** | Tema pendente (sem tese fixada) — incluir? | sim, com nav.status="pendente" + warning explícito |
| **D14 NEW** | Como apresentar jurisprudência no answer? | rodapé separado "Jurisprudência aplicável" + warning quando relevante |

## Custos estimados

- Acquisition: $0 (HTML scraping ou manual)
- Voyage re-embedding: ~$0.50 (10-15 chunks novos)
- Eval API: ~$2-3 por run × ~3 runs = ~$10
- Cross-validation: 2x do eval = ~$20
- **Total Phase 6 v0**: ~$30 + 6 dias de trabalho

## Risk

| risco | mitigation |
|---|---|
| Jurisprudência atualiza (Tema 987 julga; novas súmulas) | Build scripts versionados; re-run trivial |
| LexML resolver não cobre — usuário não pode validar URN | Documentar no doc + UI; link para portal.stf.jus.br |
| Marítaca treina pouco em jurisprudência BR — refusal/recall pior | Cross-validation surface; D7 lawyer review se gap > limiar |
| Lawyer disagree com curadoria | Defer to D7 review antes de v1.0 launch (gating já existe) |

## Open items (não-Phase-6 mas adjacentes)

- Quando STF julgar Tema 987 (MCI 19), atualizar:
  - vigência overlay (status sub_judice → vigente OU revogado)
  - jurisprudência chunk para Tema 987 (tese fixada)
  - Re-run eval — row sobre MCI art. 19 muda comportamento

## Verdict

Phase 6 v0 é factível em ~6 dias úteis com hybrid path (manual
ingestion + stub parser + eval expansion + cross-validation). Real
scrapers gated em Phase 7 (production infra) — segue padrão Phase 4.3.

Esta é uma das phases com maior payoff em "lei fria → prática
jurídica" (per reviewer round 2). Mas escopo curatorial precisa de
D7 lawyer review pra validar quais jurisprudências são canônicas
pro projeto.

Recomendação: começar com 6.0 (URN scheme) + 6.1 (manual ingestion
das 7 itens) + 6.2 (stub parser). ~3 dias. Depois decidir se segue
pra 6.4 (eval) ou pausa pra D7 lawyer review primeiro.
