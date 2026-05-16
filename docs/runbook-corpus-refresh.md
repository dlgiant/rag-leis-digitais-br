# Runbook — Corpus Refresh (Phase 7 production infra)

Para o humano que recebe um PR aberto pelo `.github/workflows/refresh-corpus.yml`
ou uma issue de `corpus-update-failed` / `production-degradation`.

## Setup único (antes do primeiro cron)

**Secrets do repo** (Settings → Secrets and variables → Actions → New repository secret):

| Nome | Obrigatório | Origem |
|---|---|---|
| `VOYAGE_API_KEY` | Sim — workflow falha sem | https://dash.voyageai.com/ |
| `MARITACA_API_KEY` | Sim para smoke test | https://chat.maritaca.ai/ |
| `ANTHROPIC_API_KEY` | Opcional — só para futuras extensões | https://console.anthropic.com/ |

**Cost guard recomendado:**
- Voyage: setar billing alert em $5/mês (steady-state esperado ~$1-2/mês)
- Marítaca: alerta em $5/mês (~$0.20/mês esperado)
- GitHub Actions: free tier 2000 min/mês; uso esperado ~30 min/mês

## Cenário 1 — PR semanal `Corpus refresh — YYYY-MM-DD`

**Quando aparece:** todo domingo ~02:00 UTC após o cron, **se** houver
algum diff vs o estado prévio.

**Tempo de review:** ~5 min.

**Checklist** (já no body do PR; aqui o detalhe):

### 1. Diff summary plausível?

O body lista os URNs mudados, byte deltas, e SHAs antigos→novos.

✅ **OK** se:
- 1-3 URNs mudaram (raro, geralmente é uma lei amendada)
- Byte delta razoável (<10× o tamanho típico; ex.: art alterado adiciona
  ~1KB, não 1MB)
- SHAs antigos batem com os tracked em `data/metadata/`

🚨 **Sinal vermelho** se:
- **Todos os 17 docs CHANGED simultaneamente** → upstream structural
  change (Planalto migrou CMS, F5 mudou pattern, parser bug surfou).
  **NÃO MERGEAR.** Investigar antes — provavelmente uma run manual local
  com `uv run python -m scripts.refresh_corpus` revela o pattern.
- **URN inesperada mudou** (ex.: Constituição inteira de uma vez)
- **Byte delta enorme** (~10× a média) — pode ser página de erro

### 2. Eval metrics dentro da banda?

O body inclui as 3 métricas (nDCG@10, Recall@20, MRR@10).

✅ **OK** se:
- nDCG@10 dentro de ±0.02 do baseline em `data/audit/last_eval_metrics.json`
- (Pequenas flutuações de ±0.005 são normais por causa de re-embed
  estocástico marginal e ranking ties)

🚨 **Sinal vermelho** se:
- O orchestrator NÃO triggou rollback (exit 0), mas a métrica caiu
  > 0.015. Pode ser flicker, mas inspecionar.

(Se passou de 0.02 de queda, o orchestrator já restaurou o índice e
abriu uma issue ao invés de PR — ver Cenário 2.)

### 3. Audit log faz sentido?

Veja `data/audit/corpus_updates.jsonl` (acrescentado por este PR).
Confirme:
- Entries têm timestamp da run atual
- Status é "changed" ou "new" (não tem motivo pra ter "unchanged" na
  audit log — orchestrator filtra)

### 4. Decisão final

- **Mergear PR** → o smoke-test.yml workflow dispara automaticamente
  e exercita o pipeline com Sabiá. Aguarde ele passar (~2-3 min) para
  marcar como "production-aceito".
- **Fechar sem mergear** → metadata fica no SHA prévio; próximo cron
  vai re-tentar e provavelmente abrir outro PR semelhante. Bom se a
  mudança é transiente (Planalto teve hiccup) ou se você quer investigar.

## Cenário 2 — Issue `Corpus refresh FAILED — YYYY-MM-DD`

**Quando aparece:** orchestrator saiu com exit 1. Causas comuns
(em ordem de probabilidade):

### 2a. Eval degradation gate trippou

Sintoma: "DEGRADATION: nDCG@10 dropped X → Y (> 0.02)".

