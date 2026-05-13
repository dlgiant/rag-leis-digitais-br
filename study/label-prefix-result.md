# Label-prefix — fechando o buraco da citação literal

Branch: `experiment/label-prefix`. Data: 2026-05-13.

## TL;DR

Adicionar o **citation chain do chunk** ("Art. 7, I" / "Art. 154-A, § 1º") como prefixo no índice ressuscita a categoria `citacao-literal` que estava 100% morta no v2.

| voyage-3-large | nav+caput+text | **label+nav+caput+text** | Δ |
|---|---:|---:|---:|
| nDCG@10 (agregado) | 0.598 | **0.645** | **+0.047** |
| Recall@20 | 0.766 | **0.869** | **+0.103** |
| MRR@10 | 0.588 | 0.635 | +0.047 |
| **nDCG citacao-literal** | **0.000** | **0.356** | **+0.356** |
| **Recall@20 citacao-literal** | **0.013** | **0.710** | **+0.697** |

Mudança: 5 linhas em `format_texts` + walk-up `parent_partition` no loader pra montar a string "Art. X, II, a".

## O experimento

V2 do eval revelou que 8 queries do tipo "*o que diz o art. X da [lei]?*" retornavam MRR=0 em 8/8 configurações testadas — porque o número do artigo **não estava em lugar nenhum do surface form indexado**. O `label` do chunk (e.g. "Art. 7") só vivia no JSONL parseado; nem o `nav_text` (capitulo/secao) nem o `caput_text` (concat de ancestrais) o continham.

Fix: walk up `parent_partition` e juntar os `label`s pra montar a citação canônica. Indexar com prefixo.

Antes:
```
nav+caput+text:
  "II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais ::
   O tratamento de dados pessoais somente poderá ser realizado nas seguintes hipóteses:"
```

Depois:
```
label+nav+caput+text:
  "Art. 7 :: II DO TRATAMENTO DE DADOS PESSOAIS > I Dos Requisitos para o Tratamento de Dados Pessoais ::
   O tratamento de dados pessoais somente poderá ser realizado nas seguintes hipóteses:"
```

Pra um chunk profundo:
```
label+nav+caput+text:
  "Art. 11, II, a :: II DO TRATAMENTO DE DADOS PESSOAIS > II Do Tratamento de Dados Pessoais Sensíveis ::
   O tratamento de dados pessoais sensíveis somente poderá ocorrer nas seguintes hipóteses:
   sem fornecimento de consentimento do titular, nas hipóteses em que for indispensável para:
   à tutela da saúde, exclusivamente, em procedimento realizado por profissionais de saúde..."
```

## Resultados completos

### voyage-3-large

| mode | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|
| text | 0.560 | 0.709 | 0.633 |
| nav+text | 0.585 | 0.743 | 0.675 |
| caput+text | 0.573 | 0.776 | 0.565 |
| nav+caput+text | 0.598 | 0.766 | 0.588 |
| **label+nav+caput+text** | **0.645** | **0.869** | **0.635** |

### Per-type (voyage, label+nav+caput+text vs nav+caput+text)

| tipo | nav+caput+text | label+nav+caput+text | Δ nDCG |
|---|---:|---:|---:|
| definicao | 0.886 | 0.859 | -0.027 |
| enumeracao | 0.706 | 0.668 | -0.038 |
| **citacao-literal** | **0.000** | **0.356** | **+0.356** |
| parafrase | 0.549 | 0.595 | +0.046 |
| cross-doc | 0.561 | 0.522 | -0.039 |

Mais informativo separado em Recall@20:

| tipo | nav+caput+text | label+nav+caput+text | Δ Recall |
|---|---:|---:|---:|
| definicao | 1.000 | 1.000 | 0.000 |
| enumeracao | 0.880 | 0.807 | -0.073 |
| **citacao-literal** | **0.013** | **0.710** | **+0.697** |
| parafrase | 0.969 | 0.969 | 0.000 |
| cross-doc | 0.722 | 0.722 | 0.000 |

A leitura honesta:

- **Citação-literal de 0% pra 71% Recall@20** é o headline. O retriever agora encontra o chunk certo em ~7 de 10 vezes; antes era 0.
- **Pequena regressão em outros tipos** (≤4pp em nDCG): o label-prefix acrescenta tokens que competem com o sinal semântico em queries não-literais. Pequeno preço a pagar.
- **MRR@10 da citação literal só sobe pra 0.30** — significa que o chunk certo está NO top-20 mas nem sempre no top-1. Esse é o próximo problema: ranking dentro do candidate set. Mas é um problema bem mais tratável que "não está no top-20 nenhum".

### BGE-M3

| mode | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|
| nav+caput+text | 0.439 | 0.628 | 0.428 |
| **label+nav+caput+text** | 0.438 | **0.657** | **0.457** |

