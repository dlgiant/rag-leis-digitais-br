# Comparação de rerankers — voyage-3-large + text (25 queries)

Data: 2026-05-13. Branch: `parser/hierarchical-lcp95`.

## TL;DR

**Os três rerankers cross-encoder multilíngues que testamos pioram o ranking** quando aplicados sobre top-20 do voyage-3-large + text. Não é "ajudou pouco" — é regressão de 14 a 29 pontos de MRR.

| pipeline | nDCG@10 | Recall@20 | MRR@10 |
|---|---|---|---|
| dense (voyage-3-large) | **0.638** | 0.717 | **0.801** |
| dense + bge-reranker-v2-m3 | 0.494 | 0.717 | 0.626 |
| dense + jina-reranker-v2-base-multilingual | 0.467 | 0.717 | 0.572 |
| dense + bge-reranker-v2-gemma | 0.439 | 0.717 | 0.513 |

Recall@20 é idêntico nas 4 linhas — o reranker só reordena o top-K. O problema é **qual chunk fica em 1º lugar**.

Resultado contraintuitivo importante para o write-up: **quanto "mais forte" o reranker, pior fica**. Gemma (2B params, líder de BEIR multilíngue) é o que mais machuca. bge-reranker-v2-m3 (568M, mesma família dos embeddings testados como baseline) é o "menos ruim", mas ainda perde 18 pontos de MRR.

---

## Setup

- Embeddings: voyage-3-large, modo `text` (sem `nav` prefix). Top-20 cacheado em `data/index/voyage-3-large__text.npz`.
- Rerankers: `BAAI/bge-reranker-v2-m3` (cross-encoder XLM-R, 568M), `jinaai/jina-reranker-v2-base-multilingual` (XLM-R base, 278M, treinado também em structured data), `BAAI/bge-reranker-v2-gemma` (Gemma-2B com scoring LLM-style sobre token "Yes").
- Eval set: 25 queries em `eval/queries.yaml`, relevância binária, mistura de definições + enumerações + citações literais cobrindo LGPD, Marco Civil, Lei do Software, Direito Autoral, LAI e o decreto da neutralidade.
- Métricas no top-10 (nDCG, MRR); recall medido no top-20.
- Cada reranker reordenou o mesmo top-20 do dense — então recall não muda; só ranking.

Script: `rag_leis/analyze_rerank.py` (per-query dump ordenado por ΔMRR).

---

## Onde quebra: query [16] como caso canônico

A única query que **todos os três rerankers** mataram completamente (MRR 1.0 → 0.0):

> Query: *"o que é neutralidade de rede no Marco Civil da Internet?"*
> Gold: `art.9` (caput que define neutralidade)

| posição | dense (voyage) | bge-m3 | jina-v2 | bge-gemma |
|---|---|---|---|---|
| 1 | ★ **art.9** | art.3, IV | (similar) | art.8, VI |
| 2 | art.3, IV | art.24, VII | — | art.3, V |
| 3 | decreto 8771 art.3 | decreto 8771 art.6 | — | decreto 8771 art.7 |

O que o dense faz certo: pega o caput do art.9 do Marco Civil, que é **a definição literal** ("O responsável pela transmissão... deve tratar de forma isonômica quaisquer pacotes de dados..."). 

O que o reranker faz errado: pega o art.3, IV — um inciso da lista de princípios que diz "preservação e garantia da neutralidade de rede". Tem o token "neutralidade de rede" explícito, mas é um item de lista de uma palavra-frase, não a definição.

Padrão: **o cross-encoder está fazendo casamento token-level**. Onde o dense entendeu "o que é X" como "me dê a definição de X", o reranker entendeu "me dê o chunk com mais ocorrências/casamento de X".

---

## Padrões de falha (≥7 queries cada)

### A. Definição vs. princípio/lista

Dense pega caput-definição; reranker pega inciso que cita o termo.

- [16] neutralidade de rede → dense art.9 (caput-def), rerank art.3,IV (princípio)
- [17] definição legal de programa de computador → dense Lei 9609 art.1 (def), rerank Lei 9610 art.7 §1 (direito autoral de software)
- [20] informação pessoal na LAI → dense LAI art.4,IV (def), rerank LGPD art.5,I (def **da LGPD**, não da LAI — confusão cross-lei)

