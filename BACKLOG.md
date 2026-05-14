# Backlog

Itens identificados mas não-aplicados — pra retomar quando for prioridade.

## Eval / gold

- **Revisar gold da query Tier-2 [T8] cross-doc** — "interação digital com o governo: proteção de dados e princípios". Proposta original em `eval/tier-2-queries-proposal.md` listava core = `14129 art.3 inc17` + `LGPD art.6` + `LGPD art.6;inc7`, supporting = `LGPD art.46` + `14063 art.5`. Cross-doc Tier-1×Tier-2 precisa validação manual: a query é abrangente e o gold pode estar incompleto (mesma classe de queries onde [13] foi corrigido em sessão anterior). Aplicar T1-T7 sem este, voltar com revisão dedicada.

- **Investigar 597 dedups silenciosos no parser CF** — logging em `_dedup_keep_last` (commit `449d89f`) expôs que o parser colapsa 597 chunks duplicados na Constituição, plus 140/35/26/15/4 em outras leis. Não fixei agora porque é refactor do parser. Pode estar perdendo conteúdo legítimo (semelhante ao bug do `len < 10` proxy que filtrava "multa;" como revogado).

## Parser

- **Refatorar parser.py** — atualmente monolítico, regex-heavy. Quebrar em estágios menores testáveis (extract paragraphs → classify partition → assign parents → strip notes). Fazer junto com 0.2 Parser protocol pra Tier-3 PDFs.

## Tier-3 (deferred)

- **AnpdPdfParser** — PDFs das resoluções ANPD. ~1 semana de trabalho (reviewer estimou).
- **Documentar synthetic URN scheme da ANPD** em `study/lexml-urn-spec-resumo.md` antes de qualquer chunk Tier-3 entrar.

## LLM stage (Phase 2 do plano)

- **Structured output schema** `{answer, citations: [urn], unverified_claims: [str]}`.
- **Cite-and-verify post-check** — URN ∈ corpus ∧ ∈ top-K context.
- **OOS routing** — refusal threshold from held-out queries.
- **Answer-eval set** — 15 rows {query, expected paragraph, gold URNs} pra medir faithfulness.

## Posts (`posts/`, gitignored)

- **Atualizar 3 drafts existentes** com números pós gold expansion (paráfrase MRR 0.40 → 0.86) e voyage rerank-2.5 re-eval.
- **Escrever 4º draft**: "Como gold incompleto mente sobre o seu retriever" — caso voyage rerank-2.5 que inverteu de +0.022 → ~zero com gold rico.
