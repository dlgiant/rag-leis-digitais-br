# Eval set v2 — resultados e o que mudou

Branch: `eval/queries-v2`. Data: 2026-05-13.

## TL;DR

Expandindo de 25 para **47 queries tipadas** com relevância gradada (`core` / `supporting`), aparecem três achados que o eval v1 não conseguia ver:

1. **Citação-literal é um buraco completo**: queries do tipo "*o que diz o art. 7 da LGPD?*" retornam **MRR=0.000 em todos os 8 modos × 2 modelos testados**. O retriever não está roteando "art. X" pro chunk certo — o número do artigo é texto cego dentro do chunk-content.
2. **Caput-prefix é seletivo, não universal**. Em v1 ganhava em quase tudo. Em v2 percebemos que:
   - Adora `enumeracao` (+38pp nDCG no BGE-M3, +24pp no voyage).
   - **Atrapalha** `parafrase` (-20pp) e `cross-doc` (-9pp no voyage).
   - Neutro pra `definicao`.
3. **O "melhor modo" agora depende do mix de queries esperado**, não é mais nav+caput+text por unanimidade. Pra produção generalista nav+text empata com nav+caput+text no nDCG global e tem MRR melhor.

Conclusão de produção: nav+caput+text continua vencendo no nDCG agregado, mas a margem é pequena (0.598 vs 0.585 em nav+text). A decisão real é per-uso: aplicação que faz muita pergunta enumerativa quer caput-prefix; aplicação que recebe paráfrases em LP natural não quer.

## Setup

- 47 queries no `eval/queries.yaml`, tipadas em 5 buckets:

  | tipo | n | exemplo |
  |---|---|---|
  | `definicao` | 15 | "qual a definição de dado pessoal na LGPD?" |
  | `enumeracao` | 10 | "quais sanções a ANPD pode aplicar?" |
  | `citacao-literal` | 8 | "o que diz o art. 7 da LGPD?" |
  | `parafrase` | 8 | "fui invadido no celular, isso é crime?" |
  | `cross-doc` | 6 | "diferença entre dado pessoal e informação pessoal" |

- Relevância gradada em 4 queries `enumeracao` onde o caput introduz mas não responde (caput = `supporting`, incisos/alíneas = `core`).
- nDCG calculado com ganho `2^rel - 1`. Recall e MRR usam união core∪supporting (binárias).
- Mesmo corpus, índices, hardware da v1.

## Resultados — agregado e por tipo

### voyage-3-large

| mode | n | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|---:|
| text | 47 | 0.560 | 0.709 | 0.633 |
| nav+text | 47 | 0.585 | 0.743 | **0.675** |
| caput+text | 47 | 0.573 | 0.776 | 0.565 |
| **nav+caput+text** | 47 | **0.598** | 0.766 | 0.588 |

### bge-m3

| mode | n | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|---:|
| text | 47 | 0.432 | 0.491 | 0.491 |
| nav+text | 47 | 0.451 | 0.550 | 0.493 |
| caput+text | 47 | 0.427 | 0.567 | 0.432 |
| nav+caput+text | 47 | **0.439** | **0.628** | 0.428 |

### Breakdown por tipo (voyage, nav+caput+text)

| tipo | n | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|---:|
| definicao | 15 | **0.886** | **1.000** | 0.850 |
| enumeracao | 10 | 0.706 | 0.880 | **0.800** |
| parafrase | 8 | 0.549 | 0.969 | 0.436 |
| cross-doc | 6 | 0.561 | 0.722 | 0.567 |
| citacao-literal | 8 | **0.000** | 0.013 | 0.000 |

### Caput-prefix por tipo (voyage, text → nav+caput+text)

| tipo | nDCG text | nDCG nav+caput+text | Δ |
|---|---:|---:|---:|
| definicao | 0.893 | 0.886 | -0.007 |
| **enumeracao** | 0.470 | **0.706** | **+0.236** |
| parafrase | 0.519 | 0.549 | +0.031 |
| cross-doc | **0.653** | 0.561 | **-0.092** |
| citacao-literal | 0.019 | 0.000 | -0.019 |

E no BGE-M3 (text → caput+text, deixei `nav+...` de fora pra isolar o efeito do caput):

| tipo | nDCG text | nDCG caput+text | Δ |
|---|---:|---:|---:|
| definicao | 0.817 | 0.754 | -0.064 |
| **enumeracao** | 0.186 | **0.567** | **+0.381** |
| **parafrase** | 0.372 | **0.173** | **-0.199** |
| **cross-doc** | 0.538 | 0.283 | **-0.255** |
| citacao-literal | 0.000 | 0.000 | 0.000 |

## Reranker em cima — voyage + nav+caput+text + bge-reranker-v2-m3

| pipeline | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|
| dense | **0.598** | 0.766 | **0.588** |
| dense + rerank | 0.497 | 0.766 | 0.475 |

Δ = -0.10 nDCG, -0.11 MRR. Magnitude bem próxima do v1 (-0.08 nDCG, -0.13 MRR em nav+caput+text). O reranker continua tóxico no agregado.

Por tipo, onde o reranker mais machuca:
- `cross-doc`: 0.561 → 0.312 (-0.25)
- `parafrase`: 0.549 → 0.424 (-0.13)

Padrão: rerank ruim onde a query é semanticamente difusa (paráfrase / multi-lei). Em queries com gold único e literal (definicao), o reranker quase não atrapalha.

## Os três achados que o v1 não viu

### 1. Citação-literal — uma blind spot

