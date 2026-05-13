# RAG sobre leis digitais brasileiras — o trajeto técnico

Documento-mãe das decisões e achados do projeto. Cada seção aponta pra um ou mais docs específicos em `study/` ou pra branches no remote.

---

## Visão geral

O projeto monta um **retriever sobre 11 leis digitais brasileiras** (LGPD, Marco Civil, Lei do Software, Direito Autoral, LAI, Código Penal, Constituição, decretos regulamentadores). 5937 chunks no Tier 1 do corpus, parseados via Planalto+LexML, indexados em embeddings densos.

Goal: aprender e documentar **o que efetivamente melhora retrieval em corpus jurídico estruturado pt-br** e o que parece bom no papel mas não rende.

Spoiler: as melhorias **vieram quase todas da camada de dados** (como o chunk é formatado pra indexação), não da camada de modelo (qual embedding, qual reranker, qual segunda etapa). Esse é o ponto que vale o post.

---

## A tese, em uma frase

> **Quatro intervenções de "second-stage retrieval" testadas (rerank, hybrid sparse, hybrid ColBERT, gated router) somam zero ganho agregado. Três intervenções de "primeira-stage representation" (nav-prefix, caput-prefix, label-prefix) somaram +0.15 nDCG. Fix the data, not the model.**

---

## O retriever final (estado em 2026-05-13)

```
chunks Tier-1 (5937)
    │
    ▼
formato indexado: "Art. 7, IX :: II DO TRATAMENTO > I Dos Requisitos ::
                   O tratamento de dados pessoais somente poderá ser realizado
                   nas seguintes hipóteses: [texto do inciso]"
    │
    ▼
voyage-3-large embedding (cosine, top-K=20)
    │
    ▼
top-K chunks retornados ao LLM
```

Componentes:

1. **Parser hierárquico** com 5 níveis (artigo→§→inciso→alínea→item), separando o texto legal dos `notes` (alterações, vetos).
2. **Surface form indexado** = label da citação + breadcrumb nav + texto do caput ancestral + texto do próprio chunk. Tudo numa string só.
3. **Voyage-3-large** como embedding (BGE-M3 testado como baseline open-weight).
4. **Sem reranker, sem hybrid, sem router.** Cada um foi testado e perdeu.

Métricas na eval v3 (78 queries tipadas):

| metric | valor |
|---|---:|
| nDCG@10 | 0.608 |
| Recall@20 | 0.856 |
| MRR@10 | 0.591 |

Por tipo de query:

| tipo | n | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|---:|
| definicao | 20 | 0.825 | 1.000 | 0.769 |
| enumeracao | 15 | 0.695 | 0.827 | 0.782 |
| citacao-literal | 15 | 0.483 | 0.762 | 0.448 |
| parafrase | 16 | 0.491 | 0.859 | 0.402 |
| cross-doc | 12 | 0.450 | 0.764 | 0.483 |

Em "fácil" (definição) → 100% recall, MRR 0.77. Em "difícil" (paráfrase) → recall 86% mas MRR 0.40 (gold provavelmente incompleto pra essa categoria — o retriever tá encontrando chunks semanticamente válidos mas não-marcados).

---

## O trajeto — 7 fases

### Fase 1 — Corpus e parsing

**O que foi feito**: identificação dos Tier-1 documentos (11 leis core de digital), fetcher async via Planalto+LexML, parser HTML hierárquico que respeita estrutura LCP-95 (Lei Complementar nº 95/98 que define como leis brasileiras são organizadas).

**Decisões não-óbvias**:
- Parser separa `text` (norma vigente) de `notes` (alterações, vetos) — chunks indexados não contêm "este parágrafo foi alterado pela Lei X de Y".
- Item level adicionado depois de detectar que LGPD art. 11, II tem alíneas com sub-items (ali-a, ali-b...).
- 5 níveis de hierarquia mantidos em metadata: artigo / parágrafo / inciso / alínea / item.

**Outputs**: `data/chunks/tier-1/*.jsonl`, ~5937 chunks após filtrar revogados/vazios.

Doc: `study/corpus-tier-1-nucleo.md`, `study/lexml-urn-spec-resumo.md`.

### Fase 2 — Eval harness e baseline

**O que foi feito**: harness em `rag_leis/run_eval.py` com 4 text modes (text, nav+text, caput+text, nav+caput+text — só os 3 primeiros nesta fase) e 2 embedders (BGE-M3 open + Voyage-3-large API). Métricas: nDCG@10, Recall@20, MRR@10. Cache de índices em `.npz`.

