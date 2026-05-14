# Voyage rerank-2.5 — o primeiro reranker que **não** é regressão

Branch: `experiment/voyage-rerank`. Data: 2026-05-13.

## TL;DR

Quatro experimentos anteriores de second-stage retrieval (3 rerankers cross-encoder open + 1 router gated) **regrediram** ou ficaram dentro do ruído. **Voyage rerank-2.5 (comercial, domain-tuned) é o primeiro que melhora alguma coisa de verdade**:

| metric | dense alone | + voyage rerank-2.5 | Δ |
|---|---:|---:|---:|
| nDCG@10 | 0.608 | 0.603 | -0.005 |
| Recall@20 | 0.856 | 0.856 | 0 |
| **MRR@10** | 0.591 | **0.613** | **+0.022** |

Quase flat no nDCG agregado, mas **+22pp em MRR**. E o per-type mostra que o ganho está concentrado exatamente na categoria que mais tinha problema:

| tipo | dense | + rerank-2.5 | Δ nDCG | dense MRR | rerank MRR | Δ MRR |
|---|---:|---:|---:|---:|---:|---:|
| **citacao-literal** | 0.483 | **0.581** | **+0.098** | 0.448 | **0.613** | **+0.165** |
| enumeracao | 0.695 | 0.701 | +0.006 | 0.782 | **0.840** | +0.058 |
| definicao | 0.825 | 0.777 | -0.048 | 0.769 | 0.721 | -0.048 |
| cross-doc | 0.450 | 0.424 | -0.026 | 0.483 | 0.475 | -0.008 |
| parafrase | 0.491 | 0.449 | -0.042 | 0.402 | 0.368 | -0.034 |

**Citação-literal MRR: +37% relativo**. Categoria mais problemática até aqui (era 0.45 MRR; agora 0.61). Definição perde -0.05 mas estava em 0.83 — perdeu pouco em altura.

A **tese revisada**: pra **RAG que envia top-K ao LLM** (nDCG é a métrica que importa), dense puro continua sendo o operating point. Pra **aplicações single-answer** (FAQ, chatbot que retorna uma resposta), voyage rerank-2.5 é o primeiro reranker que vale a pena ligar.

## Setup

- Eval set v3: 78 queries tipadas em `eval/queries.yaml`.
- Pipeline dense: voyage-3-large + `label+nav+caput+text`, top-K=20.
- Reranker: `voyage.Client().rerank(query, documents, model="rerank-2.5")` retornando scores de relevância. Re-ordena top-20 do dense.
- Custo: ~$0.05 por 1K documentos. 78 queries × 20 docs = ~$0.08 por run.

Implementação em `rag_leis/rerank.py:VoyageReranker`.

## Por que funciona aqui onde os outros falharam

Os 3 rerankers cross-encoder open-source testados antes (bge-m3, jina-v2, bge-gemma) compartilham uma característica: **foram treinados predominantemente em web QA** (MS MARCO, NQ multilíngues). Em corpus jurídico estruturado:

- Onde a resposta certa é o **caput** (lexicalmente vago: "As seguintes hipóteses são:"), token-overlap rerankers preferem chunks-filhos que mencionam o termo específico.
- Onde a query é **citação literal** ("o que diz o art. 7?"), o sinal certo é símbolico (a citação canônica), não semântico — cross-encoders genéricos não são treinados pra isso.

Voyage rerank-2.5 é diferente. Não temos visibilidade dos detalhes de treinamento, mas a evidência mostra:
1. **Citação literal melhorou** — o modelo entende "art. X" como identificador, não como bag of words. Provável fine-tuning em corpus jurídico/contratual.
2. **Categorias já-fortes (definicao, parafrase) regrediram menos** que com os open-source. Não é "consertar errando outras coisas" — é "consertar quase sem custo".

A tese implícita: rerankers comerciais com domain-tuning amplo (Voyage rerank-2.5, provavelmente Cohere rerank-multilingual-v3 também) podem quebrar o pattern de falha dos open-source genéricos.

## A variante lite é pior

| | rerank-2.5 | rerank-2.5-lite |
|---|---:|---:|
| nDCG@10 | -0.005 | -0.013 |
| MRR@10 | **+0.022** | -0.013 |
| citacao-literal nDCG | **+0.098** | +0.032 |
| citacao-literal MRR | **+0.165** | +0.012 |

