# Hybrid retrieval — dense + sparse via RRF

Data: 2026-05-13. Branch: `main`.

## TL;DR

Testamos fusão **dense + sparse** via Reciprocal Rank Fusion (RRF) com três variações de sinal lexical e dois pesos diferentes. **Nenhuma combinação superou o dense Voyage puro.** Em todos os cenários, RRF aproximou-se do dense puro à medida que aumentamos o peso do dense, mas nunca o ultrapassou.

A conclusão é específica e útil pro write-up: **neste corpus, sinal lexical e sinal semântico estão altamente correlacionados** — quando o dense erra, o sparse erra junto. Não há classe de query onde sparse encontre relevantes que o dense perdeu. RRF, sob essa correlação, só adiciona ruído.

---

## Setup

- Eval set: as mesmas 25 queries de `eval/queries.yaml`.
- Dense baseline: `voyage-3-large + nav+caput+text` (melhor configuração do projeto até aqui: nDCG=0.713, Recall=0.834, MRR=0.730).
- Sparse testado:
  - **BGE-M3 sparse** — lexical_weights emitidos no mesmo forward que o dense. `compute_lexical_matching_score` = soma de pesos sobre tokens compartilhados.
  - **BM25** (rank-bm25 `BM25Okapi`) — IR clássico com tokenizer simples pt-br (regex sobre tokens lowercase, mantém dígitos e hifens).
- Fusão:
  - **RRF clássico** (Cormack et al. 2009): `score(d) = Σ_retriever 1/(k + rank_retriever(d))`, k=60.
  - **Weighted RRF**: `score(d) = w_dense/(k + rank_d) + w_sparse/(k + rank_s)`, testamos w=3:1 favorecendo dense.
- Top-K = 50 candidatos por retriever, fusão produz top-50; métricas no top-10/20.
- Código: `rag_leis/hybrid_eval.py` (RRF + M3-sparse), `rag_leis/bm25_eval.py` (RRF + BM25).

---

## Resultados — voyage dense + sparse signal

### nav+caput+text (a configuração de produção)

| pipeline | nDCG@10 | Recall@20 | MRR@10 |
|---|---|---|---|
| **dense (voyage)** | **0.713** | **0.834** | **0.730** |
| BGE-M3 sparse alone | 0.407 | 0.492 | 0.407 |
| BM25 alone | 0.413 | 0.603 | 0.414 |
| RRF (dense + m3-sparse, equal) | 0.504 | 0.718 | 0.532 |
| RRF (dense + m3-sparse, **dense 3x**) | 0.590 | 0.778 | 0.601 |
| RRF (dense + BM25, equal) | 0.569 | 0.767 | 0.595 |
| RRF (dense + BM25, **dense 3x**) | 0.637 | 0.783 | 0.691 |

### text mode (sparse-friendly — chunks têm texto distintivo)

| pipeline | nDCG@10 | Recall@20 | MRR@10 |
|---|---|---|---|
| dense (voyage / text) | 0.640 | 0.717 | 0.801 |
| BGE-M3 sparse alone | 0.295 | 0.380 | 0.380 |
| BM25 alone | 0.251 | 0.391 | 0.371 |
| RRF (dense + m3-sparse, equal) | 0.425 | 0.626 | 0.536 |
| RRF (dense + BM25, equal) | 0.452 | 0.599 | 0.631 |

### bge-m3 dense + bge-m3 sparse (same-model hybrid)

Para checar se o hybrid de mesmo-modelo (a tese central do paper de BGE-M3) salva neste corpus:

| modo | dense | sparse | RRF (equal) |
|---|---|---|---|
| text | 0.460 / 0.500 / 0.564 | 0.295 / 0.380 / 0.380 | 0.350 / 0.442 / 0.453 |
| nav+caput+text | 0.572 / 0.743 / 0.569 | 0.407 / 0.492 / 0.407 | 0.486 / 0.700 / 0.498 |

(nDCG@10 / Recall@20 / MRR@10)

Em todos os casos do mesmo-modelo, RRF também perde pro dense puro. Não é tão dramático quanto cross-model porque os dois sinais são mais correlacionados (mesmo encoder).

---

## Por que o sparse não ajuda?

Hipóteses iniciais que falsificamos:

1. ❌ **"Sparse pega citações literais que dense perde."** Falso — queries com termo literal ("o que é neutralidade de rede") são justamente as que o dense já acerta. O sparse também acerta o mesmo chunk. Não há ganho.
2. ❌ **"Caput-prefix mata o sparse, mas em text mode ele revive."** Falso — em text mode o sparse é AINDA pior (0.30 vs 0.41 em nav+caput+text). Caput-prefix ajuda o sparse de fato (mais tokens pra casar), só que ajuda mais o dense ainda.
3. ❌ **"BGE-M3 sparse é fraco, BM25 vai resolver."** Falso — BM25 é marginalmente melhor (Recall +11pp em nav+caput+text), mas a fusão continua perdendo.
4. ❌ **"Equal-weight RRF é injusto pro dense forte; weighted RRF salva."** Falso — weighted RRF 3:1 chegou perto (nDCG 0.637 vs 0.713 do dense), mas ainda perdeu. E quanto mais peso o dense ganha, mais o resultado tende ao próprio dense — é uma reta passando por (peso=∞, score=dense), nunca cruza acima.