**Eval set inicial**: 25 queries binárias cobrindo LGPD + Marco Civil + Software + LAI + Carolina Dieckmann.

**Primeiro resultado interessante**: trocar text mode de `text` pra `nav+text` (adicionar capitulo/secao no surface form) sobe BGE-M3 de 0.460 → 0.533 nDCG. **Representação > modelo** já apareceu aqui.

Doc: `SUMMARY-DAY2.md`.

### Fase 3 — Caput-prefix

**Hipótese**: chunks de inciso/alínea são curtos demais isoladamente. "a soberania;" (CF art. 1, I) não casa com "quais são os fundamentos da República?" porque o caput diz "tem como fundamentos:".

**Intervenção**: walk-up `parent_partition` no loader, concatenar o caput dos ancestrais como prefix do chunk indexado.

**Resultado** (voyage, 25 queries):

| mode | nDCG | Recall | MRR |
|---|---:|---:|---:|
| text | 0.640 | 0.717 | 0.801 |
| nav+text | 0.667 | 0.774 | 0.811 |
| caput+text | 0.703 | 0.834 | 0.728 |
| **nav+caput+text** | **0.713** | **0.834** | **0.730** |

**Tradeoff surfacing**: nDCG e Recall sobem (esperado), **MRR cai** (-7pp). Adicionando o caput aos chunks de inciso, todos os irmãos do mesmo artigo ficam semanticamente parecidos — o conjunto top-k melhora (recall ↑), mas o 1º colocado fica mais aleatório entre siblings (MRR ↓).

Lição: caput-prefix é "select better" pra recall e nDCG mas "select more confused" pra MRR. Pra RAG (top-K vai pro LLM), nDCG é a métrica certa. Pra FAQ single-answer, considere `nav+text` apenas.

Doc: `study/rerank-comparison.md` (seção "Update — testando a hipótese 'fix the data'").

### Fase 4 — Second-stage retrieval (4 tentativas)

Quatro experimentos, todos pelo mesmo motivo: ver se a regressão de MRR pode ser corrigida por uma camada extra após o dense.

#### 4a. Reranker cross-encoder

3 rerankers testados: `bge-reranker-v2-m3`, `jina-reranker-v2-base-multilingual`, `bge-reranker-v2-gemma` (2B params).

**Todos pioraram voyage** (text mode, 25 queries):
- bge-m3: -0.14 nDCG, -0.18 MRR
- jina: -0.17 nDCG, -0.23 MRR
- gemma: -0.20 nDCG, -0.29 MRR — **quanto maior o reranker, pior**

Por quê: rerankers cross-encoder fazem casamento token-level. Em corpus legal, o sinal certo está no **caput** que é deliberadamente vago lexicamente ("As seguintes hipóteses são:") — não tem os tokens da query. Cross-encoder treinado em web QA é adversarialmente desalinhado.

Doc: `study/rerank-comparison.md`.

#### 4b. Hybrid sparse + dense via RRF

BGE-M3 emite sparse (lexical_weights) no mesmo forward. Testamos:
- BGE-M3 dense + sparse via RRF
- Voyage dense + BGE-M3 sparse via RRF (cross-model)
- Voyage dense + BM25 via RRF
- Versões weighted (dense×3)

**12 configurações × negative**: melhor caso foi -0.04 nDCG vs voyage dense puro. Em nav+caput+text, sparse fica especialmente fraco (caput compartilhado entre irmãos arruina diferenciação token).

Por quê: sparse e dense neste corpus encontram **os mesmos relevantes** e erram **os mesmos irrelevantes**. Sem complementaridade, RRF dilui em vez de complementar.

Doc: `study/hybrid-rrf.md`.

#### 4c. Label-prefix (data layer, não retrieval)

Aqui o estudo virou. V2 do eval (47 queries tipadas) revelou que **citação-literal era um buraco total**: 0.000 nDCG, 0.013 Recall em 8/8 configurações testadas.

Causa: o número do artigo ("Art. 7") **não estava em lugar nenhum** do surface form indexado. O `label` do chunk só vivia no JSONL; nem nav nem caput o continham. Query "art. 7 da LGPD" → não tinha nada pra casar.

Fix: walk-up `parent_partition` e juntar labels — chunk indexado vira "Art. 7, IX :: [nav] :: [caput] [text]".

