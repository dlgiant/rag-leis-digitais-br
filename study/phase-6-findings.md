# Phase 6 — Jurisprudência Tier-4: findings

**Status:** v0 entregue (6.0, 6.1, 6.4, 6.5). 6.2 dispensado, 6.3 gated, 6.6 (este doc) fecha o ciclo.
**Data:** 2026-05-15
**Branch base:** `main` (commits `7ed065e..d8d43c9`)

## TL;DR

Adicionamos **7 chunks atômicos de jurisprudência STF/STJ** ao corpus (3 súmulas
STJ verbatim + 4 temas STF, sendo 1 com tese verbatim e 3 stubs flagados para
revisão D7). O retrieval funciona muito bem nessa tier — **10/11 queries acertam
o gold na posição 1**, com a única falha sendo um caso de sobreposição
vocabular com a Lei de Direitos Autorais. Métricas agregadas no eval set v3
(96 queries) subiram em todas as dimensões.

## Métricas — Voyage-3-large, label+nav+caput+text

| Métrica | Pre-Phase 6 (85 q) | Post-Phase 6 (96 q) | Δ |
|---|---|---|---|
| nDCG@10 | 0.6606 | **0.6890** | +0.028 |
| Recall@20 | 0.8501 | **0.8568** | +0.007 |
| MRR@10 | 0.7125 | **0.7359** | +0.023 |

Por tipo (96 queries):

| type | n | nDCG@10 | Recall@20 | MRR@10 |
|---|---|---|---|---|
| definicao | 23 | 0.8463 | 1.0000 | 0.8134 |
| **parafrase** | 24 | 0.7203 | 0.8396 | **0.8958** |
| enumeracao | 21 | 0.6283 | 0.7956 | 0.6726 |
| citacao-literal | 19 | 0.6240 | 0.8543 | 0.5866 |
| cross-doc | 9 | 0.4826 | 0.6852 | 0.5741 |

Paráfrase saltou para MRR 0.90 — jurisprudência atômica é "fácil" (texto único,
pouca competição lexical). Cross-doc continua o tipo mais difícil (poucos
exemplos, gold espalhado por leis).

## Per-query: onde caiu cada gold de jurisprudência

| Query | Tipo | Gold | Pos |
|---|---|---|---|
| "o que diz a Súmula 227 do STJ?" | citacao-literal | S 227 | **1** |
| "o que diz a Súmula 403 do STJ?" | citacao-literal | S 403 | **1** |
| "o que diz a Súmula 479 do STJ sobre instituições financeiras?" | citacao-literal | S 479 | **1** |
| "qual a tese fixada pelo STF no Tema 786?" | citacao-literal | T 786 | **1** |
| "uma empresa pode pedir indenização por dano moral?" | parafrase | S 227 | **1** |
| "preciso de autorização para usar a foto de uma pessoa em uma propaganda?" | parafrase | S 403 | **42** |
| "se um terceiro usa meus dados bancários para fraude, o banco responde?" | parafrase | S 479 | **1** |
| "existe direito ao esquecimento no Brasil?" | parafrase | T 786 | **1** |
| "a Receita Federal pode acessar meus dados bancários sem ordem judicial?" | parafrase | T 533 | **1** |
| "juiz pode bloquear o WhatsApp inteiro por descumprimento de ordem?" | parafrase | T 815 | **1** |
| "qual o regime de responsabilidade civil dos provedores...?" | cross-doc | T 987 / MCI art.19 / MCI art.21 | **1 / 2 / 9** |

## O 1 miss — análise

**Query:** "preciso de autorização para usar a foto de uma pessoa em uma propaganda?"
**Gold:** Súmula STJ 403
**Top-5 retornado:** Lei 9610 (Direitos Autorais) art.29 inc.8 alíneas g/j + art.79 §§1-2
**Posição real do gold:** 42

### Diagnóstico

A query usa o vocabulário "foto", "pessoa", "propaganda" — termos que aparecem
densamente no chunk da Lei de Direitos Autorais (art.79 trata de obras
audiovisuais e direito de imagem em produção fonográfica). O embedder está
fazendo a coisa **semanticamente certa** (LDA é tematicamente relacionado), mas
**juridicamente errada** — a resposta canônica para "preciso de autorização
para usar foto em propaganda" é:

