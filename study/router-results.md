# Gated router — não ganha o que a calibração prometia

Branch: `experiment/router`. Data: 2026-05-13.

## TL;DR

A calibração do v3 sugeria que rotear queries de citação literal com gap baixo pra ColBERT-RRF poderia render +3-5pp nDCG. **Não rendeu.** Sweep em 4 configurações:

| pipeline | nDCG@10 | Recall@20 | MRR@10 | Δ nDCG |
|---|---:|---:|---:|---:|
| **voyage dense alone** | **0.608** | 0.856 | **0.591** | — |
| router citation-only (route all 15 cit.) | 0.610 | **0.873** | 0.588 | +0.002 |
| router citation+gap≤0.016 (10 routed) | 0.609 | 0.873 | 0.585 | +0.001 |
| router citation+gap≤0.005 estrito (6 routed) | **0.611** | 0.874 | 0.586 | +0.003 |
| router citation+gap=0.016, dense×10 RRF | 0.606 | 0.870 | 0.583 | -0.002 |
| router gap-only (42 routed, no regex) | 0.588 | 0.860 | 0.557 | **-0.020 ❌** |

No melhor cenário (threshold 0.005), ganho é +0.003 nDCG — dentro do ruído com 78 queries. **Voyage dense + label+nav+caput+text continua sendo o operating point.**

## O que o sweep revela

### Per-query nos 10 roteados (config padrão citation+gap=0.016)

| # | query | gap | ΔnDCG | ΔMRR | veredito |
|---|---|---:|---:|---:|---|
| 27 | "o que diz o art. 18 da LGPD?" | 0.002 | **+0.28** | **+0.33** | ✓ win forte |
| 60 | "o que diz o art. 147 do CP?" | 0.004 | **+0.63** | **+0.50** | ✓ win enorme |
| 31 | "o que diz o art. 11 da LGPD?" | 0.010 | +0.01 | 0 | neutro |
| 32 | "o que diz o art. 13 do MCI?" | 0.002 | 0 | 0 | neutro |
| 33 | "o que diz o art. 46 do Direito Autoral?" | 0.016 | 0 | 0 | neutro |
| 28 | "o que diz o art. 9 MCI?" | 0.007 | -0.03 | -0.03 | leve loss |
| 26 | "o que diz o art. 7 da LGPD?" | 0.008 | **-0.11** | 0 | ⚠ loss |
| 64 | "o que diz o art. 41 da LGPD?" | 0.001 | **-0.13** | -0.17 | ⚠ loss |
| 59 | "o que diz o art. 121 CP?" | 0.005 | **-0.24** | -0.30 | ⚠ loss |
| 63 | "o que diz o art. 7 do Direito Autoral?" | 0.005 | **-0.33** | **-0.75** | ⚠ loss grande |

Wins concentrados (+0.28 a +0.63), losses dispersos mas frequentes (-0.03 a -0.33). **Magnitude média dos losses é menor mas frequência é maior**: ~4 losses × ~-0.20 = -0.80 vs 2 wins × +0.45 = +0.90. Net ≈ +0.10 distribuído em 10 queries = +0.01 nDCG, que coincide com o ganho agregado em citacao-literal (0.483 → 0.488).

### Por que falhou — análise das 4 losses

Pattern: quando dense já encontrou o artigo certo MAS em uma posição ruim do top-K, ColBERT-RRF reorganiza pra pior.

- **#26 art.7 LGPD**: dense top-3 tinha art.7;par4, art.7;par6 (irmãos do artigo certo). RRF puxou art.46;par1 (chunk não-relacionado mas com forte casamento token de "tratamento") pra cima.
- **#63 art.7 Direito Autoral**: dense top-3 tinha art.7;inc1,inc2,inc3 (todos gold). RRF substituiu os incisos por art.7;par1, art.7;par2 (parágrafos do mesmo artigo mas não-gold) — ColBERT achou mais tokens em comum nos parágrafos.
- **#64 art.41 LGPD**: dense top-1 era art.42;par1 (sibling artigo); top-2 era art.41 (gold). RRF moveu pra art.41;par3, art.42, art.41;par2 — pior ainda.

Padrão estrutural: **ColBERT casa tokens locais e prefere chunks com mais tokens em comum com a query, mesmo que sejam `art.X;par.Y` em vez do `art.X` certo**. Isso é exatamente o problema que a relevância gradada deveria capturar (par1 do artigo certo ainda é "partial relevance"), mas o gold binário diz "errado" e a métrica não recompensa o quase-acerto.

### Por que gap-only é desastre

