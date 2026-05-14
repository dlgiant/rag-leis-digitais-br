# Phase 2 — LLM Contract Layer (design)

**Status**: design (não-implementado). 2026-05-14.

## Objetivo

Plugar o LLM gerador (claude-sonnet-4-5) downstream do retriever (voyage `label+nav+caput+text`, top-K) com **três guard-rails** rígidos antes que qualquer string chegue ao usuário:

1. **Structured output**: o LLM retorna JSON `{answer, citations, unverified_claims}` via tool-call forçado.
2. **Cite-and-verify**: cada URN citado tem que estar **no corpus** e **no contexto top-K**. Citações que não passam são marcadas como `rejected`.
3. **OOS routing**: se o top-1 cosine score < threshold, refusa sem chamar o LLM.

Depois, montar um **answer-eval set** (15 rows) e medir **citation precision/recall**, **faithfulness** (LLM-judge) e **refusal accuracy**.

## Por que estes três guard-rails

A fase de retrieval do projeto convergiu pra "fix the data, not the model": ganhos vieram de gold expansion, label/nav/caput prefixes e cleanup de parser. Mas mesmo com nDCG@10 = 0.672 e recall@20 = 0.861, o LLM downstream tem **três modos de falha** que o eval de retrieval não pega:

- **Citation hallucination** — modelo cita "Art. 12 da LGPD" quando a LGPD não tem art. 12. Mata confiança jurídica.
- **Out-of-context citation** — modelo cita um URN real do corpus que não estava no top-K — não há como ele saber daquele texto, então a citação é fabricada.
- **Out-of-scope answering** — usuário pergunta "qual a alíquota do IRPF?", retriever traz top-K com lixo (qualquer chunk tem score > 0), modelo gera resposta plausível mas inventada.

Os três guard-rails atacam cada um:

| Falha | Guard-rail |
|---|---|
| Citation hallucination | Cite-and-verify (URN ∈ corpus) |
| Out-of-context citation | Cite-and-verify (URN ∈ top-K) |
| Out-of-scope answering | OOS routing (top-1 < threshold → refusa) |

## Stack

```
query
  ↓
retrieve (voyage label+nav+caput+text, top-K=10)
  ↓
OOS gate: top-1 sim < threshold? → refusa "fora do escopo"
  ↓
build context (chunks com URN tags)
  ↓
LLM call (claude-sonnet-4-5, tool_choice forçado → JSON)
  ↓
parse: {answer, citations: list[urn], unverified_claims: list[str]}
  ↓
cite-and-verify (URN ∈ corpus ∧ URN ∈ top-K)
  ↓
return RAGAnswer(answer, citations=verified, rejected=[...], refused, ...)
```

## Módulos (novos)

| arquivo | papel |
|---|---|
| `rag_leis/llm.py` | `AnthropicLLM` — wrapper Anthropic API, `complete()` e `complete_structured(tool_schema)` |
| `rag_leis/rag.py` | `RAGPipeline` orquestra retrieve→guard→LLM→verify; `RAGAnswer` dataclass |
| `rag_leis/verify.py` | `verify_citations()`, OOS gate utils, judge faithfulness |
| `rag_leis/run_answer_eval.py` | CLI: roda pipeline sobre `eval/answer_queries.yaml`, reporta métricas |

**Modificados:**
- `pyproject.toml` — `anthropic>=0.40` em deps
- `.env` — `ANTHROPIC_API_KEY` (já há padrão pelas outras keys)

**Dados novos:**
- `eval/answer_queries.yaml` — 12 in-scope + 3 OOS rows, formato `{query, type, expected_paragraph, gold_urns, alternative_urns, oos: bool}`

## Decisões já tomadas (sessão 2026-05-14)

| decisão | escolha | racional |
|---|---|---|
| Modelo gerador | `claude-sonnet-4-5` | Equilíbrio custo/qualidade. Tool-call estruturado robusto. |
| Ordem de implementação | Pipeline-first (2.1→2.4 antes do eval) | Iteração mais rápida; demo end-to-end early. |
| Faithfulness measurement | LLM-as-judge | Cheap, viável v0. Mitigar circular bias usando **judge ≠ generator** (judge = opus-4-7). |
| Tool-call vs JSON mode | tool-call forçado | `tool_choice={"type":"tool","name":...}` garante schema válido; alternativa instruct+retry é flaky. |