**Resultado**:
- citacao-literal nDCG: 0.000 → 0.356 (+0.36 absoluto)
- citacao-literal Recall@20: 0.013 → 0.710 (+0.70!)
- Agregado: +0.047 nDCG, +0.103 Recall

5 linhas de código. Maior ganho do projeto. **Outra vez: fix the data, not the model.**

Doc: `study/label-prefix-result.md`.

#### 4d. ColBERT (late interaction)

BGE-M3 também emite vetores ColBERT. Testamos MaxSim scoring (Khattab & Zaharia 2020) com:
- ColBERT sozinho vs BGE-M3 dense
- Voyage dense + BGE-M3 ColBERT via RRF

**ColBERT sozinho tem complementaridade clara por tipo**:
- citacao-literal Recall@20: dense 0.26 → colbert 0.48 (+0.22)
- cross-doc nDCG: dense 0.26 → colbert 0.33 (+0.07)
- parafrase nDCG: dense 0.21 → colbert 0.31 (+0.10)
- definicao/enumeracao: regride -0.04/-0.05

**RRF de voyage+colbert ainda não bate voyage só** (-0.04 nDCG). Mesmo padrão: ganha num tipo, perde em outro, net neutro.

Lição lateral: matmul de 32×1024 query tokens contra 300K doc tokens em fp16 é **~1000× mais rápido na GPU** que em numpy CPU. Sempre que o índice cabe na VRAM, mude.

Doc: `study/colbert-multivector.md`.

### Fase 5 — Eval expansion + calibração

Negative results acumulados mostraram que a eval set v1 (25 queries) e v2 (47) eram suficientes pra detectar grandes diferenças mas não pra calibração fina.

**V3**: 78 queries tipadas em 5 categorias:
- definicao (20) — "o que é X"
- enumeracao (15) — "quais são as X"
- citacao-literal (15) — "o que diz o art. X"
- parafrase (16) — linguagem natural sem termos canônicos
- cross-doc (12) — múltiplas leis na mesma resposta

Cobertura preenchida em CP, Direito Autoral, Constituição, Decreto 8771.

**Calibração**: extraído top1-top2 gap do voyage dense. Forte correlação com correctness:

| gap quartile | top-1 correct% |
|---|---:|
| Q1 (< 0.003) | 26% |
| Q2 (0.003–0.016) | 20% |
| Q3 (0.016–0.028) | 63% |
| Q4 (> 0.028) | 70% |

Threshold na mediana (gap=0.016) dividia queries 50/50 entre "trust" (67% correct) e "untrust" (23% correct). Estimativa back-of-envelope: rotear untrust pra fallback poderia subir nDCG agregado ~3-5pp.

Doc: `study/eval-v3-and-calibration.md`.

### Fase 6 — Gated router (a tentativa de unificar)

Implementação: voyage dense default; pra queries que casam `art\.?\s*\d+` AND com gap < 0.016, fundir com ColBERT-RRF.

**Resultado: +0.003 nDCG**. Dentro do ruído. Sweep em 4 configurações (citation-only, gap-only, threshold estrito, weight×10) confirma:

| config | nDCG | Δ |
|---|---:|---:|
| dense alone | 0.608 | — |
| citation+gap≤0.016 | 0.609 | +0.001 |
| citation-only | 0.610 | +0.002 |
| citation+gap≤0.005 estrito | 0.611 | +0.003 |
| gap-only (route by confidence só) | 0.588 | **-0.020** |

Por que a calibração mentiu: o "fallback ganha quando dense erra" assumiu que ColBERT-RRF acerta consistentemente em queries de gap baixo. Não acerta. ColBERT tem **alta variância por query**: às vezes salva (+0.6), às vezes destrói (-0.3). Média ≈ zero.

Lição estrutural: **calibração de UM retriever não basta pra decidir se OUTRO retriever vai ajudar**. Precisaria de calibração conjunta — saber não só "dense está incerto?" mas também "fallback vai discordar de forma útil?".

Doc: `study/router-results.md`.

### Fase 7 — Documentação consolidada (este doc)

Aqui.

---

## A tese revisitada

| intervenção | camada | Δ nDCG agregado | tipo de mudança |
|---|---|---:|---|
| nav-prefix | dados | +0.07 (bge-m3) | adiciona breadcrumb capítulo/seção |
| caput-prefix | dados | +0.04 (voyage v1) | adiciona texto do ancestral |
| label-prefix | dados | **+0.047 (v2)** | adiciona "Art. X" pra citação |
| rerank (3 modelos) | modelo | -0.10 a -0.20 | second-stage cross-encoder |
| hybrid sparse RRF | modelo | -0.04 a -0.08 | fusão dense+sparse |
| hybrid colbert RRF | modelo | -0.04 | fusão dense+colbert |
| gated router | modelo | +0.003 | seletivamente aplica fallback |