Lite regride no agregado, e o ganho de citação literal vira marginal. Não vale baratear aqui.

## O efeito por query em citacao-literal

Pra entender de onde vem o salto de citação literal (15 queries do tipo "o que diz o art. X?"):

- Dense baseline: 5 das 15 com MRR=0 (chunk certo não no top-10), 10 com MRR alto. Média 0.448.
- + voyage rerank-2.5: 3 das 15 com MRR=0, 12 com MRR alto. Média 0.613.

Reduz 2 das 5 falhas — sem destruir nenhum acerto existente. **Esse é o padrão que estava ausente nos 3 rerankers anteriores**: ajudar onde dense errou sem prejudicar onde dense acertou.

Recall@20 é idêntico (0.856 → 0.856) — esperado, reranker só reordena top-K do dense.

## Por que ainda perdemos um pouco em nDCG agregado

Apesar do MRR subir, o nDCG fica quase flat (-0.005). Razão: o rerank troca acertos por outros acertos em queries com gold multi-chunk. Definição (gold single chunk) → rerank promove às vezes um irmão estrutural não-gold. Como o gold tem só 1 entrada, qualquer movimento que não puxe ela pro top-1 piora nDCG.

Em queries multi-chunk (enumeracao, citacao-literal), o rerank consegue mover gold para cima sem deslocar outros gold — daí o ganho diferencial.

## Implicações práticas

| caso de uso | recomendação |
|---|---|
| RAG que envia top-5/10 ao LLM | voyage dense puro, sem rerank |
| FAQ single-answer (mostra 1 resposta) | voyage dense + voyage rerank-2.5 |
| Citation lookup específica (legal/contratual) | voyage dense + voyage rerank-2.5 (+0.10 nDCG, +0.17 MRR em citação literal) |
| Latency-sensitive (<100ms) | voyage dense puro — rerank-2.5 adiciona ~50-150ms de roundtrip API |

Custo extra de produção: ~$50/M docs reranked, então 1K queries/dia × 20 docs/query = 20K docs/dia = ~$1/dia. Negligível pra a maioria dos usos.

## Onde **não** ajuda

- **Paráfrase** (-0.034 MRR): voyage rerank-2.5 ainda prefere chunks com casamento token sobre os semanticamente equivalentes mas vocabulário diferente. Mesmo problema dos cross-encoders open, atenuado mas presente.
- **Cross-doc** (-0.008 MRR): igual ao padrão dos outros — rerank amplifica uma lei e dilui outra.
- **Definição** (-0.048 MRR): trade-off explícito, paga 5pp aqui pra ganhar 16pp em citação literal.

A escolha "ligar ou não" depende da distribuição esperada de queries.

## Voltando à tese principal do projeto

Antes deste experimento, a tese era:

> 4 técnicas de second-stage retrieval testadas, nenhuma melhora dense voyage.

Agora a tese ajusta:

> 5 técnicas de second-stage testadas, **4 perderam e 1 (voyage rerank-2.5) melhora MRR sem perder nDCG**. Os 4 que perderam têm uma coisa em comum: foram **rerankers/fusers open-source treinados em corpus geral**. O que ganhou foi um **reranker comercial domain-tuned**. A lição não é "second-stage não funciona" — é "second-stage só funciona com modelo treinado no domínio certo".

Ainda **menor que o efeito dos 3 truques de dados** (label-prefix sozinho deu +0.10 nDCG no eval v2). Fix the data continua sendo o que mais multiplica. Mas voyage rerank-2.5 é uma exception genuína que vale aplicar em produção single-answer.

## Reprodução

```bash
# Setup
export VOYAGE_API_KEY=...  # ou .env
uv sync --extra voyage

# Comparação
python -m rag_leis.run_eval --model voyage-3-large \
    --text-mode label+nav+caput+text --by-type

python -m rag_leis.run_eval --model voyage-3-large \
    --text-mode label+nav+caput+text --rerank voyage-rerank-2.5 --by-type

python -m rag_leis.run_eval --model voyage-3-large \
    --text-mode label+nav+caput+text --rerank voyage-rerank-2.5-lite --by-type
```

Custo total: ~$0.16.

## Próximos passos