### B. Caput vs. inciso/§ irmão

Dense ancora no caput do artigo correto; reranker promove um §/inciso adjacente ou o caput de um artigo vizinho.

- [5] dados sensíveis sem consentimento → dense art.11,II (caput da hipótese), rerank art.11,§1 (irmão estrutural)
- [6] direitos do titular → dense art.18 (caput), rerank art.20 ou art.18,§1 (próximo)
- [9] provedor de conexão responde civilmente → dense art.18 do MCI (regra de imunidade), gemma art.21 ("dano decorrente de divulgação")
- [11] princípios do tratamento → dense art.6 (caput), rerank art.49 ou art.55-j,§1 (cita "princípios" em outro contexto)
- [14] sanções ANPD → dense art.52 + incisos, rerank art.55-K (cita "sanções" no nome de outra seção)

### C. Cross-artigo / cross-lei

Dense diferencia entre artigos vizinhos similares; reranker confunde.

- [4] hipóteses para tratar sem consentimento → dense art.7,IX, rerank art.7 (caput-vazio que só diz "as seguintes hipóteses") ou art.18,VI
- [13] avaliação de país adequado → dense art.34 (caput-def), gemma art.33 §1 (artigo vizinho que cita transferência)

### D. Anchor lexical fraco quebra o que estava OK

Queries que o dense já tinha múltiplos relevantes nos top-3, reranker mantém 1 mas joga os outros pra fora do top-3.

- [10] direitos garantidos ao usuário → dense top-3 = art.7 + art.7,II + art.7,XI (todos gold). bge-m3 mantém só art.7, troca os outros por art.175 da Constituição e art.98-B,VII da Lei 9610.

---

## Hipóteses sobre a causa raiz

1. **Treino fora-de-domínio**. Os três rerankers foram treinados em pares query–passagem genéricos (MS MARCO, NQ multilíngues), onde "responder a uma pergunta" significa o texto da passagem casar com o tópico. Em corpus legal estruturado, a resposta certa é frequentemente o **caput**, que é deliberadamente vazio de conteúdo lexical ("As seguintes hipóteses são:" / "O titular tem direito a:"). O reranker não tem prior pra esse padrão.
2. **Token-level emphasis dos cross-encoders**. A arquitetura cross-encoder concatena query+passage e dá muito peso a casamento de tokens da query no documento. Caputs jurídicos não têm os tokens da query — o conteúdo está nos filhos. O dense bi-encoder, por contraste, aprende uma representação holística do artigo no embedding.
3. **Voyage já é forte demais no top-1**. O dense entrega MRR=0.80, ou seja, em 80% das queries o gold está em 1º. O reranker só pode (a) manter o 1º — sem ganho, ou (b) trocar — frequentemente piora. Com base baixa (BGE-M3 dense MRR=0.56) sobra mais espaço pra ele agregar valor.
4. **Quanto maior o modelo, mais opinionado e mais errado quando errado**. Gemma-2B prompted-style produz scores muito polarizados (logits do token "Yes"); um chunk com leve preferência lexical fica MUITO acima dos outros. m3 produz logits mais comprimidos.

A combinação (1)+(2) é o que dói: o sinal certo no nosso corpus está em chunks deliberadamente vagos no nível lexical, e cross-encoders trained on web QA estão **adversariamente desalinhados** com isso.

---

## Onde o reranker ajuda (e como replicar)

Casos isolados onde reranker ajudou voyage+text:

| # | Query | Δ MRR (m3) | Padrão |
|---|---|---|---|
| 1 | "qual a definição de dado pessoal na LGPD?" | +0.50 | dense pegou um decreto regulamentador em 1º; reranker subiu art.5,I |
| 7 | "como o Código Penal define crime de invasão de dispositivo informático?" | +0.50 | similar — dense pegou parágrafo conexo, reranker subiu o caput |
| 15 (jina) | "medidas de segurança" | +0.17 | dense estava com art.6,VII em 1º (princípio); jina subiu art.46 (caput-def) |