Padrão é cristalino:
- **Dados (3/3)**: todas as intervenções ganharam.
- **Modelo (4/4)**: todas perderam ou ficaram dentro do ruído.

Por quê:
1. **Corpus pequeno** (5937 chunks) com vocabulário denso e específico (jurídico-pt-br). Dense single-vector já captura bem o sinal — segundo retriever raramente acha algo novo.
2. **Queries homogêneas** em fonte (formuladas por uma pessoa, eval curada). Não há ruído de OCR ou variação linguística que justifique multi-vector / sparse.
3. **Gold às vezes incompleto** (paráfrase especialmente). Métricas confundem "ranking diferente" com "ranking pior" quando dois chunks são semanticamente equivalentes.
4. **A maior parte do retorno está em adicionar contexto que falta**, não em refinar similaridade. Caput, label, nav — cada um preenche uma lacuna semântica no chunk.

---

## Mapa de experimentos (resumo executivo)

| # | Branch | Hipótese | Resultado |
|---|---|---|---|
| 1 | `parser/hierarchical-lcp95` | parser hierárquico LCP-95 melhora chunks | ✓ baseline |
| 2 | `eval/harness-and-queries` | eval set + métricas detectam diferenças | ✓ harness viável |
| 3 | (mesmo) | nav+text > text | ✓ +7pp nDCG no BGE-M3 |
| 4 | `rerank/cross-encoder` | reranker melhora top-K | ✗ regressão sistemática |
| 5 | (mesmo) | maior reranker = melhor | ✗ inverso — gemma é o pior |
| 6 | `study/rerank-caput-followup` | caput-prefix sobe dense | ✓ +5pp nDCG, ↓ MRR |
| 7 | `experiment/hybrid-rrf` | sparse complementa dense | ✗ correlação alta de sinais |
| 8 | `experiment/label-prefix` | label "Art. X" fixa citação | ✓ +5pp nDCG, +10pp Recall |
| 9 | `experiment/colbert` | late interaction vs single-vector | ◐ complementar per-tipo, plano agregado |
| 10 | `eval/queries-v3` | eval maior + calibração | ✓ 78 queries, gap discrimina |
| 11 | `experiment/router` | calibração → router → ganho | ✗ variância de fallback dilui |

---

## Onde paramos

**Configuração de produção atual**: voyage-3-large + `label+nav+caput+text` + top-K=20, sem second-stage.

**Métricas de referência** (78 queries v3):
- nDCG@10: 0.608
- Recall@20: 0.856
- MRR@10: 0.591

**Custo**: ~5937 × $0.06/M tokens (re-embedding sob mudança de text mode) = poucos cents por re-indexação. Voyage subscription. Queries: API call (~ms), brutalmente barato.

**Quality bar atendida**: top-K traz pelo menos 1 chunk relevante em **85.7%** das queries. Pra RAG com LLM, isso é "bom o suficiente" — o LLM downstream tolera contexto ruidoso até onde sintetiza sobre 5-10 chunks.

**Limitações conhecidas**:
1. Paráfrase com gold incompleto: MRR aparente de 0.40 é provavelmente artefato. Revisão manual subiria essa métrica.
2. Citação-literal MRR 0.45: o retriever encontra a família de chunks certa (Recall 0.76) mas o 1º colocado raramente é o caput do artigo. Aceitável pra RAG, ruim pra FAQ single-answer.
3. Cobertura do corpus limitada a Tier-1 (11 leis). Tier-2 (ANPD resoluções, jurisprudência) ainda não parseado.

---

## Próximas direções (em ordem de retorno esperado)

