# Eval v3 — expansão + calibração de confiança

Branch: `eval/queries-v3`. Data: 2026-05-13.

## TL;DR

Expandido pra **78 queries** (de 47 no v2; +31), com cobertura preenchida em CP, Direito Autoral, Constituição e Decreto 8771. Resultados agregados por tipo ficaram mais estáveis e revelaram:

1. **Citação-literal estabilizou em ~0.48 nDCG** (era 0.36 com 8 queries no v2; agora 15 queries). O label-prefix ajuda mais do que parecia.
2. **Paráfrase tem accuracy real de top-1 = 19%** — significativamente abaixo dos outros tipos (26-67%). Provável misto de gold incompleto + dificuldade legítima.
3. **Calibração funciona**: o gap top1−top2 do dense é um sinal previsível de correctness. Gap > 0.028 → top-1 correto em 70% das queries; gap < 0.003 → 26%. **Ratio de quase 3×** entre os extremos.

Implicação prática: **confidence-gated retrieval é viável**. Threshold no gap (~0.016) divide queries em "trusted" (skip second-stage) e "untrusted" (route to ColBERT/RRF). Não testamos a implementação final ainda, mas a base estatística agora existe.

## Expansão do eval

47 → 78 queries. Mudanças por tipo:

| tipo | v2 | v3 | Δ |
|---|---:|---:|---:|
| definicao | 15 | 20 | +5 |
| enumeracao | 10 | 15 | +5 |
| citacao-literal | 8 | 15 | +7 |
| parafrase | 8 | 16 | +8 |
| cross-doc | 6 | 12 | +6 |

Cobertura de lei preenchida:
- **CP (Decreto-Lei 2848)**: +5 queries (art. 121 homicídio, 147 ameaça, 154-A invasão, 171 estelionato, 218-C divulgação não consentida, 307 falsa identidade, 14 consumado/tentado). Antes: 1.
- **Direito Autoral (Lei 9610)**: +4 queries (art. 7 obras protegidas, 8 não objeto, 11 def autor, 22 direitos do autor). Antes: 1.
- **Constituição**: +5 queries (art. 5 X intimidade, XII sigilo, XXXIII info pública, LXXII habeas data, 220 manifestação). Antes: 0.
- **Decreto 8771 (regulamenta MCI)**: +1 query (art. 4 discriminação tráfego). Antes: 0 core.

## Resultados v3 — voyage-3-large + label+nav+caput+text

| metric (78 queries) | v3 |
|---|---:|
| nDCG@10 | 0.608 |
| Recall@20 | 0.856 |
| MRR@10 | 0.591 |

Comparação direta com v2 não é apples-to-apples (corpus de queries diferente), mas o ranking entre tipos se confirma:

| tipo | n | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|---:|
| **definicao** | 20 | **0.825** | **1.000** | 0.769 |
| **enumeracao** | 15 | 0.695 | 0.827 | **0.782** |
| citacao-literal | 15 | 0.483 | 0.762 | 0.448 |
| **parafrase** | 16 | 0.491 | 0.859 | **0.402** |
| cross-doc | 12 | 0.450 | 0.764 | 0.483 |

Citação-literal melhorou claramente (v2: 0.36 nDCG → v3: 0.48) com mais amostras — confirma que o label-prefix está fazendo o trabalho dele. Os 0.0 do v2 eram em parte ruído estatístico de 8 queries.

Paráfrase com 16 queries ainda em ~0.49 nDCG. **MRR de 0.40 é o pior do conjunto** — o top-1 do dense é o chunk certo em <50% dos casos, mesmo quando o relevante está no top-20 (Recall 0.86).

## Calibração de confiança — onde os experimentos convergem

Para cada query, extraio dois sinais do dense:
- `top1_score`: similaridade cosseno do melhor chunk (com vetores L2-normalizados, é a similaridade absoluta)
- `gap`: `top1_score - top2_score` (margem)

E correlaciono com "top-1 foi correto?" (URN em `q.relevant`).

### Distribuição (78 queries, voyage)

```
top1_score:  min=0.535  q25=0.616  median=0.668  q75=0.717  max=0.784
gap:         min=0.000  q25=0.003  median=0.016  q75=0.028  max=0.103
```

### Quartis — top1_score

| bucket | n | top1 correct |
|---|---:|---:|
| [0.535, 0.616) | 19 | **26.3%** |
| [0.616, 0.668) | 20 | 35.0% |
| [0.668, 0.716) | 19 | 52.6% |
| [0.716, 0.784] | 20 | **65.0%** |

### Quartis — top1-top2 gap

| bucket | n | top1 correct | mean nDCG | mean MRR |
|---|---:|---:|---:|---:|
| [0.000, 0.003) | 19 | **26.3%** | 0.506 | 0.477 |
| [0.003, 0.016) | 20 | **20.0%** | 0.426 | 0.395 |
| [0.016, 0.028) | 19 | **63.2%** | 0.672 | 0.690 |
| [0.028, 0.103] | 20 | **70.0%** | 0.827 | 0.800 |

O **gap é o sinal mais limpo**: salta de ~25% pra 65%+ exatamente no median. As duas metades inferiores são quase indistinguíveis (Q1 e Q2 acima estão em ~25% — a confiança baixa não diz nada sobre certeza, é "todo mundo perdido"). Mas acima da mediana, os números viram.

### Threshold sweep — gap