Padrão: **quando o dense errou o 1º colocado e a resposta certa estava em #2-#5, o reranker pode acertar**. Só que ele faz isso ~3x menos vezes do que ele troca o 1º correto por um errado.

---

## O que tentar a seguir

Em ordem de aposta-vs-esforço:

1. **Não usar reranker como default no top-1.** Pra produção, dense voyage+text+nav é o mais limpo. Reranker como uma camada de "expandir top-20 → ressortear top-10 quando MRR_dense estiver baixa" — não como sempre-ligado.
2. **Top-K maior antes do reranker**. Recall@20 está em 0.72 — 28% dos relevantes não chegam no candidate set. Vale rodar dense top-50 ou top-100 e medir se reranker compensa o ganho de cobertura. Hipótese: gemma melhora se tiver candidatos relevantes que o dense não rankeou no top-20.
3. **Reranker treinado em-domínio**. `voyage-rerank-2.5` ou Cohere `rerank-multilingual-v3` foram treinados em corpus jurídico/comercial mais amplo e podem ser menos token-rabid. Custa créditos de API.
4. **Caput-prefix do parser** (já mapeado no Dia-2). Resolve o problema na origem: se o caput é vago, o filho carrega o texto do caput. Reranker provavelmente continua errando, mas o **dense** ganha — e o sistema todo fica menos sensível a um reranker ruim.
5. **Hybrid search dense + BM25 com RRF**. Casos do tipo "qual a definição de X" são exatamente onde lexical match no caput certo bate o cross-encoder. BGE-M3 emite sparse no mesmo forward — vale exercitar.

---

## Para o post

- "Reranker piora retrieval" não é o que está nos READMEs. É um achado de domínio: legal-pt-br + chunking estrutural é um terreno onde o pressuposto "cross-encoder > bi-encoder no top-K" inverte.
- O **paradoxo do modelo grande**: gemma é a "melhor" arquitetura testada e a pior em uso. Material direto pro tópico "benchmarks são contextuais".
- O passo seguinte natural é **mostrar que o problema é o caput-vazio** — quando rodarmos com caput-prefix no parser, a hipótese é que (a) dense sobe, (b) reranker também sobe, (c) gap reranker–dense diminui. Se confirmar, fica um caso de "fix the data, not the model".
- `bge-reranker-v2-m3` ainda é o melhor reranker dentre os três pra este corpus — não porque acerta, mas porque erra menos. Útil de citar pra quem leu o paper de M3 e assumiu transferência forte pra pt-br jurídico.

---

## Update — testando a hipótese "fix the data": caput-prefix nos chunks

Implementação no `format_texts` (sem re-parser): para cada chunk, walk up no `parent_partition` e concatenar todos os caputs ancestrais. Inciso/§/alínea passam a carregar o caput do artigo. Dois modos novos: `caput+text` e `nav+caput+text`.

Exemplo (`art7;inc9` da LGPD):
```
text:           "quando necessário para atender aos interesses legítimos do controlador..."
caput+text:     "O tratamento de dados pessoais somente poderá ser realizado nas seguintes
                 hipóteses: quando necessário para atender aos interesses legítimos..."
nav+caput+text: "II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos :: O tratamento de
                 dados pessoais somente poderá ser realizado nas seguintes hipóteses:
                 quando necessário..."
```

### Resultados dense (mesma eval set, 25 queries)

| modelo | mode | nDCG@10 | Recall@20 | MRR@10 |
|---|---|---|---|---|
| bge-m3 | text | 0.460 | 0.500 | 0.564 |
| bge-m3 | nav+text | 0.533 | 0.620 | 0.628 |
| bge-m3 | caput+text | 0.591 | 0.707 | 0.603 |
| bge-m3 | nav+caput+text | 0.572 | 0.743 | 0.569 |
| voyage-3-large | text | 0.638 | 0.717 | 0.801 |
| voyage-3-large | nav+text | 0.667 | 0.774 | 0.811 |
| voyage-3-large | caput+text | 0.703 | 0.834 | 0.728 |
| voyage-3-large | **nav+caput+text** | **0.713** | **0.834** | 0.730 |

### O que aconteceu