Roteia 42 queries (não só citação). Per-type breakdown:

| tipo | n routed | router nDCG | dense nDCG | Δ |
|---|---:|---:|---:|---:|
| **parafrase** | 10 / 16 | **0.396** | 0.491 | **-0.095** |
| **enumeracao** | 11 / 15 | 0.695 | 0.695 | 0 (n/a porque enum tem gap baixo) |
| **cross-doc** | 5 / 12 | 0.423 | 0.450 | -0.027 |
| citacao-literal | 10 / 15 | 0.488 | 0.483 | +0.005 |
| definicao | 6 / 20 | 0.836 | 0.825 | +0.011 |

Paráfrase é onde ColBERT mais machuca (-9.5pp nDCG): ColBERT prefere chunks com casamento literal de tokens da query, mas a query é justamente paráfrase — vocabulário leigo que NÃO está no chunk certo. Voyage dense entende a semântica; ColBERT regride pra casamento superficial e erra.

### Por que dense×10 RRF não salva

Mesmo com peso muito alto pra dense, RRF ainda é fusão. Quando ColBERT discorda forte (rank 1 dele em algo que dense tinha em rank 30), a fusão move o doc pra cima o suficiente pra entrar no top-K final. Não há combinação de pesos que faz "se dense estiver confiante, ignore ColBERT" — pra isso precisaria de seleção dura, não fusão.

## Por que a calibração mentiu (e como)

Calibração mostrava: gap < 0.016 → 23% top-1 correct; gap > 0.016 → 67%. Sugeria que para queries de gap baixo, *qualquer* fallback que faça melhor que 23% já ganha.

**O que faltou medir**: o fallback (ColBERT-RRF) não só tem accuracy variável por query — quando ele acerta, acerta forte (+0.6); quando erra, erra moderadamente (-0.2). A média esconde a variância.

Pra calibração ter previsto isto, precisaríamos de um sinal *adicional* — não só "dense está incerto?" mas também "ColBERT vai discordar de forma útil?". A última seria circular sem um classificador treinado.

A lição: **calibração de UM retriever (dense) não basta pra decidir se outro retriever (ColBERT) vai ser útil**. Precisaria de calibração conjunta, que é basicamente um meta-aprendizado.

## Pra produção

**Recomendação: ficar com voyage dense + label+nav+caput+text como retriever único.** nDCG 0.608, Recall 0.856, MRR 0.591. Mais simples, suficientemente bom.

Onde poderia melhorar (sem second-stage):
1. **Caput-prefix mais cirúrgico**: hoje incluímos o caput inteiro de TODOS os ancestrais. Talvez incluir só caput do artigo + parágrafo direto (não o caput de capítulo/seção) ajude paráfrase.
2. **Expansão do gold da paráfrase**: 19% top-1 correct é provavelmente artefato de gold incompleto. Revisão manual pode trazer essa categoria de 0.49 → 0.65+.
3. **Reranker em-domínio**: nunca testamos Cohere `rerank-multilingual-v3` ou Voyage `rerank-2.5`. Custam, mas talvez sejam o caminho onde os abertos falharam.

## Onde o router *poderia* funcionar

Resultado negativo deste experimento é específico:
- A query é **suficientemente bem-formulada** que voyage dense já tem o chunk certo perto do top.
- ColBERT-MRR (single model BGE-M3) **não tem força suficiente** pra superar voyage dense quando este está perto.

Em outros setups o router faria diferença:
- Se o dense fosse fraco (BGE-M3 dense alone, nDCG 0.44) → ColBERT-RRF poderia trazer ganho substancial.
- Se as queries fossem mais "lossy" (ruído OCR, transcrições verbais) → casamento token seria mais valioso.
- Se o gold fosse single-chunk em vez de multi-chunk (enumerações fragmentadas tipo art.7 LGPD) → vencedor único bate fusão.

Pra nosso corpus + queries, o router agrega complexidade sem retorno. **É um achado contrarian útil pro post: "calibração de confiança ≠ ganho garantido".**

## Artefatos

- Eval set: `eval/queries.yaml` (78 queries v3).
- Código: `rag_leis/router_eval.py` (gate modes: citation-and-gap, citation-only, gap-only).
- Outputs: `/tmp/router_results.txt`, `/tmp/router_sweep.txt`.
- Reprodução:
  ```bash
  python -m rag_leis.router_eval --gate-mode citation-and-gap --gap-threshold 0.016
  python -m rag_leis.router_eval --gate-mode citation-only
  python -m rag_leis.router_eval --gate-mode gap-only --gap-threshold 0.016
  ```