1. **Expandir gold da paráfrase manualmente.** 16 queries, ~30 min de trabalho. Pode subir MRR dessa categoria de 0.40 → 0.65+ sem mexer no retriever.
2. **Tier-2 do corpus**: ANPD resoluções, decretos de proteção de dados. ~10 documentos. Estende cobertura sem mudar nada na pipeline.
3. **Reranker em-domínio comercial**: Cohere `rerank-multilingual-v3` ou Voyage `rerank-2.5`. Custa créditos. Os abertos falharam por mismatch de domínio — comerciais podem ter melhor cobertura jurídica. Ou podem falhar pelo mesmo motivo. ~1-2 horas de teste pra descobrir.
4. **Voyage-3-law-2** específico pra Common Law: testar se overshoot pra domínio de direito americano ainda ajuda pra português brasileiro. Hipótese: provavelmente pior que voyage-3-large genérico.
5. **Eval set 200+ queries**: necessário pra estatística confiável dentro de cada tipo. Trabalho de semana.
6. **Hybrid via late-fusion learnable**: em vez de RRF fixo, aprender pesos por tipo de query num pequeno classifier. Sofisticação extra, ganho marginal esperado dada a análise anterior.

---

## Os achados que viram post

Lista de "drafts" possíveis. Cada um é uma sessão deste doc.

1. **"Reranker piora retrieval (num corpus específico)"** — caso dos 3 rerankers. Material contrarian, fácil de defender com tabela. Citation: BGE-M3 paper, gemma model card.
2. **"Hybrid sparse+dense via RRF nem sempre funciona"** — 12 configurações testadas, todas perdem. Material pra audiência que acha que "hybrid é silver bullet". Citation: Cormack et al. 2009, BGE-M3 paper.
3. **"3 representation tricks que multiplicaram o nDCG (e os 4 retrieval tricks que falharam)"** — a tese central, dataset-first. Material pra LinkedIn/Medium/blog técnico.
4. **"Como calibração de confiança pode mentir"** — caso do router. Material denso, audiência técnica.
5. **"BGE-M3 vs Voyage-3-large em pt-br jurídico"** — comparação de embedders. Material referencial, útil pra quem está escolhendo modelo.
6. **"Eval set design: tipos de query e relevância gradada"** — meta-trabalho. Material pra audiência de ML practitioners.

---

## Apêndice — comandos pra reproduzir

```bash
# Setup
uv sync --extra bge --extra voyage --extra reranker
export VOYAGE_API_KEY=...  # ou .env

# Baseline atual (recomendado pra produção)
python -m rag_leis.run_eval --model voyage-3-large \
    --text-mode label+nav+caput+text --by-type

# Comparar com BGE-M3 (open-weight baseline)
python -m rag_leis.run_eval --model bge-m3 \
    --text-mode label+nav+caput+text --by-type

# Calibração de confiança
python -m rag_leis.confidence_analysis --model voyage-3-large \
    --text-mode label+nav+caput+text

# Router experimental (não recomendado em produção, mas instrutivo)
python -m rag_leis.router_eval --gate-mode citation-and-gap \
    --gap-threshold 0.016

# Comparações negativas (pra ver com seus olhos)
python -m rag_leis.run_eval --model voyage-3-large \
    --text-mode label+nav+caput+text --rerank bge-reranker-v2-m3 --by-type

python -m rag_leis.hybrid_eval --dense-model voyage-3-large \
    --text-mode label+nav+caput+text --dense-weight 3 --k 50

python -m rag_leis.colbert_eval --text-mode label+nav+caput+text \
    --rrf-dense-model voyage-3-large --rrf-dense-weight 3 --k 50
```

---

## Docs específicos (referências)

- `study/rerank-comparison.md` — 3 rerankers testados + caput-prefix + k=50
- `study/hybrid-rrf.md` — dense+sparse via RRF (12 configurações)
- `study/label-prefix-result.md` — fix da citação literal
- `study/colbert-multivector.md` — late interaction
- `study/eval-expansion-plan.md` — plano da v2/v3
- `study/eval-v3-and-calibration.md` — eval v3 + calibração de confiança
- `study/router-results.md` — router gated não bate o baseline
- `SUMMARY-DAY2.md` — eval harness inicial e baseline

E pro lado mais bruto:
- `eval/queries.yaml` — eval set v3 (78 queries tipadas, schema graded)
- `rag_leis/` — código todo
- `data/index/` — caches (.npz)
- `data/chunks/tier-1/` — corpus parseado

---

## Reconhecimento honesto

Tudo isto pra construir um retriever que **manda os mesmos chunks que voyage dense puro mandaria com label+nav+caput+text indexado**, mais 8 docs explicando porque a maioria dos truques que tentei não funcionou.

O retorno do projeto, em uma frase: **aprendi a confiar mais nos dados que nos modelos pra RAG em corpus técnico estruturado em pt-br.** O retriever final é o subproduto; o processo é o produto.