A hipótese (a) bateu: **nDCG e Recall sobem em todos os casos** com caput-prefix. voyage+nav+caput+text é o novo SOTA da eval (+7.5pp nDCG, +12pp Recall vs. text). bge-m3 ganha ainda mais em termos relativos (+13pp nDCG).

A hipótese (b) **não** bateu: **MRR caiu** em voyage (0.81 → 0.73). Isso revela uma tensão estrutural que o teste original não conseguiu ver:

> **Trade-off "context leak vs. ranking":** prefixar o caput faz os irmãos do mesmo artigo ficarem semanticamente parecidos entre si. Antes, "qual a definição de dado pessoal" → art.5,I (única coincidência forte). Agora art.5,II, art.5,III, etc. todos carregam o caput "Para os fins desta Lei, considera-se:" — todos ficam plausíveis no top-1.

Resultado: o **conjunto** de top-k fica melhor (recall ↑, nDCG ↑ porque mais relevantes entram em posições altas), mas o **primeiro colocado** fica ruidoso (MRR ↓). Pra queries com gold único (definição literal), caput-prefix é regressão; pra queries com gold de N chunks (enumerações), é ganho franco.

A hipótese (c) tinha duas partes: dense sobe (sim, na média) e reranker fecha gap. Vamos ver.

### Reranker em cima de voyage+nav+caput+text

| pipeline | nDCG@10 | Recall@20 | MRR@10 |
|---|---|---|---|
| dense (voyage + nav+caput+text) | **0.713** | 0.834 | **0.730** |
| dense + bge-reranker-v2-m3 | 0.635 | 0.834 | 0.646 |
| dense + jina-reranker-v2-base-multilingual | 0.599 | 0.834 | 0.626 |
| dense + bge-reranker-v2-gemma | 0.335 | 0.834 | 0.332 |

Reranker ainda piora — mas em magnitudes diferentes:

| reranker | ΔnDCG no text | ΔnDCG no nav+caput+text |
|---|---|---|
| bge-m3 | -0.144 | -0.079 |
| jina-v2 | -0.171 | -0.114 |
| **gemma** | -0.198 | **-0.379** |

m3 e jina amaciam o estrago — provável que o caput-prefix torne os passages **menos** dependentes de casamento token-level, então o cross-encoder erra menos no top-1. Gemma vai pra trás violentamente: provavelmente porque o caput-prefix faz **todas** as passagens do mesmo artigo terem alta similaridade lexical com a query, e o scoring polarizado da Gemma (logits do token "Yes") amplifica diferenças mínimas para escolhas erradas.

### Padrões de falha pós-caput (top-3 dumps)

Mudança qualitativa: antes o reranker confundia **artigos** (art.18 → art.19; art.7 → art.6); agora confunde **irmãos do mesmo artigo** (art.18 caput vs art.18;inc8; art.11;par1 vs art.11;par2).

Query [21] (prazo LAI):
- gold: art.11;par1
- dense: ★ art.11;par1 → art.11;par1;inc3 → art.11;par1;inc1
- bge-m3: art.11;par1;inc3 → art.11;par1;inc1 → ★ art.11;par1

Todos os 3 chunks no top do reranker são "filhos do par.1" — o reranker sabe que estão no contexto certo, só erra **qual nível da hierarquia** responde.

### Conclusões revisadas

1. **Nova baseline de produção**: voyage-3-large + `nav+caput+text`, sem reranker. nDCG 0.713 / Recall 0.834 / MRR 0.730.
2. **Caput-prefix é um ganho net-positive** em nDCG e Recall, mas é um trade-off explícito em MRR. Se a aplicação precisa de "**uma** resposta única no top-1" (FAQ / pergunta-resposta), considerar manter `nav+text`. Se precisa de "**conjunto** de chunks relevantes pra contexto de LLM" (RAG clássico), `nav+caput+text` é melhor.
3. **Reranker continua tóxico**, mas o problema mudou: era "confunde artigos vizinhos" → é "confunde níveis da mesma família". Suspeito que melhore com top-K maior (top-50/100) já que o candidate set tem cobertura muito melhor (Recall 0.834 vs 0.717). Próximo experimento: rerank no top-50 — **falsificado abaixo**.
4. **Gemma é definitivamente o pior**: -0.38 nDCG é o tipo de regressão que indica modelo-corpus mismatch grave, não tuning fino. Não vale insistir.