## Sub-fases (sizing total: ~3-4 dias)

### 2.1 Anthropic SDK wrapper (~3h)

`rag_leis/llm.py`:

```python
class AnthropicLLM:
    def __init__(self, model: str = "claude-sonnet-4-5"): ...
    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str: ...
    def complete_structured(
        self, system: str, user: str, tool_schema: dict, max_tokens: int = 1024
    ) -> dict:
        """Force tool_choice; return parsed tool input dict."""
```

Smoke test: prompt minimal pra checar API + tool-call forcing.

### 2.2 RAGPipeline (~½ dia)

`rag_leis/rag.py`:

```python
@dataclass
class RAGAnswer:
    answer: str
    citations: list[str]                       # verified URNs
    unverified_claims: list[str]               # modelo auto-marca
    rejected_citations: list[tuple[str, str]]  # (reason, urn)
    refused: bool
    refusal_reason: str | None
    raw_retrieval: list[tuple[str, float]]     # full top-K com scores

class RAGPipeline:
    def answer(self, query: str) -> RAGAnswer: ...
    def _build_context(self, retrieved) -> str:
        # Cada chunk vira:
        #   --- URN: <urn> | <citation> | <nav>
        #   <text>
```

System prompt (português):
- responder usando EXCLUSIVAMENTE o contexto fornecido
- citar pelo URN canônico exato
- se não souber, dizer "Não há informação suficiente no contexto"
- popular `unverified_claims` com qualquer afirmação não suportada

### 2.3 Structured output via tool-call (~3h)

Schema:

```python
ANSWER_TOOL = {
    "name": "responder",
    "description": "Submeta a resposta final. Cite cada artigo/lei usado pelo URN canônico exato do contexto.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}},
            "unverified_claims": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer", "citations", "unverified_claims"]
    }
}
```

`tool_choice={"type": "tool", "name": "responder"}` força schema válido.

### 2.4 Cite-and-verify (~3h)

`rag_leis/verify.py`:

```python
def verify_citations(
    cited: list[str],
    retrieved_urns: frozenset[str],
    corpus_urns: frozenset[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Returns (verified, rejected)."""
```

Política inicial: **citações rejeitadas não bloqueiam** a resposta — só são removidas de `citations` e logadas em `rejected_citations`. Razão: rejeitar a resposta inteira por 1 citação ruim é frágil; o `unverified_claims` + rejected_count já sinalizam confiança baixa.

Alternativa pra futuro: se `rejected` ≥ 50% ou se a única citação for rejeitada, refusar com motivo "citações não-verificáveis".

### 2.5 Answer-eval set (~1 dia, trabalho de domínio)

`eval/answer_queries.yaml`: 12 in-scope + 3 OOS.

Schema por linha:
```yaml
- query: "Quais hipóteses autorizam tratamento de dados pessoais segundo a LGPD?"
  type: enumeracao
  expected_paragraph: |
    A LGPD autoriza tratamento de dados pessoais nas hipóteses do art. 7,
    incluindo consentimento, cumprimento de obrigação legal, execução de
    políticas públicas, pesquisa, execução de contrato, exercício de
    direitos, proteção da vida, tutela da saúde, legítimo interesse e
    proteção ao crédito.
  gold_urns:
    - "urn:lex:br:federal:lei:2018-08-14;13709~art7"
    - "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1"
    - "..."
  oos: false

- query: "Como funciona a tributação do IRPF para autônomos?"
  type: oos
  oos: true
```

Sample plan (12 in-scope, escolhidas de `eval/queries.yaml`):
- 4 `definicao` (consentimento LGPD, dado pessoal sensível, neutralidade de rede, …)
- 4 `enumeracao` (hipóteses art.7 LGPD, princípios MCI, …)
- 3 `citacao-literal` (anonimato CF art.5;inc4, …)
- 1 `cross-doc` (proteção de dados em interação com governo)