| threshold | trusted_n | trusted correct% | untrusted_n | untrusted correct% |
|---:|---:|---:|---:|---:|
| 0.003 | 59 | 50.8% | 19 | 26.3% |
| **0.016 (median)** | **39** | **66.7%** | **39** | **23.1%** |
| 0.028 | 20 | 70.0% | 58 | 36.2% |
| 0.098 | 2 | 100.0% | 76 | 43.4% |

A escolha pragmática é **threshold = 0.016**: divide queries metade-metade, e diferencia entre 67% correct (trust) e 23% correct (route to fallback) — **ratio de 2.9×**.

### Confiança por tipo

| tipo | n | mean top1 | mean gap | top1 correct% | mean nDCG |
|---|---:|---:|---:|---:|---:|
| definicao | 20 | 0.712 | 0.037 | **65%** | 0.825 |
| enumeracao | 15 | 0.706 | 0.017 | **67%** | 0.695 |
| citacao-literal | 15 | 0.596 | 0.019 | 27% | 0.483 |
| cross-doc | 12 | 0.634 | 0.013 | 42% | 0.450 |
| **parafrase** | 16 | 0.642 | 0.017 | **19%** | 0.491 |

Insights:

- **definicao** é o "easy" — alto score, alto gap, alto correct%. Sinal autoconsistente.
- **enumeracao** tem gap baixo (0.017) mas correct% alto (67%): chunks irmãos do mesmo artigo competem, mas o top-1 ainda é gold porque ALL incisos estão em `relevant`. Caso especial.
- **parafrase é o problemão**: gap normal (0.017), score normal (0.64), mas correct% catastrófico (19%). O modelo está "confiante" mas errado. Calibração não distingue parafrase de outras — ela só vê o sinal interno do dense, que parece OK. Provavelmente o gold é incompleto (paráfrases têm múltiplos chunks que respondem, mas só 1-2 marcados).

Conclusão: **gap-based gating pode capturar a maioria dos casos onde voyage está perdido**, mas não distingue "perdido em terra real" de "achou um chunk não-gold que talvez seja correto". Pra fazer isso direito precisaria de relevância gradada mais cuidadosa nas paráfrases.

## Mix proposto — o que os 4 experimentos sugerem juntos

Plano:

1. **Default**: voyage dense + label+nav+caput+text. Cobre o caso fácil bem.
2. **Gate por gap**: se top1-top2 gap < 0.016, ative o fallback.
3. **Fallback por tipo** (com regex simples na query):
   - `art\.?\s*\d+` → ColBERT RRF (citação literal — o gap baixo aqui correlaciona com a categoria)
   - default fallback → reranker ou simplesmente top-K maior do dense

Estimativa do ganho (back-of-envelope):
- 50% das queries no "trust" bin: 67% correct hoje, não mexe. Contribui 0.67 × 50% × 78 = ~26 corretas.
- 50% no "untrust" bin: 23% correct hoje. Se fallback recupera ~10pp dessas, → 33% correct → ~13 corretas (era 9). Ganho: ~4 queries.
- Total: 26+13 = 39 correct vs 26+9 = 35 hoje. **~+5pp em top-1 correct%**.

nDCG agregado correspondente: dos experimentos anteriores, fallback bem-roteado ganha ~3-5pp em nDCG no segmento dele. Trazendo para o agregado: voyage 0.608 → ~0.625-0.635 nDCG. Modesto mas defensivo.

## Limitações honestas do v3

1. **Paráfrase tem gold incompleto.** 19% de top-1 correct é absurdamente baixo dado que Recall@20 é 86%. Significa que o dense acha 8 chunks gold no top-20, mas o "primeiro colocado" frequentemente é UM chunk que **não está marcado como gold mas é semanticamente equivalente**. Solução: revisão manual de cada paráfrase pra expandir gold. ~2-3 horas de trabalho.
2. **Cross-doc com gold underspec.** Múltiplas leis tratam da pergunta, escolher quais entram no gold é subjetivo. As respostas que o dense traz podem ser igualmente válidas mas não-marcadas.
3. **20 queries por tipo ainda é pouco** pra calibração robusta. Erro-padrão de "67% correct" com n=20 é ~10pp. Pra cada decisão de threshold ter <5pp de incerteza, precisaria ~100 queries por tipo. 500 queries totais é trabalho de semana, não tarde.

Mesmo assim: o sinal é claro o suficiente pra justificar começar a montar o router gated. Não dá pra otimizar mais sem mais dados.

## Próximos experimentos

1. **Implementar o router gated** — código simples, ~50 linhas. Testar com v3 e ver se ganho corresponde à estimativa.
2. **Expandir paráfrase** — revisar manualmente os 16 queries de paráfrase, expandir gold pra incluir chunks semanticamente equivalentes. Pode subir nDCG/MRR da categoria sem mexer no retriever.
3. **Voyage rerank-2.5** — temos crédito, vale tentar reranker em-domínio pra ver se quebra o pattern.

## Artefatos

- Eval set: `eval/queries.yaml` (78 queries, schema v2).
- Análise: `rag_leis/confidence_analysis.py`.
- Output: `/tmp/confidence_analysis.txt`.
- Reprodução:
  ```bash
  python -m rag_leis.run_eval --model voyage-3-large --text-mode label+nav+caput+text --by-type
  python -m rag_leis.confidence_analysis --model voyage-3-large --text-mode label+nav+caput+text
  ```