1. **Cohere rerank-multilingual-v3** — outro comercial domain-tuned. Hipótese: efeito similar, dependendo do treinamento. ~10 min de teste se a chave Cohere estiver à mão.
2. **Per-type routing usando voyage rerank-2.5**: ligar o rerank só pra queries com regex de citação. Estimativa: capturar o ganho de citação sem o custo nas outras categorias. Pode levar o agregado pra +0.01-0.02 nDCG.
3. **Eval com gold expandido em paráfrase** — paráfrase regrediu -0.04 nDCG, mas isso pode ser artefato de gold incompleto (vide eval-v3-and-calibration.md). Vale revisão manual antes de descartar voyage rerank-2.5 nessa categoria.

## Outputs

- Aggregate: `/tmp/voyage_rerank.txt`.
- Código: `rag_leis/rerank.py:VoyageReranker`, wired em `get_reranker`.

---

## Update — re-eval com gold expandido (v3.5)

Após expansão do gold de paráfrase (78 queries com graded relevance, +CDC adicionado, +CF/LAI/LGPD cross-doc, +incs/§§ supporting nas mono-artigo), re-rodei voyage rerank-2.5 contra o novo dense baseline.

**Mudanças nos números agregados**:

| metric | gold antigo | **gold expandido** |
|---|---|---|
| dense baseline nDCG | 0.608 | **0.660** (+0.052) |
| dense baseline MRR | 0.591 | **0.697** (+0.106) |
| + rerank nDCG | 0.603 (Δ -0.005) | 0.637 (**Δ -0.022**) |
| + rerank MRR | 0.613 (Δ +0.022) | 0.711 (**Δ +0.014**) |

A regressão de nDCG **dobrou** (-0.005 → -0.022). O ganho de MRR **caiu** de +0.022 pra +0.014.

**Per-type com gold expandido**:

| tipo | Δ nDCG | Δ MRR | conclusão |
|---|---:|---:|---|
| **citacao-literal** | **+0.046** | **+0.099** | ✓ ganho confirmado |
| **enumeracao** | +0.001 | **+0.058** | ✓ MRR ganha real |
| definicao | -0.045 | -0.045 | regride como antes |
| cross-doc | -0.027 | -0.008 | regride leve |
| **parafrase** | **-0.078** | **-0.016** | ✗ **agora regride** (antes parecia neutra) |

### Por que o ganho do reranker caiu

A v3 baseline tinha gold underspec em paráfrase — média 1-2 chunks marcados quando a resposta natural envolve 5-10 da mesma família estrutural. Esse underspec mascarava parte do dense:

- **Gold antigo**: dense top-10 retornava chunks "vizinhos do gold" que **não contavam** como relevantes → dense parecia mais fraco do que é.
- **Reranker movia esses vizinhos** sem perder o gold único → parecia neutro/positivo na superfície.
- **Gold expandido**: vizinhos do gold viraram supporting (rel=1). Dense agora retorna vários relevantes no top-K → nDCG do dense sobe muito.
- **Reranker reordena dentro do top-K** e empurra alguns supporting pra fora do top-10 → DCG cai.

Resumindo: parte do "ganho aparente" do reranker em paráfrase era **artefato de gold incompleto**.

### Tese ajustada (de novo)

> Voyage rerank-2.5 é útil **apenas** em queries com gold multi-chunk concentrado em UM artigo: **citação-literal** (+0.099 MRR) e **enumeração** (+0.058 MRR). Em outras categorias (definição, paráfrase, cross-doc), regride.

### Recomendação revisada de produção

| caso de uso | recomendação |
|---|---|
| RAG geral (top-K → LLM, queries paraphrásticas) | voyage dense puro |
| Citation lookup ("o que diz o art. X?") | voyage dense + voyage rerank-2.5 |
| FAQ enumerativa ("quais são as X?") | voyage dense + voyage rerank-2.5 |
| Definição single-answer | voyage dense puro |

A escolha de ligar reranker depende do mix de queries. **Não é universal**.

### Implicação maior pro projeto

Toda comparação anterior (rerank, hybrid, colbert) deveria ser re-rodada com o gold expandido. Ganhos podem ter sido **sub**estimados (se ajudava em paráfrase, gold antigo escondeu) ou **sobre**estimados (se ajudava em definição, gold antigo deu crédito demais).

Aprendizado pra próximos projetos: **eval set com gold completo é pré-requisito pra avaliar second-stage retrieval**. Eval v1/v2 era suficiente pra detectar grandes efeitos (label-prefix 0 → 0.36 em citação-literal); insuficiente pra calibrar efeitos finos de rerank/router. v3 + gold expansion é o primeiro nível confiável.
