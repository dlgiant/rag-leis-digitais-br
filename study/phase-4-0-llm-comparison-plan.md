# Phase 4.0 — LLM Comparison Harness (sonnet-4-5 vs Sabiá-3)

**Status**: design (não-implementado). 2026-05-15.

Triggered by D9 (LGPD data residency). Anthropic não tem region BR; Marítaca
hospeda Sabiá-3 nativamente em SP. Antes de comprometer a arquitetura com
um provider, **rodar benchmark data-driven** sobre o eval set existente.

Sem este benchmark, D9 vira chute. Custo do benchmark (~$15-20 + 1 dia de
trabalho) é trivialmente menor que custo de migrar errado depois.

## Pergunta que o benchmark responde

Sabiá-3 substitui sonnet-4-5 sem regressão inaceitável nas 4 métricas
load-bearing?

| Métrica | sonnet-4-5 (baseline atual) | Threshold pra trocar |
|---|---|---|
| Faithfulness mean | 4.15/5 | ≥ 3.7/5 (-10%) |
| Citation precision lenient | 0.66 | ≥ 0.55 (-15%) |
| **Rejected citation rate** | **0.000** | **≤ 0.05** (load-bearing — produto verificável) |
| Refusal accuracy | 0.93 | ≥ 0.85 |

**Critério de decisão**: se Sabiá-3 passa nas 4 simultaneamente, swap pra
ele resolve D9 + reduz custo + melhora latência. Se falha em qualquer uma
(especialmente rejected_citation_rate), fica Anthropic + ZDR + DPA + ToS
disclaimer (option C do D9 menu).

## Por que esta phase precisa ser SEPARADA

- Decisão de provider impacta arquitetura (auth, fallback, monitoring,
  cost tracking, prompt versioning) — todas as Phase 7+ items
- Refactor pra suportar múltiplos providers é genuinamente útil mesmo se
  ficarmos com Anthropic (model fallback de 7.4 fica muito mais barato)
- Risco de descobrir tarde que Sabiá-3 não suporta tool_choice forçado é
  alto; cedo vale identificar

## Sub-fases (~2-3 dias prep + 1 dia eval pós-key)

### 4.0.a — LLM provider abstraction (~½ dia)

Hoje `AnthropicLLM` é typed concreto em `RAGPipeline` e `run_answer_eval`.
Refactor pra protocol:

**Novo arquivo `rag_leis/llm_protocol.py`** (ou estender `rag_leis/llm.py`):

```python
from typing import Protocol

class LLM(Protocol):
    name: str  # identificador estável (ex: "claude-sonnet-4-5", "sabia-3")
    provider: str  # "anthropic" | "maritaca"

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str: ...

    def complete_structured(
        self, system: str, user: str, tool_schema: dict, max_tokens: int = 2048
    ) -> dict: ...
```

**Mudanças derivadas**:
- `AnthropicLLM` ganha `name` + `provider` fields
- `RAGPipeline.llm: LLM` (era `AnthropicLLM`)
- `load_pipeline(...)` aceita `provider: str = "anthropic"` + factory dispatch
- `run_answer_eval --llm-provider {anthropic, maritaca}` flag novo

Testes existentes passam unchanged (Anthropic é o único impl).

### 4.0.b — `MaritacaLLM` adapter (~1 dia)

**Novo arquivo `rag_leis/maritaca.py`**:

```python
class MaritacaLLM:
    name: str = "sabia-3"
    provider: str = "maritaca"

    def __init__(self, model: str = "sabia-3", api_key: str | None = None):
        # Marítaca usa OpenAI-compatible SDK; reuse openai client lib
        # apontando pra https://chat.maritaca.ai/api
        ...

    def complete(self, system, user, max_tokens=1024) -> str:
        # Direct chat completion
        ...

    def complete_structured(self, system, user, tool_schema, max_tokens=2048) -> dict:
        # CRITICAL: Sabiá-3 supports OpenAI-style function calling.
        # Verify se `tool_choice={"type": "function", "function": {"name": ...}}`
        # forces emission like Anthropic. Se não, fallback pra JSON mode + retry.
        ...
```

**Pontos críticos a investigar** (antes de implementar 4.0.b):
1. Marítaca SDK exato — é OpenAI-compatible literal ou tem quirks?
2. Tool-choice forcing reliability — é tão garantido quanto Anthropic?
3. Rate limits e quotas no tier gratuito vs paid
4. Streaming / non-streaming parity
5. PT-BR system prompt overhead (Sabiá-3 espera prompt em PT? EN?)

**Ação**: research feito amanhã quando user tiver acesso ao painel Marítaca.
Provavelmente 1-2h de leitura de docs + 1-2h de test calls + 4-6h de coding.

**Dependência nova**: `openai>=1.0` em pyproject (Marítaca usa SDK OpenAI-compatible).

### 4.0.c — Comparison runner (~½ dia)

**Novo CLI `rag_leis/run_llm_comparison.py`**:

```bash
uv run python -m rag_leis.run_llm_comparison \
    --llm-providers anthropic,maritaca \
    --runs-per-provider 3 \
    --output study/llm-comparison-2026-05-XX.json
```

Faz:
1. Pra cada provider × N runs:
   - Chama `run_answer_eval` underneath, salva todos os JSONs