OOS examples (3 rows):
- "Como pagar IRPF?"
- "Direitos do empregado em rescisão sem justa causa"
- "Qual a alíquota do ICMS em SP?"

### 2.6 Answer-stage eval (~½ dia)

`rag_leis/run_answer_eval.py`:

Métricas:
- **Citation precision** = `|cited ∩ gold| / |cited|` (per query, depois média)
- **Citation recall** = `|cited ∩ gold| / |gold|`
- **Citation F1** = harmônica
- **Faithfulness score** = LLM-judge 0-5 (judge = `claude-opus-4-7`, generator = `claude-sonnet-4-5`)
- **Refusal accuracy** = `(true_oos_refused + true_inscope_answered) / total`
- **Rejected citation rate** = `|rejected| / |cited+rejected|` (sinal de hallucination)

Aggregate report por query + média global + breakdown por type.

LLM-judge prompt (faithfulness):
```
Compare a resposta gerada à resposta esperada. Pontue de 0 a 5:
5 = Todos os fatos da esperada, sem alucinação.
4 = Cobre fatos essenciais, sem alucinação.
3 = Cobre fatos parciais, sem alucinação.
2 = Cobre parcial, alucinação leve.
1 = Cobertura ruim ou alucinação significativa.
0 = Incorreta ou totalmente alucinada.

Retorne JSON: {"score": int, "reasoning": str}
```

### 2.7 OOS routing calibration (~3h)

Depois de 2.6:
- Plot top-1 scores: in-scope vs OOS
- Pick threshold maximizando F1 (refusal classifier)
- Update `RAGPipeline.oos_threshold` default

Cuidado: **held-out set** — separar 3 OOS pra calibration vs 3 pra report final, ou aceitar o leak (com 15 rows total é difícil ter split).

## Cronograma proposto

| dia | tarefa |
|---|---|
| 1 (manhã) | 2.1 Anthropic wrapper + smoke test |
| 1 (tarde) | 2.2 Pipeline + 2.3 structured output |
| 2 (manhã) | 2.4 Cite-and-verify + manual smoke (3 queries) |
| 2 (tarde) | 2.5 Answer-eval set (3-5 rows prova) |
| 3 (manhã) | 2.5 finalizar 15 rows |
| 3 (tarde) | 2.6 metrics + report |
| 4 (manhã) | 2.7 OOS calibration |
| 4 (tarde) | Write-up: `study/phase-2-results.md` |

## Riscos & mitigations

| risco | mitigação |
|---|---|
| Judge circular bias (Claude judging Claude) | Usar opus-4-7 como judge, sonnet-4-5 como generator — modelos de tamanho diferente |
| 15 rows é eval set pequeno | Documentar como v0; expandir incrementalmente; reportar variance |
| OOS threshold com leak (calibrar e reportar no mesmo set) | Reportar 2 cenários: leak (otimista) + held-out (real). 15 rows justifica leak na v0. |
| API cost | ~$0.01/query → $0.15 por run de eval. OK pra iteração. |
| Tool-call não-disponível em alguns paths | Tested no Anthropic SDK estável. Fallback: JSON mode + parse+retry (codepath não implementado v0). |

## Trade-offs pra documentar no write-up

1. **Tool-call vs JSON mode**: por que tool-call ganha (schema enforcement por SDK).
2. **OOS via similarity threshold vs LLM classifier**: threshold é barato, falso-positivo em paráfrase é o custo.
3. **Refusing vs stripping rejected citations**: escolha conservadora vs prática.
4. **Citation precision/recall vs faithfulness**: por que citation metrics sozinhos não bastam (modelo pode citar URNs certos e mesmo assim alucinar texto).
5. **Latency**: 1 retrieve + 1 LLM call. Reportar p50/p95.

## Output do Phase 2

- 4 módulos novos
- 1 eval set (15 rows)
- 1 CLI (`run_answer_eval.py`)
- 1 doc de resultados (`study/phase-2-results.md`)
- Atualização BACKLOG.md (mark Phase 2 done, surface Phase 3 candidates: retry policy, multi-turn, reasoning trace, etc.)