### Update — testando reranker no top-50

A hipótese era que dar mais candidatos (top-50 em vez de top-20) daria ao reranker espaço pra puxar relevantes que o dense rankeou em 21-50 pra dentro do top-20 final. Recall@50 do dense é 0.884 (vs Recall@20 = 0.834), então existe ~5pp de teto disponível.

| pipeline (k=50) | nDCG@10 | Recall@20 | MRR@10 |
|---|---|---|---|
| dense ceiling Recall@50 | — | 0.884 | — |
| **dense (top-50, métricas no top-20/10)** | **0.713** | **0.834** | **0.730** |
| dense + bge-reranker-v2-m3 | 0.626 | **0.772** | 0.622 |
| dense + jina-reranker-v2-base-multilingual | 0.583 | **0.776** | 0.607 |
| dense + bge-reranker-v2-gemma | 0.290 | **0.523** | 0.317 |

**Recall@20 dos rerankers caiu** comparado ao dense (em k=20 isso era impossível por construção — o set de top-20 era idêntico). O reranker não só está reordenando mal o top-20 — está **puxando chunks irrelevantes de posições 21-50 pra dentro do top-20**, derrubando até a métrica que parecia segura.

Gemma é o caso extremo: Recall@20 desaba de 0.834 → 0.523. O reranker está convencido de que chunks que o dense rankeou em posição 30+ são mais relevantes que os top-20.

**Conclusão definitiva**: rerankers cross-encoder multilíngues genéricos não funcionam neste corpus. Não é questão de top-K, não é questão de representação de chunk, não é questão de força do modelo (gemma é o líder de BEIR e o pior aqui). É **misalignment de critério de relevância** treinado em web-QA vs. corpus jurídico estruturado em pt-br.

Pra o reranker valer a pena, precisaríamos de:
- (a) reranker fine-tuned no domínio (esforço significativo), ou
- (b) reranker comercial treinado em corpus comercial-jurídico amplo (Cohere `rerank-multilingual-v3`, voyage `rerank-2.5` — custa créditos, não testamos), ou
- (c) outra estratégia de "second-stage": hybrid sparse + dense via RRF, que aproveita o sinal lexical do BGE-M3 sem confiar em cross-encoder.

Por enquanto a melhor recomendação é **dense puro com nav+caput+text e top-K alto**, sem reranker.

### Para o post, edição final

- **"Fix the data" funcionou parcialmente.** Subiu nDCG e Recall do dense. **Não** fechou o gap com o reranker — na verdade, em uma das métricas (MRR), o caput-prefix piorou o dense, e o reranker continuou piorando mais ainda.
- **Trade-off revelado pelo experimento**: prefixar contexto estrutural aumenta cobertura e reduz precisão top-1 simultaneamente. É um material rico pro post — duas escolas de pensamento sobre chunking (cada chunk auto-contido vs. cada chunk com contexto enxuto) e dados que mostram quando cada uma ganha.
- **nDCG é a métrica certa pra RAG, não MRR.** O LLM downstream vai receber top-K chunks, não só top-1. A métrica que casa com "qualidade do conjunto top-10" é nDCG. Pela lente certa, caput-prefix é o melhor truque que testamos em todo o projeto.

---

## Artefatos

- Aggregates iniciais (voyage+text): `/tmp/rerank_voyage_text.txt`
- Aggregates pós-caput (voyage+nav+caput+text): `/tmp/rerank_voyage_nav_caput.txt`
- Re-rodar baseline: `python -m rag_leis.run_eval --model voyage-3-large --text-mode nav+caput+text`
- Re-rodar rerank: `python -m rag_leis.analyze_rerank --model voyage-3-large --text-mode nav+caput+text --rerankers bge-reranker-v2-m3,jina-reranker-v2-base-multilingual,bge-reranker-v2-gemma`
- Código: `rag_leis/rerank.py`, `rag_leis/analyze_rerank.py`, `rag_leis/eval_harness.py` (load_chunks + format_texts).
- Indexes cacheados: `data/index/{voyage-3-large,bge-m3}__{text,nav+text,caput+text,nav+caput+text}.npz`.
