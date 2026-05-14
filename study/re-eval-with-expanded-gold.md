# Re-eval de todos os second-stage com gold expandido

Branch: `experiments/re-eval-with-newgold`. Data: 2026-05-13.

## TL;DR

Após expandir o gold de paráfrase (78 queries com graded relevance, +CDC, cross-doc onde apropriado), re-rodei **todas** as técnicas de second-stage testadas no projeto. **Todas pioraram comparado ao baseline gold antigo**, e o sinal anterior de "alguns ajudam um pouco" se confirma como artefato de gold incompleto.

| pipeline | gold antigo Δ nDCG | **gold novo Δ nDCG** | gold antigo Δ MRR | **gold novo Δ MRR** |
|---|---:|---:|---:|---:|
| voyage rerank-2.5 (commercial) | -0.005 | -0.022 | +0.022 | **+0.014** ✓ |
| router (citation+gap=0.016) | +0.001 | **-0.008** | +0.000 | -0.020 |
| voyage + colbert RRF (3:1) | +0.001 | **-0.052** | -0.005 | -0.064 |
| voyage + BM25 RRF (3:1) | **+0.029** | **-0.111** | -0.011 | -0.120 |
| voyage + bge-sparse RRF (3:1) | -0.018 | -0.093 | -0.012 | -0.132 |
| Cohere rerank-v3.5 | -0.070 | -0.089 | -0.081 | -0.077 |
| bge-reranker-v2-m3 | -0.184 | -0.130 | -0.114 | -0.126 |
| jina-reranker-v2 | -0.246 | -0.108 | -0.231 | -0.128 |
| bge-reranker-v2-gemma | -0.274 | -0.273 | -0.286 | -0.296 |

Patterns:

1. **voyage + BM25 (3:1)** era o "achado positivo" mais limpo do projeto (+0.029 nDCG). **Virou regressão de -0.111 nDCG** — reversão de **14 pontos percentuais**.
2. **ColBERT RRF** era flat (~zero); virou regressão de -0.052 nDCG.
3. **Router** continua quase neutro (-0.008 nDCG); o ganho marginal de antes desapareceu.
4. **voyage rerank-2.5** continua sendo o ÚNICO que melhora MRR (+0.014, era +0.022). Resta como exceção.
5. **Open rerankers (bge-m3, jina-v2)** ficaram menos catastróficos (-0.13 ao invés de -0.18~-0.25), mas continuam regressões claras.
6. **Gemma e Cohere** quase não mudam — desalinhamento estrutural não responde ao gold.

## Por que o gold antigo escondia esses regressões

**Mecanismo**: gold antigo (v3 baseline) marcava 1-2 chunks por paráfrase quando a resposta natural envolvia 5-10 da mesma família estrutural. Resultado:

- Dense top-10 retornava muitos "vizinhos do gold" que não contavam como relevantes → dense aparecia mais fraco.
- Second-stage (rerank, RRF) reordenava esses vizinhos sem perder o gold único → parecia neutro/positivo.
- **Gold expandido**: vizinhos viraram supporting (rel=1). Dense agora retorna múltiplos relevantes no top-K → nDCG do dense sobe muito (0.608 → 0.660 = +5.2pp).
- Second-stage **reordena dentro do top-K** e empurra alguns supporting pra fora do top-10 → DCG cai.

Conclusão: parte do "ganho aparente" de várias técnicas era **dense underestimado pelo gold pobre**, não real adição de valor pelo second-stage.

## Detalhes por experimento

### Hybrid sparse + dense via RRF

| pipeline | gold antigo (47q) | gold novo (78q) |
|---|---|---|
| voyage dense baseline | 0.645 nDCG / 0.869 Rec / 0.635 MRR | 0.660 / 0.848 / 0.697 |
| sparse alone | 0.407 / 0.492 / 0.407 | 0.249 / 0.419 / 0.244 |
| BM25 alone | 0.413 / 0.603 / 0.414 | 0.210 / 0.364 / 0.221 |
| voyage + sparse (1:1) | 0.504 / 0.718 / 0.532 | 0.447 / 0.801 / 0.464 |
| voyage + sparse (3:1) | 0.590 / 0.778 / 0.601 | 0.567 / 0.852 / 0.565 |
| voyage + BM25 (1:1) | 0.569 / 0.767 / 0.595 | 0.444 / 0.782 / 0.478 |
| voyage + BM25 (3:1) | **0.637** / 0.783 / 0.691 | 0.549 / 0.836 / 0.577 |