1. **CC art.20** (uso da imagem como direito da personalidade) — não indexado ainda
2. **CF art.5º, X** (intimidade, vida privada, honra, imagem) — indexado, mas mais abstrato
3. **Súmula 403 STJ** (publicação não autorizada com fins econômicos = dano in re ipsa)

Lei 9610 (Direitos Autorais) trata de **obra autoral**, não de **direito de
imagem da pessoa retratada**. São institutos distintos. O embedder não captura
essa distinção doutrinária.

### Caminhos de correção (ordenados por custo)

1. **Reranker (BGE-reranker-v2-m3)** — Phase 4.4.b já tem esse stage para
   outros casos; aplicado aqui, o cross-encoder pode reorganizar top-50 e
   trazer S 403 para o top-10. Custo: instalar `--extra reranker` (~2GB torch).
2. **Hybrid sparse+dense** — BGE-M3 sparse embedding já existe no projeto; o
   token "súmula 403" + "dano moral" via BM25 daria peso à súmula. Custo:
   wire o stage híbrido no run_eval.
3. **Indexar Código Civil art.20** — a fonte canônica está faltando do corpus.
   Quando indexar, o gold dessa query ficaria `[CC art.20, S 403]` (LDA cairia
   naturalmente no rank).
4. **Query rewriting** — LLM expande "foto em propaganda" → "uso comercial de
   imagem da pessoa, art.20 CC, Súmula 403 STJ". Custo: chamada extra ao LLM
   por query.

Próxima ação: testar (1) reranker antes de adicionar (3) ou (4) — menor custo
de implementação.

## Decisões de design documentadas

### D1: ChunkKind atômico para jurisprudência

`ChunkKind = "jurisprudencia"` foi adicionado como sexto valor do Literal,
ortogonal aos cinco LCP-95 (artigo / §  / inc / alí / item). Súmulas e teses
não têm hierarquia interna — forçá-las no esquema legislativo seria
falsificação. **Implicação:** parsers futuros de jurisprudência não devem
emitir `parent_partition`; o renderer no answer payload trata `kind ==
"jurisprudencia"` como caso especial.

### D2: Rank URN-derivado vs. effective rank

`legal_rank_for_urn(urn)` mapeia tipo URN → rank potencial. Mas a vinculância
real depende de status de fato: um Tema STF sem tese fixada não tem efeito
vinculante difusa. **Phase 6.5** introduziu `effective_legal_rank(urn, nav)`
que faz rank-down para `RANK_INFRALEGAL` quando `nav.status` contém
`"pendente"`. A partir disso, `IndexChunk.legal_rank` reflete a autoridade
**efetiva**, não só a URN.

| URN | URN rank | Status | Effective rank |
|---|---|---|---|
| `tema:786` | 3 | `tese-fixada` | **3** |
| `tema:987` | 3 | `tese-fixada-pendente-transcricao-verbatim` | **5** |
| `tema:533` | 3 | `tese-fixada-pendente-transcricao-verbatim` | **5** |
| `tema:815` | 3 | `pendente_julgamento` | **5** |
| `sumula.vinculante:11` | 2 | `vigente` | **2** |
| `sumula:227` | 5 | `vigente` | **5** |

Isso preserva o `hierarchy_warning`: se o LLM citar o stub Tema 987 ignorando
MCI art.19, o warning surge porque o stub é rank 5 e a lei é rank 3.

### D3: Stubs em vez de confabulação

Para Tema 987, 533 e 815 não temos a tese verbatim na frente — escrever
"tese verbatim" do meu (Claude Code) conhecimento seria reproduzir o problema
que Phase 5.1 resolveu (Marítaca confabulando sobre PL não promulgado).

Convenção adotada:
- **`partition: "ementa"`** (não `"tese"`) — sinaliza que é descrição curatorial
- **Texto começa com `"STUB — DESCRIÇÃO RESUMIDA, NÃO É A TESE VERBATIM"`** — bloqueia
  o LLM de citar como se fosse fonte autoritativa
- **`nav.status` com sufixo `-pendente-...`** — dispara o rank-down de D2
- **`notes[]` carrega `PENDENTE_REVISAO_JURIDICA`** — handoff para D7

