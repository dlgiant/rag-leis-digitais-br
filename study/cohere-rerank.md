# Cohere rerank — comercial não basta

Branch: `experiment/voyage-rerank` (mesmo experimento). Data: 2026-05-13.

## TL;DR

Voyage rerank-2.5 quebrou o padrão de "todos os second-stage rerankers regridem" — foi o primeiro a melhorar MRR neste corpus. Hipótese natural: **rerankers comerciais domain-tuned funcionam onde os open-source falham**.

Testei a hipótese contra Cohere — outro rerank comercial, com versões `rerank-multilingual-v3.0` (treinado pra multilíngue) e `rerank-v3.5` (mais recente). **Hipótese falsificada parcialmente**:

| pipeline (78 queries v3) | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|
| voyage dense (baseline) | **0.608** | **0.856** | **0.591** |
| + voyage rerank-2.5 | 0.603 (-0.005) | 0.856 | **0.613 (+0.022)** ✓ |
| + cohere rerank-v3.5 | 0.538 (-0.070) | 0.856 | 0.510 (-0.081) ✗ |
| + cohere rerank-multilingual-v3.0 | 0.487 (-0.121) | 0.856 | 0.466 (-0.125) ✗ |

Cohere é regressão clara em ambas as variantes. **De 6 second-stage rerankers testados no projeto (3 open + 3 comerciais), apenas voyage rerank-2.5 ganha em alguma métrica.**

## A pista que Cohere v3.5 deixou

Olhando per-type, Cohere v3.5 (a versão mais recente) tem o **mesmo perfil de ganho que voyage rerank-2.5** em citação literal:

| tipo | voyage rerank-2.5 Δ nDCG | cohere v3.5 Δ nDCG |
|---|---:|---:|
| **citacao-literal** | **+0.098** | **+0.099** |
| enumeracao | +0.006 | -0.064 |
| definicao | -0.048 | -0.125 |
| cross-doc | -0.026 | -0.123 |
| parafrase | -0.042 | -0.125 |

Os dois entendem que "Art. X" é um identificador categórico — sobem citação literal **igualzinho**. A diferença é o que eles fazem com as outras queries:

- **Voyage rerank-2.5**: regride suavemente (-3 a -5pp) nas outras 4 categorias.
- **Cohere v3.5**: destrói (-12pp em definição, paráfrase, cross-doc).

Voyage tem **melhor preservação dos chunks que dense já acertou**. Cohere reordena ruidosamente quando não tem sinal forte.

## Multilingual v3.0 é ainda pior

O modelo Cohere "multilingual" (v3.0, mais antigo) tem regressão maior:

| tipo | dense | + cohere mult-v3.0 | Δ nDCG |
|---|---:|---:|---:|
| citacao-literal | 0.483 | 0.432 | -0.051 |
| cross-doc | 0.450 | 0.245 | **-0.205** |
| definicao | 0.825 | 0.719 | -0.106 |
| enumeracao | 0.695 | 0.620 | -0.076 |
| parafrase | 0.491 | 0.309 | **-0.182** |

Curiosamente nem ajuda em citação literal — o modelo multilingual parece otimizar pra cobertura ampla de idiomas, não pra precisão em domínios técnicos.

A versão `v3.5` (sem o "multilingual" no nome) é melhor pra português jurídico que a `multilingual-v3.0`. Lição lateral pra escolha de modelo: "multilingual" no nome ≠ otimizado pro seu idioma específico.

## Por que voyage rerank-2.5 é diferente

Não temos visibilidade do training data de nenhum dos dois, mas a evidência sugere que voyage rerank-2.5 tem **calibração específica pra paráfrase em corpus técnico** que Cohere não tem.

Hipóteses (não verificáveis sem internals):

1. **Voyage incluiu corpus jurídico/contratual** com proporção alta no treinamento. A aquisição da Voyage por MongoDB em 2025 reforçaria foco em uso enterprise, onde contratos/legal são caso de uso forte.
2. **Cohere otimizou pra queries de RAG genérico** (web/wiki). Excelente em casamento de facts, mas ruidoso em queries paraphrásticas técnicas.
3. **Voyage tem cabeça de scoring melhor calibrada** — quando sinal de relevance é fraco, prefere manter a ordem do dense em vez de re-rankear ruidosamente. Cohere "tenta" sempre.

A última é a hipótese mais útil pra escolher reranker em geral: **modelo que prefere "no-op" quando confidence é baixa** > modelo que sempre opina.

## Custo

Cohere rerank é mais caro que voyage:
- Voyage rerank-2.5: $0.05/1K docs.
- Cohere rerank-v3.5: $2/1K searches (1 search = 1 query + N docs). Em 78 queries × 20 docs, ~$0.16.

Custo similar pro experimento, mas Cohere escala pior — em produção com 1K queries/dia, voyage = ~$1/dia, Cohere = ~$2/dia.

E mesmo no preço maior, Cohere perde nas métricas. Pra este corpus, sem dúvida.

## Tese ajustada (de novo)

> **De 6 second-stage retrievers testados** — 3 open-source (bge-m3, jina-v2, bge-gemma) e 3 comerciais (voyage rerank-2.5, voyage rerank-2.5-lite, cohere rerank-multilingual-v3.0, cohere rerank-v3.5) — **apenas voyage rerank-2.5 melhora MRR sobre voyage dense puro**. Domain-tuning comercial é necessário mas não suficiente; a calibração específica do voyage rerank-2.5 (preservar onde dense acerta) é o diferencial.

## Implicação prática

Pra produção em corpus jurídico-pt-br + queries paraphrásticas + dense voyage:

1. **Default**: voyage dense puro.
2. **Se MRR/single-answer importa**: + voyage rerank-2.5 (ganha +0.022 MRR, perde 0.005 nDCG).
3. **Não usar Cohere** neste setup. Mesmo a versão nova v3.5 regride 7pp nDCG.

A escolha de reranker comercial **não é genérica**. Tem que medir.

## Reprodução

```bash
export COHERE_API_KEY=...  # cohere.com → tier gratuito tem 1K calls/min
uv pip install cohere

python -m rag_leis.run_eval --model voyage-3-large \
    --text-mode label+nav+caput+text --rerank cohere-rerank-v3.5 --by-type

python -m rag_leis.run_eval --model voyage-3-large \
    --text-mode label+nav+caput+text \
    --rerank cohere-rerank-multilingual-v3.0 --by-type
```

Custo total: ~$0.32 em créditos Cohere.

## Outputs

- `/tmp/cohere_rerank.txt`.
- Código: `rag_leis/rerank.py:CohereReranker` (modelos suportados: `cohere-rerank-multilingual-v3.0`, `cohere-rerank-v3.5`, `cohere-rerank-english-v3.0`).
