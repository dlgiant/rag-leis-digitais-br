# Plano — expansão do eval set (v2)

Branch: `eval/queries-v2`. Data: 2026-05-13.

## Motivação

O eval set atual (`eval/queries.yaml`, 25 queries, relevância binária) está dando sinal — conseguimos comparar 4 representações × 2 embeddings × 3 rerankers × 3 fusões. Mas três limitações apareceram nos experimentos:

1. **Volume baixo**: 25 queries é pouco para detectar segmentos. A análise per-query do reranker mostrou que rerankers ajudam em 2-3 queries e atrapalham em 8-12 — com mais queries, esses subgrupos viram estatística confiável.
2. **Sem tipagem**: a hipótese central que ficou em aberto no estudo de hybrid RRF é "sparse complementa em queries de citação literal e atrapalha em queries paráfrase". Sem rótulos por tipo, não há como testar essa decomposição.
3. **Relevância binária mascara o trade-off caput-prefix**: vimos que caput-prefix subiu nDCG/Recall e baixou MRR. Com gold gradado (core vs. supporting), podemos medir se o caput "ajuda a pegar os irmãos certos" sem confundir com "atrapalha o top-1".

## As três maneiras de expandir

### 1. Volume + variedade tipada (25 → ~50 queries)

Dobrar o set. Critério não é "mais", é **balanço por tipo**. Adicionar campo `type:` em cada query com um destes 5 valores:

- `definicao` — "o que é X?" (gold normalmente é um inciso isolado tipo `art5;inc1`)
- `enumeracao` — "quais são as X?" (gold normalmente é caput + todos os incisos do artigo)
- `citacao-literal` — menciona número de artigo direto ("o que diz o art. 18 da LGPD?")
- `parafrase` — pergunta sem termos canônicos da lei ("posso ser hackeado e a lei me protege?")
- `cross-doc` — resposta canônica vive em ≥2 leis (ex.: "prazos de retenção de logs" cobre Marco Civil + LGPD)

Alvo: ~10 queries de cada tipo, totalizando 50. Distribuição atual está enviesada pra `enumeracao` (~12) e `citacao-literal` (poucas).

### 2. Relevância gradada (0/1 → 0/1/2)

Trocar `relevant: [urn1, urn2, ...]` por:

```yaml
relevant:
  core:        # rel = 2: o chunk que ALGUÉM esperaria como resposta primária
    - urn:...
  supporting:  # rel = 1: relevante mas auxiliar (irmão estrutural, artigo conexo)
    - urn:...
```

Atualizar `ndcg_at_k` em `eval_harness.py` para usar `2^rel - 1` (DCG gain) em vez de 1/0. MRR e Recall continuam binários (consideram tudo em `core` ∪ `supporting` como relevante).

Isso resolve o falso negativo onde, por exemplo, art.18,§1 da LGPD aparece em vez do caput art.18: hoje é "errado", deveria ser "parcialmente certo". E preserva o sinal de que o caput é a resposta canônica.

### 3. Cobertura por lei e por chunk-type

Garantir distribuição:

- **Por lei** (Tier-1): cada lei com ≥4 queries. Hoje LGPD domina (~12 queries), Lei do Software e Lei Carolina Dieckmann têm 1-2.
- **Por chunk-type**: ~30% artigo (caput), ~30% inciso/alínea, ~20% parágrafo, ~10% itens deep-nested, ~10% multi-level (enumeração inteira).

Ajuda a (a) testar o parser em chunks que raramente vemos no eval (items, decretos regulamentadores), (b) detectar regressões específicas por nível.

## Backwards compat

`load_queries` precisa aceitar tanto o formato antigo (`relevant: [...]`) quanto o novo (`relevant: {core: [...], supporting: [...]}`). Detecta o tipo e converte; queries antigas viram `core` por padrão.

## Sequência sugerida

1. Atualizar `load_queries` em `eval_harness.py` com schema novo + back-compat.
2. Atualizar `ndcg_at_k` para suportar relevância gradada.
3. Adicionar `--by-type` flag em `run_eval.py` que imprime metrics por tipo de query.
4. Escrever as ~25 queries novas. Anotar em uma planilha ou rodando `--show-misses` para gold-URN typos.
5. Rodar a v2 do eval em todas as configurações testadas até hoje (voyage × 4 modos × {dense, rerank, hybrid}) e comparar com v1 — sanity check que os números antigos batem aproximadamente.
6. Análise: per-type metrics. Especial atenção em **sparse complementaridade** (`parafrase` vs `citacao-literal`).

## Critérios de "pronto"

- 50 queries, distribuição balanceada por tipo e por lei (sanity check em script).
- Relevância gradada onde fizer sentido (não obrigatória pra queries de definição com gold único).
- `run_eval --by-type` rodando e produzindo tabela.
- Eval v1 reproduzível (manter o schema antigo carregável, queries antigas migráveis 1:1).

## Não fazer agora

- Não automatizar geração de queries com LLM. Eval set tem que ser curado, não sintético — synthetic queries têm distribuição diferente de queries humanas e enviesam métricas.
- Não trocar de framework (ranx, BEIR, etc). O harness atual é suficiente; trocar gera ruído pro pouco benefício.
- Não introduzir hard-negatives explícitos (gold complement). Pode vir depois quando tiver classificador de queries.