2. Computa stats agregadas:
   - Mean + stddev por métrica por provider
   - Per-row diff (qual provider venceu em cada query)
   - Latência p50/p95
   - Cost total
3. Output: side-by-side report markdown + JSON dump pra reanálise

**Métricas adicionais que o comparison expõe**:
- Stddev across runs (proxy de determinismo)
- Per-type breakdown (Sabiá-3 pode ser melhor em definição PT-BR mas pior
  em enumeração — relevante pra adaptive routing depois)
- Token cost dollar amount por provider

### 4.0.d — Run benchmark + decisão (~½ dia + custo $15-20)

**Quando user fornecer Marítaca API key**:

1. Setar `MARITACA_API_KEY` em `.env`
2. Rodar comparison (3 runs cada provider):
   ```bash
   set -a; source .env; set +a
   uv run python -m rag_leis.run_llm_comparison \
       --llm-providers anthropic,maritaca \
       --runs-per-provider 3 \
       --output study/llm-comparison-2026-05-XX.json
   ```
3. Inspecionar:
   - **Show-stopper check**: rejected_citation_rate Sabiá-3 ≤ 0.05?
   - Faithfulness gap aceitável?
   - Per-type onde Sabiá-3 ganha/perde?
4. **Decision matrix**:
   - Sabiá-3 passa todas as 4 thresholds → trocar generator pra Sabiá-3,
     manter opus-4-7 como judge (judge não tem mesmo requirement de residency
     porque processa só `expected_paragraph` + `answer`, ambos já redigidos
     em PT por humano + sonnet)
   - Sabiá-3 passa em 3 de 4 → híbrido: Sabiá-3 como default, fallback
     pra sonnet-4-5 nas queries-tipo onde reprovou
   - Sabiá-3 reprova em rejected_citation_rate especificamente → fica
     Anthropic. D9 vira "ZDR + DPA + ToS disclaimer" path

### 4.0.e — Atualizar plan + commit findings (~2-3 horas)

- Atualizar `study/post-review-plan.md` com decisão D9 final
- Documentar decisão em `study/llm-provider-decision-2026-05-XX.md` com
  números, raciocínio, threshold definitions
- Update `BACKLOG.md` se ficar híbrido (Sabiá fallback rules)
- Posts/findings doc pra capturar pra LinkedIn arc

## Estimativa total

| Sub-fase | Sizing | Custo API |
|---|---|---|
| 4.0.a refactor | ½ dia | $0 (no API call) |
| 4.0.b Marítaca adapter | 1 dia | ~$1-2 (smoke tests) |
| 4.0.c comparison runner | ½ dia | $0 |
| 4.0.d run benchmark | ½ dia | ~$15-20 (3 runs × 2 providers) |
| 4.0.e doc | ½ dia | $0 |
| **Total** | **~3 dias** | **~$15-25** |

## Hoje (sem API key Marítaca)

Posso fazer **4.0.a + parte de 4.0.b** (estrutura sem testar), também
research + leitura de docs Marítaca. Quando key chegar, finalizar 4.0.b +
fazer 4.0.c + 4.0.d em sequência.

Concretamente hoje (~½ dia útil):
1. Refactor `LLM` protocol em `rag_leis/llm.py`
2. Refactor `RAGPipeline.llm` typed como protocol
3. Refactor `load_pipeline()` aceitar `provider` arg
4. Stub `MaritacaLLM` com TODOs marcando os pontos a testar amanhã
5. Adicionar `openai>=1.0` em `pyproject.toml` (Marítaca usa SDK compatível)
6. Tests existentes passam (sem regressão)

Amanhã com key:
1. Implementar `MaritacaLLM` real
2. Smoke test contra API
3. Build comparison runner
4. Run benchmark
5. Decisão D9 + commit findings

## Risks / unknowns

| Risk | Mitigation |
|---|---|
| Marítaca tool_choice não força como Anthropic | Investigar primeiro; se sim, fallback pra JSON mode + parse + retry. Manter v0 com retry budget de 3. |
| Sabiá-3 PT-BR jurídico tem buracos vs sonnet-4-5 EN-fluent | Eval set captura — é exatamente o que o benchmark vai medir. |
| Marítaca rate-limit free tier muito baixo | Run com sleep + retry; se inviável, esperar paid tier ou rodar em batches |
| Pricing surpresa | Conferir docs antes de rodar (3 runs × 16 queries × ~3000 tokens cada estimate ~$5-10 pra Sabiá) |
| Latência muito ruim (apesar BR region) | Medir; se >10s p95 vira deal-breaker pra UX produto |

## Saídas

- `rag_leis/llm.py` (LLM protocol + AnthropicLLM unchanged)
- `rag_leis/maritaca.py` novo
- `rag_leis/run_llm_comparison.py` novo
- `study/llm-comparison-2026-05-XX.json` (raw data)
- `study/llm-provider-decision-2026-05-XX.md` (write-up + decision)
- D9 unblocked
- Update `study/post-review-plan.md` com D9 final
- Possível update `BACKLOG.md` com fallback rules

## Critério de sucesso

- Decisão D9 baseada em dados, não estimativa
- Refactor de LLM protocol durável (serve pra Phase 7.4 model fallback também)
- Custo ≤ $25
- Tempo ≤ 3 dias (½ hoje + 1 dia amanhã + 1 dia análise/decisão)