Sparse alone caiu mais (0.41 → 0.25 nDCG) porque o gold expandido tem muitos chunks supporting que sparse não pega. Sparse acerta o "termo lexical certo" (1-2 chunks), mas erra os múltiplos relevantes ao redor.

BM25 (3:1) que era o melhor caso virou pior — RRF ainda funciona como média, e voyage dense puro agora é tão forte que qualquer fusão é diluição.

### ColBERT (late interaction)

| pipeline | gold antigo (47q) | gold novo (78q) |
|---|---|---|
| bge-m3 dense alone | 0.438 / 0.657 / 0.457 | 0.417 / 0.643 / 0.468 |
| bge-m3 colbert alone | 0.441 / 0.671 / 0.455 | 0.421 / 0.676 / 0.473 |
| voyage dense + colbert RRF (1:1) | 0.545 / 0.842 / 0.532 | (não testado equal weight novo) |
| voyage dense + colbert RRF (3:1) | 0.609 / 0.861 / 0.585 | 0.608 / 0.873 / 0.633 |

Aqui interessante: ColBERT alone (vs bge dense alone) ainda **complementa** marginalmente — Recall@20 sobe de 0.643 → 0.676 (+3pp), nDCG +0.4pp. Mas voyage + colbert RRF (3:1) regrediu mais que antes em nDCG.

Recall@20 do RRF (0.873) é maior que voyage dense alone (0.848). Mas nDCG cai porque o reordenamento move chunks supporting pra fora do top-10. **Trade-off explícito de recall vs ranking**.

### Router gated

| config | gold antigo (78q) | gold novo (78q) |
|---|---|---|
| dense baseline | 0.608 / 0.856 / 0.591 | 0.660 / 0.848 / 0.697 |
| router citation+gap | 0.609 / 0.873 / 0.585 | 0.652 / 0.865 / 0.677 |
| Δ | +0.001 / +0.017 / -0.006 | -0.008 / +0.017 / -0.020 |

Router preserva ganho de Recall@20 (+0.017 em ambos os golds). Mas nDCG e MRR pioram com gold novo. Recall melhora porque ColBERT puxa pra cima alguns chunks que dense errou; mas no top-10 o reranking introduz ruído.

10 queries roteadas em ambos os experimentos (mesma regex). O sinal interno (gap < 0.016 + citação) é o mesmo; o que mudou foi como o gold mede o efeito.

## Implicações para a tese

A tese revisada do projeto:

> **Com gold completo, TODAS as 4 técnicas de second-stage testadas regridem ou ficam neutras**. A única exceção é voyage rerank-2.5 (+0.014 MRR, mas -0.022 nDCG). Os "wins" e "neutros" anteriores eram artefatos de gold incompleto que escondia a força real do dense.

Implicação prática: voyage dense + label+nav+caput+text é a configuração de produção, **sem ambiguidade**. O custo da complexidade adicional de second-stage não é compensado por ganho.

Implicação metodológica: **eval set com gold completo é pré-requisito pra avaliar second-stage retrieval honestamente**. Eval set com gold underspec cria ilusão de ganho que desaparece com revisão.

## Custo do re-eval

- bge-m3 sparse rebuild: ~30s GPU
- bge-m3 colbert rebuild: ~3 min GPU
- 8 evals: ~2 min total (caches existentes)
- Total: ~5 min, $0 (caches reaproveitados, voyage dense já existia)

Pra qualquer projeto similar: gold expansion + re-run dos experimentos é um caminho de baixo custo pra honestidade — o ROI é informacional, não computacional.

## Outputs

- Aggregate: `/tmp/all_experiments_v2.txt`
- Caches rebuildados: `data/index/bge-m3__label+nav+caput+text.{npz,sparse.pkl,colbert.npz}`
- Reprodução: ver script anexo no commit message

## Próximos passos

1. **Atualizar `study/RETRIEVAL-JOURNEY.md`** com a versão final dos números.
2. **Atualizar `study/eval-v3-and-calibration.md`** notando que gold expansion foi o maior ganho.
3. **Reescrever drafts de post** (em `posts/`) com os números finais. O draft #1 ("fix the data, not the model") fica fortíssimo.