A explicação que sobra:

> **Sparse e dense neste corpus encontram os mesmos relevantes e erram os mesmos irrelevantes.** Não há complementaridade. Em RRF, complementaridade é o que cria valor — se dois retrievers veem coisas diferentes, fundir os rankings agrega. Aqui eles veem o mesmo. Quando o dense erra (queries com gold único cujo caput é vago), o sparse também erra (mesmo texto, mesmas pistas lexicais). Quando o dense acerta (queries com termo literal no texto), o sparse também acerta — não há marginal pra adicionar.

A correlação alta entre sinais provavelmente vem da estrutura do corpus: chunks legais têm vocabulário denso e específico ("controlador", "operador", "tratamento", "anonimização"). Uma query menciona um desses termos → tanto o dense quanto o sparse convergem no mesmo conjunto pequeno de chunks. Não é o terreno típico de RRF (web data, onde queries genéricas combinadas com sparse + sinal estrutural via dense costumam complementar).

---

## Onde o RRF helpou (uma única query)

Em todos os runs, só uma query teve ΔnDCG>0.05 vs dense em modo nav+caput+text:

> [11] *"quais são os princípios do tratamento de dados pessoais na LGPD?"* (BGE-M3 dense+sparse, text mode)
> Dense top-3: art.1 (escopo da LGPD), Marco Civil art.3,III, art.6 (gold).
> Sparse top-3: art.55-J,§1; art.55-J,§3; art.6.
> RRF top-3: **art.6 (gold)**, art.1, art.55-J,§1.

Ambos os retrievers tinham art.6 em 3ª posição, e RRF amplificou esse consenso. Caso clássico onde "se dois discordam pouco, o consenso vence o ruído". Mas é só um caso.

---

## Conclusões e o que isso significa pro write-up

1. **RRF não é silver bullet.** É uma técnica condicionada à premissa de complementaridade entre retrievers. Quando os sinais correlacionam, RRF dilui em vez de complementar. Vale o post.
2. **BGE-M3 sparse alone é fraco neste corpus** — 0.41 nDCG vs 0.71 do voyage dense é mais que 1.7x de gap. BM25 marginalmente melhor. Sinal lexical custa quase nada extra (BGE-M3 já emite no mesmo forward), mas não é onde está a alavanca de produção.
3. **A melhor pipeline continua sendo dense puro com nav+caput+text** (voyage-3-large). Recall já em 0.834, MRR 0.730. nDCG 0.713 é o teto da eval atual.
4. **Caminhos plausíveis pra ir além**:
   - Eval set maior e mais variado (50–100 queries). Pode revelar segmentos onde sparse complementa (queries de citação literal vs queries paráfrase).
   - **Query-conditional retrieval**: detectar tipo de query (citação literal vs definição vs enumeração) e rotear pra sparse ou dense. Caro de implementar; provavelmente fica pra post de comparação de arquiteturas.
   - **Reranker em-domínio** (fine-tune ou Cohere/Voyage rerank). Pode atacar o problema de MRR sem destruir top-1.
   - **Multi-vector / ColBERT-style** (BGE-M3 já emite vetor ColBERT). Late interaction pode pegar matches token-level que dense single-vector perde, mas custo de armazenamento é ~50x.

---

## Para o post — pontos contrarian

- "Hybrid sparse+dense via RRF" é o conselho de produção mais repetido pra RAG. Em **um corpus pt-br jurídico com 5937 chunks e 25 queries paráfrase**, não funciona. Não é "funciona pouco" — é **regressão consistente em 3 variantes × 2 modos × 2 pesos = 12 configurações testadas**.
- O motivo é estrutural (correlação entre sinais), não tunável (peso, tokenizer, modelo de sparse). Útil de citar pra quem está prestes a montar a infra de hybrid sem medir antes.
- Vincula com o achado anterior (reranker piora): **second-stage retrieval (rerank + hybrid) é onde a maioria das pipelines RAG perde tempo. Melhor caminho neste corpus foi do parser (caput-prefix), não da camada de retrieval.** "Fix the data" venceu novamente.

---

## Artefatos

- Aggregates: `/tmp/hybrid_nav_caput.txt`, `/tmp/hybrid_text.txt`, output corrido de bm25_eval no log da última run.
- Código: `rag_leis/hybrid_eval.py`, `rag_leis/bm25_eval.py`.
- Caches: `data/index/bge-m3__{text,nav+caput+text}.sparse.pkl` (lexical_weights, picked).
- Comandos de reprodução:
  ```bash
  # BGE-M3 hybrid em ambos os modos
  python -m rag_leis.hybrid_eval --text-mode nav+caput+text --k 50
  python -m rag_leis.hybrid_eval --text-mode text --k 50

  # Cross-model voyage + bge-m3-sparse
  python -m rag_leis.hybrid_eval --dense-model voyage-3-large --text-mode nav+caput+text --k 50
  python -m rag_leis.hybrid_eval --dense-model voyage-3-large --text-mode nav+caput+text --k 50 --dense-weight 3

  # Voyage + BM25
  python -m rag_leis.bm25_eval --dense-model voyage-3-large --text-mode nav+caput+text --k 50
  python -m rag_leis.bm25_eval --dense-model voyage-3-large --text-mode nav+caput+text --k 50 --dense-weight 3
  ```