Significa: parser/corpus mudou de um jeito que prejudicou retrieval em
≥1 query do eval set.

**Diagnose:**
```bash
git pull
uv run python -m scripts.refresh_corpus --skip-fetch
# inspeciona qual query degradou:
uv run python -m rag_leis.run_eval --model voyage-3-large \
    --text-mode title+label+nav+caput+text --show-misses
```

**Resolução possível:**
- Legítimo (Planalto mudou conteúdo, eval precisa de gold update) →
  rode `eval-set-reviewer` agent, atualize `eval/queries.yaml`,
  re-rode orchestrator.
- Parser regression (mais provável) → escreva test pinning o caso,
  fix o parser, faça outro commit.

### 2b. pytest falhou (antes do re-embed)

Sintoma: "pytest failed; aborting BEFORE re-embed (saves $$)".

Causa: invariante do schema quebrou (URN format, partição naming) ou
parser test failed.

**Resolução:** rodar `uv run pytest -v` local, identificar test failing,
fix o code, commit.

### 2c. Voyage / Planalto API outage

Sintoma: timeouts, HTTP errors no log.

**Resolução:** transiente. Re-trigger manualmente via
**Actions tab → Weekly corpus refresh → Run workflow** depois de algumas
horas. Se persistir > 24h, investigar o serviço externo.

### 2d. F5 WAF mudou o pattern de injeção

Sintoma: todos os docs vêm como CHANGED toda semana, mesmo sem mudança
real (audit log enche de noise).

**Diagnose:**
```bash
# Compara dois fetches sucessivos do mesmo doc
uv run python <<EOF
import asyncio
from rag_leis.planalto import PlanaltoScraper
async def main():
    async with PlanaltoScraper() as s:
        h1 = (await s.fetch("https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm")).html
        h2 = (await s.fetch("https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm")).html
    # Find first 3 differing positions
    for i, (a, b) in enumerate(zip(h1, h2)):
        if a != b:
            print(f"pos {i}: {h1[max(0,i-50):i+50]!r} vs {h2[max(0,i-50):i+50]!r}")
            break
asyncio.run(main())
EOF
```

**Resolução:** estender `_F5_CSPM_RE` (ou adicionar segundo padrão) em
`rag_leis/diff_audit.py`. Adicionar test que pinna o novo padrão.

## Cenário 3 — Issue `Post-merge smoke FAILED — <sha>`

**Quando aparece:** smoke-test.yml achou regression depois de um merge em
main (geralmente o próprio PR do refresh, ou um merge manual de feature).

**Diagnose:**
```bash
# Reproduzir local
git checkout <sha>
uv run python -m scripts.smoke_test_rag
```

Falhas comuns:
- **Crash:** stack trace no log; geralmente bug introduzido no PR. Revert ou fix-forward.
- **Empty answer:** Sabiá retornou nada — provável problema de SYSTEM_PROMPT ou queda do retrieval (cite-and-verify rejeitou tudo).
- **Refusal:** Sabiá refusou query que deveria ser in-scope — SYSTEM_PROMPT pode precisar iteração.

**Resolução:** fix em branch separado, PR normal, smoke-test roda automatically em main após merge.

## Quando NÃO usar este runbook

- **Mudança de modelo embedder** (ex.: voyage-3-large → outro) → reset
  o baseline metrics file e re-rode manual primeiro. O gate `is_degradation`
  pula a comparação automaticamente quando model muda, mas é melhor não
  triggerar isso via cron.
- **Mudança de text-mode** → idem. Atualizar `EMBEDDER` / `TEXT_MODE` em
  `scripts/refresh_corpus.py` é mudança de config, não de data.
- **Adicionar novo doc ao corpus** (extending TIER_1/2) → fazer via PR
  manual normal. O próximo cron vai tratá-lo como NEW (esperado).

## Métricas operacionais alvo

Após ~1 mês de operação:
- ≥75% das semanas: zero notification (steady state)
- ≤25% das semanas: 1-2 PRs com diff legítimo
- ≤1/mês: issue de failure (qualquer tipo)
- 100% dos PRs revisados em ≤7 dias

Se desviar significativamente desses números, revisitar o plano Phase 7
para identificar fricção operacional não prevista.