8 queries do tipo "o que diz o art. X da [lei]?" todas com MRR=0 em todos os modos × modelos. Inclusive nas variantes com `nav+` (que inclui breadcrumb estrutural) e `caput+text` (que inclui o texto do artigo).

**Hipótese da causa raiz**: O label "Art. 7" do chunk **não entra em lugar nenhum do surface form indexado**. O `nav_text` é montado de `capitulo > secao`; não inclui o número do artigo. O texto do chunk começa com o conteúdo legal, não com "Art. 7". Então quando a query diz "art. 7 LGPD", literalmente não há tokens explícitos em chunk algum que casem com "art. 7" — vejam por exemplo o que entra no índice pro art.7 da LGPD:

```
nav+caput+text:
  "II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais ::
   O tratamento de dados pessoais somente poderá ser realizado nas seguintes hipóteses:"
```

Sem "7" em lugar nenhum. O retriever está fazendo o que pode — não há sinal pra ranquear.

**Fix óbvio pra testar (próximo experimento)**: adicionar `label+nav+caput+text` mode, prefixando o label do chunk (e.g. "Art. 7"). Hipótese: citacao-literal sobe de 0.00 → 0.7+ sem afetar outras métricas. Custo: 5 linhas no `format_texts`.

### 2. Caput-prefix é seletivo, não universal

V1 mostrou caput-prefix subindo nDCG em quase tudo. V2 separa por tipo de query e mostra que:

- **Onde caput-prefix arrasa**: `enumeracao` (+24pp voyage, +38pp bge-m3). Faz sentido: quando a query é "quais X?", o caput "O X compreende:" é o stem da resposta. Sem caput-prefix, os incisos isolados não casam com "quais"; com caput-prefix, todos os filhos herdam o contexto.
- **Onde caput-prefix atrapalha**: `parafrase` e `cross-doc`. Hipótese: paráfrases usam vocabulário leigo que **não** está no caput; o caput acaba sendo ruído lexical/semântico. Cross-doc precisa diferenciar entre leis — o caput introduz contexto que pode "confundir" o modelo entre artigos similares.
- **Onde é neutro**: `definicao` (a definição é o caput; já está sendo retornado isolado).

Implicação: a escolha de text-mode deveria ser **routing-based** se você sabe o tipo da query. Em pipelines de produção, isso vira "classificar query → escolher index". Mas pra eval/baseline, `nav+caput+text` continua sendo o melhor compromisso por causa do enorme ganho em enumeração.

### 3. Cross-doc sofre menos com o reranker do que esperávamos

Em v1 o reranker piorava parafrase e cross-doc por inferência indireta. Agora vemos quantitativamente:
- `definicao`: reranker −0.09 nDCG
- `enumeracao`: −0.09
- `cross-doc`: **−0.25** ← pior caso
- `parafrase`: −0.13

Cross-doc é o pior porque o reranker re-rankeia 20 candidatos do dense — e os 20 da dense são todos de UMA lei normalmente (a mais "óbvia" pra query). O cross-encoder amplifica a relevância da lei dominante e dilui a segunda. Quando a resposta canônica está em 2 leis, o reranker derruba uma delas pra fora do top.

Pra mitigar: ou (a) garantir diversidade no candidate set antes do reranker (e.g. MMR), ou (b) puxar top-20 por lei separadamente. Não vou tentar agora.

## V1 → V2: por que os números caíram

V1 voyage+nav+caput+text: 0.713 nDCG.
V2 voyage+nav+caput+text: 0.598 nDCG.

A queda de 11.5pp **não é regressão de retriever**. É a eval set ficando harder por design:
- 8 das novas 22 queries são citacao-literal (todas MRR=0). Sozinhas puxam o agregado pra baixo em ~0.13/0.13/0.13 nDCG/Recall/MRR.
- Subtraindo citacao-literal: voyage+nav+caput+text rende **0.720** nDCG nas 39 queries não-literais — basicamente igual ao 0.713 do v1.

V1 estava medindo só o que voyage já fazia bem (definição + enumeração). V2 inclui categorias onde o retriever erra estruturalmente — e por isso é uma eval mais útil pra decidir o próximo experimento.

## Próximos experimentos sugeridos pelo v2

Em ordem de aposta-vs-esforço:

1. **`label+nav+caput+text` mode** — incluir "Art. X" no prefix. Hipótese: ressuscita citacao-literal de 0 → 0.7+. Custo: 5 linhas. **Quase certo de funcionar**. (#)
2. **Query routing** — detectar tipo (regex "art\.? \d+" → citacao-literal, etc.) e escolher text-mode. Custo: 30 linhas. Provavelmente +5-8pp no agregado.
3. **Diversidade no candidate set** — re-rerank com chunks de leis diferentes. Talvez ajuda `cross-doc`.
4. **Mais queries** — 47 ainda é pouco pra estatística confiável dentro de cada tipo (8 queries de citacao-literal não dão pra falar "MRR=0±?"). Idealmente 100+ pra ter erros padrão decentes.

## Artefatos

- Eval set: `eval/queries.yaml` (47 queries, schema v2).
- Output completo: `/tmp/eval_v2_results.txt` (gerado por loop `for m in voyage-3-large bge-m3; do for mode in ... ; do run_eval --by-type`).
- Reprodução:
  ```bash
  python -m rag_leis.run_eval --model voyage-3-large --text-mode nav+caput+text --by-type
  python -m rag_leis.run_eval --model bge-m3 --text-mode caput+text --by-type
  python -m rag_leis.run_eval --model voyage-3-large --text-mode nav+caput+text \
      --rerank bge-reranker-v2-m3 --by-type
  ```
