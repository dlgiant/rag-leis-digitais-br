# ColBERT (late interaction) — onde ajuda e onde não

Branch: `experiment/colbert`. Data: 2026-05-13.

## TL;DR

BGE-M3 emite vetores ColBERT (multi-vector) no mesmo forward pass. Testamos late interaction via MaxSim (Khattab & Zaharia 2020) em duas configurações:

1. **ColBERT sozinho** vs **BGE-M3 dense** (mesmo modelo, representação diferente).
2. **Voyage dense + BGE-M3 ColBERT via RRF** (cross-model hybrid).

Achado central: ColBERT tem **sinal complementar mensurável em queries de citação-literal e cross-doc**, mas **regride em paráfrase**. RRF equal-weight perde para voyage puro; RRF com peso 3:1 chega perto mas não passa. **Conclusão: late interaction faz sentido apenas com query-routing**, não como segunda etapa universal.

Mesmo padrão estrutural dos experimentos anteriores: rerankers, hybrid sparse, hybrid colbert — todos têm o mesmo defeito: melhoram um nicho e quebram outro. Voyage dense puro continua o operating point.

## Setup

- Cache ColBERT: `data/index/bge-m3__label+nav+caput+text.colbert.npz` (flat layout, ~1.2 GB fp16).
- Layout: `flat_vecs (sum_T, 1024)` + `offsets (N+1,)` para slicing per-doc.
- MaxSim scoring vetorizado: 1 matmul gigante na GPU (PyTorch fp16) + `np.maximum.reduceat` para max segmentado. ~ms por query.
- Eval: mesmas 47 queries tipadas do v2.

### Por que matmul na GPU importa

Primeira versão da minha implementação usava `numpy.matmul` em fp16 — caiu pra CPU porque numpy não tem matmul fp16 nativo. Resultado: ~10s por query × 47 queries = ~8 min. Migrando o tensor flat pra `torch.cuda.HalfTensor` e fazendo `q @ flat.T` no device direto: ms.

Lição lateral pro post: **quando o índice cabe na GPU (1.2 GB no nosso caso), não tem motivo pra ficar em CPU.** numpy parece "default fácil" mas paga 1000× em latência aqui.

## Resultados — ColBERT sozinho vs BGE-M3 dense

Mesmo modelo (BGE-M3), mesmo text-mode (label+nav+caput+text), mesma corpus.

| metric | dense | colbert | Δ |
|---|---:|---:|---:|
| nDCG@10 agregado | 0.438 | 0.441 | +0.002 |
| Recall@20 agregado | 0.657 | 0.671 | +0.013 |
| MRR@10 agregado | 0.457 | 0.455 | -0.002 |

Empate na média. Mas per-type:

| tipo | dense nDCG | colbert nDCG | Δ |
|---|---:|---:|---:|
| **cross-doc** | 0.264 | **0.330** | **+0.066** |
| **parafrase** | 0.213 | **0.314** | **+0.101** |
| **citacao-literal Recall@20** | 0.261 | **0.477** | **+0.216** |
| definicao | 0.720 | 0.680 | -0.040 |
| enumeracao | 0.586 | 0.536 | -0.050 |

ColBERT ajuda exatamente onde dense single-vector tinha mais problema: **queries com vocabulário misto (paráfrase) ou multi-domínio (cross-doc)**. Pra essas, casamento token-level resolve o que pooling para single-vector achata.

Atrapalha em definição/enumeração onde dense já fazia bem — late interaction adiciona ruído quando a query é objetiva o suficiente.

Notar: **Recall@20 da citação-literal quase dobrou** (0.26 → 0.48). MRR não melhorou (0.16 igual em ambos), então o chunk certo entrou no candidate set mas não no top-1. ColBERT está achando a categoria certa, errando o ranking dentro dela — mesma raiz do label-prefix.

## Resultados — Voyage dense + BGE-M3 ColBERT via RRF

Cross-model: voyage como dense backbone (estado da arte do projeto), bge-m3 colbert como sinal secundário.

| pipeline | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|
| **voyage dense (baseline)** | **0.645** | **0.869** | **0.635** |
| bge-m3 colbert | 0.441 | 0.671 | 0.455 |
| RRF (1:1) | 0.545 | 0.842 | 0.532 |
| **RRF (dense×3)** | 0.609 | 0.861 | 0.585 |

Mesmo padrão dos experimentos de hybrid sparse: RRF equal-weight perde 10pp; ponderação 3:1 a favor do dense chega perto mas não passa.

### Onde RRF(3:1) move o ponteiro

| tipo | voyage | RRF dense×3 | Δ nDCG |
|---|---:|---:|---:|
| **citacao-literal** | 0.356 | **0.384** | **+0.028** ✓ |
| cross-doc | 0.522 | 0.495 | -0.027 |
| definicao | 0.859 | 0.820 | -0.039 |
| enumeracao | 0.668 | 0.660 | -0.008 |
| **parafrase** | 0.595 | 0.461 | **-0.134** ✗ |