BGE-M3 também sobe em citação literal (Recall 0% → 26%), mas bem menos que voyage. Hipótese: o tokenizer XLM-R da BGE-M3 lida pior com "Art. 7" como sinal categórico — talvez quebre em sub-tokens que dispersam o peso. Voyage (cuja tokenização não conhecemos exatamente) parece tratar "Art. 7" como unidade mais coesa.

### Reranker em cima

| voyage / label+nav+caput+text | nDCG@10 | Recall@20 | MRR@10 |
|---|---:|---:|---:|
| dense | **0.645** | **0.869** | **0.635** |
| dense + bge-reranker-v2-m3 | 0.538 | 0.869 | 0.519 |

Reranker continua mais machucando que ajudando (-0.11 nDCG). Citação-literal especificamente cai de 0.36 → 0.29 com rerank — significa que o cross-encoder está re-rankeando mal *mesmo quando* o chunk certo está disponível na lista. Confirma o achado de v1: rerankers cross-encoder genéricos estão fundamentalmente desalinhados pra este corpus.

## Por que funciona

O label-prefix dá ao retriever um **identificador categórico explícito** do chunk. Modelos de embedding densos são bons em casamento semântico ("definição" ↔ "que é"), mas precisam de muletas pra casamento simbólico ("Art. 7" ↔ "art. 7"). O label-prefix oferece exatamente essa muleta.

Comparação útil: é o **mesmo princípio do `nav+text`** (Dia 2), só que pra eixo diferente:
- `nav` adiciona contexto hierárquico (capitulo/secao) → ajuda queries que mencionam tópico de capítulo
- `label` adiciona identidade canônica (Art. X, § Y) → ajuda queries que mencionam citação literal
- `caput` adiciona contexto semântico do pai → ajuda queries enumerativas

Os 3 são "adicione metadado estrutural ao surface form do chunk", em direções complementares.

## Por que não funciona perfeitamente

Recall foi de 1.3% pra 71%, nDCG só pra 35.6%. O gap é ranking — chunk certo entra no top-20 mas não no top-1. Algumas razões prováveis:

1. **Múltiplos chunks compartilham o prefixo "Art. 7"**: o caput é "Art. 7" mas os incisos são "Art. 7, I", "Art. 7, II", etc. Quando query diz "art. 7", todos ficam relevantes — qual é o "1º colocado" depende do conteúdo.
2. **Ambiguidade entre leis**: "art. 5" existe em LGPD, Constituição, LAI e várias outras. O retriever precisa do contexto da lei (que vem do `nav_text`) pra desambiguar, mas isso é peso lateral comparado ao casamento literal "art. 5".
3. **Limite do que dense embedding pode fazer**: pra "qual é A resposta canônica" entre N chunks semanticamente parecidos, embed dense single-vector tem ceiling estrutural.

Solução parcial pra (1) e (2): **reranker em-domínio** — mas é exatamente o que sabemos que falha hoje. Talvez (3) abra caminho pra **sparse + ColBERT late interaction**: bge-m3 já emite vetor ColBERT, e late interaction casa token por token, então "art. 7" no chunk casa com "art. 7" na query com peso explícito.

## Decisão de produção

**Trocar default de `nav+caput+text` pra `label+nav+caput+text`** sempre que o eval permitir verificar não houve regressão localmente. Custo: zero (mesmo tempo de embedding, mesmo tamanho de índice). Ganho: +4.7pp nDCG agregado, +10.3pp Recall@20, citação literal sai do zero.

## Próximos experimentos

1. **ColBERT/multi-vector** — BGE-M3 já emite. Pode resolver o "ranking dentro do top-20" da citação literal.
2. **Hard-negatives na eval de citação literal** — atualmente o gold de "art. 7 LGPD" inclui todos os incisos. Pra medir ranking mais fino, talvez separar core="o caput Art. 7" e supporting="incisos". Mas tem trade-off: a resposta natural pra "o que diz art. 7" inclui sim os incisos.
3. **Roteamento de query** — detectar "art\.? \d+" via regex e enviar pra um índice especial (sparse puro? ColBERT?). Mais complexo, ganho marginal sobre o que já temos.

## Artefatos

- Eval set v2: 47 queries tipadas em `eval/queries.yaml`.
- Output: `/tmp/label_results.txt`.
- Mudança: ~30 linhas em `rag_leis/eval_harness.py` (citation field + `_resolve_citation` + format_texts mode) e 1 linha em `run_eval.py` (adiciona "label+nav+caput+text" à lista de choices).
- Reprodução:
  ```bash
  python -m rag_leis.run_eval --model voyage-3-large --text-mode label+nav+caput+text --by-type
  python -m rag_leis.run_eval --model bge-m3 --text-mode label+nav+caput+text --by-type
  ```