Trade-off explícito: chunks ficam menos úteis no curto prazo (LLM tem que dizer
"ainda não temos a tese verbatim, consulte STF"), mas o sistema mantém
honestidade epistêmica. Quando o D7 substituir os stubs, basta editar o JSONL
+ remover sufixo `-pendente-` e o rank automaticamente sobe para 3.

### D4: Tema STF aceita URN sem data

Convenção LexML padrão é `urn:lex:br:autoridade:tipo:DATE;ID`. Para temas STF,
o número é universalmente único (Tema 786 só existe um), e a data de fixação
da tese muitas vezes é menos saliente que o número. Adotamos
`urn:lex:br:supremo.tribunal.federal:tema:786` (sem segmento de data) como
forma canônica. `tests/test_urn_validity.py::DOC_URN_RE` foi relaxado para
aceitar essa variante. Para súmulas, mantida a forma com data
(`sumula:1999-09-08;227`) porque ali a data é histórica e relevante.

### D5: Ingestão manual em vez de scraper

Phase 6.1 entrega 7 chunks via JSONL escrito à mão (`data/chunks/tier-4/`).
Phase 6.3 (scrapers reais STF/STJ) ficou **gated** — três razões:

1. **Padrão a/b** já validado em Phase 4.3 (ANPD): manual unblocka eval/gen,
   parser real vem depois quando há clareza sobre escopo.
2. **D7 lawyer** precisa definir whitelist canônica antes de scraper fazer
   sentido (STF tem ~1.300 temas, STJ ~700 súmulas; sem curadoria é noise).
3. **Phase 7 scheduler** é a infra que dá valor real ao scraper (cron + diff);
   sem ela, scraper é só script one-off.

## Suite de testes

| Arquivo | Adicionados | Total |
|---|---|---|
| `tests/test_legal_rank.py` | +14 (parametrizados + case-insensitive) | 31 |
| `tests/test_jurisprudencia_rank.py` | +5 (end-to-end, lê chunks reais) | 5 |
| `tests/test_urn_validity.py` | regexes atualizadas, +0 testes | 7 |

Total da suite: **257 passed** (era 242 antes de Phase 6). Zero regressão.

## O que fica em aberto

### Phase 6.3 (gated)

Scrapers reais STJ + STF. Ver razões em `study/phase-6-jurisprudencia-plan.md`
§6.3. Resumo: depende de D7 lawyer + Phase 7 scheduler.

### Phase 6.4 cross-validation LLM

A expansão de eval em 6.4 mediu retrieval (Voyage embedder), não generation. O
protocolo Phase 5.1 (Marítaca vs Anthropic com cross-validation de gold) não foi
replicado nas 11 novas queries de jurisprudência. Hipótese a testar:
**Marítaca confabula tese verbatim quando o stub diz `STUB — não é a tese
verbatim`?** Custo: ~22 chamadas LLM (11 × 2 providers). Aguardando ask
explícito do user (per memory `feedback-paid-api-caution`).

### Indexação D7-driven

Quando o consultor jurídico for contratado:
- Substituir 3 stubs (Tema 987, 533, 815) por tese verbatim → chunks
  re-promovem automaticamente de rank 5 para 3
- Avaliar inclusão de mais súmulas/temas relevantes pra direito digital
- Validar a curadoria das 3 súmulas STJ atuais (227 / 403 / 479)
- Item 5 do `study/lawyer-review-checklist.md`

### Indexação CC art.20 + leitura mais ampla do CC

O 1 miss revelou que falta o Código Civil art.20 (direito de imagem) no
corpus. Quando indexar, o gold de várias queries paráfrase-jurisprudência
ficará mais rico (LDA não é a fonte canônica para imagem da pessoa).

## Próxima decisão

Caminho recomendado por custo crescente:
1. **Sem custo:** mergear este findings doc + Phase 6.5 já mergeada localmente
   (push pendente de autorização explícita do user)
2. **Custo CPU local (~2GB torch):** instalar reranker e testar se BGE-reranker
   resolve o miss da Súmula 403
3. **Custo Voyage:** indexar CC art.20 (alguns chunks novos = poucos
   centavos de embedding)
4. **Custo Anthropic + Marítaca:** cross-validation LLM nas 11 jurisprudência
   queries (~22 chamadas)
5. **Custo D7 lawyer:** revisão completa, substituição dos stubs, expansão
   da curadoria

Recomendo (1) + (3), defer (2) e (4) até bater Phase 7 (production infra).