**Citação-literal MRR sobe de 0.299 → 0.362** (+6pp) — ColBERT está conseguindo desambiguar entre "Art. 7 da LGPD" e "Art. 7 da Constituição" porque vê os tokens "LGPD"/"Constituição" em janelas locais do passage. Voyage single-vector está enviesado pelo conteúdo semântico do chunk e perde essa pista categórica.

**Paráfrase desaba** (-13pp): ColBERT puxa pra cima chunks com casamento token-superficial. Quando query é "fui invadido no celular sem permissão, isso é crime?", ColBERT casa "celular"/"permissão" com chunks irrelevantes que mencionam os tokens. Voyage faz melhor porque entende a intenção semântica.

## O padrão que se repete

Três experimentos de second-stage retrieval, três regressões médias:

| experimento | aggregate Δ vs voyage dense |
|---|---|
| Reranker (bge-m3) | -0.10 nDCG |
| Hybrid sparse RRF (m3 / BM25, weighted) | -0.04 a -0.08 |
| ColBERT + RRF (dense×3) | -0.04 |

Em todos, **uma categoria de query melhora** (definição→paráfrase no reranker; citação-literal no ColBERT) e **outra piora pior** (cross-doc/paráfrase no reranker; paráfrase no ColBERT). O efeito médio nunca é positivo porque sempre tem víctima.

Isso aponta pra uma intervenção comum: **query routing**. Detectar o tipo de query e selecionar o pipeline ideal por tipo, em vez de aplicar uniformemente. Custo de implementação razoável (regex + heurística pra começar), ganho potencial: o melhor de cada experimento somado.

Esboço:

```python
def route(query: str) -> str:
    if re.search(r"art\.?\s*\d+", query, re.IGNORECASE):
        return "voyage+colbert_rrf"   # citacao-literal: colbert ajuda
    return "voyage_dense"             # default — domina nos outros tipos
```

Ganho esperado pelo eval atual:
- 8 citação-literal × (0.384 - 0.356) = +0.22 / 47 ≈ +0.005 nDCG agregado
- Outros 39 unchanged

Pequeno mas positivo. Pra valer a pena montar router, precisa eval set bem maior (100+ queries) ou outras heurísticas (e.g. paráfrase pode ser detectada por verbosity / ausência de termos técnicos).

## Decisão de produção

Manter **voyage-3-large + label+nav+caput+text** como retriever default. ColBERT vale a pena apenas se construirmos o router. Custo de armazenamento (1.2 GB pra ColBERT vs ~24 MB pra dense) também desfavorece — 50× mais memória pra ganho marginal sem routing.

## Onde ColBERT funcionaria de verdade

Pra quem está lendo isso pensando em adotar ColBERT: o trade-off não é universal. Funciona melhor quando:

- **Corpus tem alta variedade de vocabulário** (web data, multi-domínio). Aqui o corpus é homogêneo (jurídico-pt-br) e dense single-vector já captura bem o sinal.
- **Queries tendem a usar termos técnicos / nomes próprios** que precisam de casamento exato. Nossos eval queries são mais paráfrase que citação.
- **MRR é a métrica que importa mais que nDCG**. ColBERT é melhor em "uma resposta certa no top-1"; pra "k chunks relevantes pra contexto de LLM" (RAG), nDCG/Recall agregam — onde dense já vence.

## Próximos experimentos

1. **Query router** — regex + heurística pra escolher pipeline. Ganho marginal mas defensivo (corrigir citação-literal sem destruir paráfrase).
2. **Eval set maior** — 100+ queries pra ter erro-padrão decente dentro de cada tipo. Pode revelar segmentos onde ColBERT é dominante mesmo no agregado.
3. **Re-encodar com tokenizer custom** — pra um corpus tão específico, fine-tunar o tokenizer (ou pelo menos adicionar tokens jurídicos: "art", "inciso", "alínea") pode subir tanto dense quanto ColBERT. Mais caro.

## Artefatos

- Eval set v2: `eval/queries.yaml` (47 queries tipadas).
- Cache ColBERT: `data/index/bge-m3__label+nav+caput+text.colbert.npz` (~1.2 GB fp16, regenera com `--rebuild`).
- Código: `rag_leis/colbert_eval.py`, `rag_leis/embeddings.py` (métodos `embed_docs_colbert` / `embed_query_colbert`).
- Reprodução:
  ```bash
  # ColBERT alone vs BGE-M3 dense
  python -m rag_leis.colbert_eval --text-mode label+nav+caput+text --compare-dense --k 20

  # Voyage dense + ColBERT RRF
  python -m rag_leis.colbert_eval --text-mode label+nav+caput+text \
      --rrf-dense-model voyage-3-large --rrf-dense-weight 3 --k 50
  ```
