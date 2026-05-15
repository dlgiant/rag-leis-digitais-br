# Backlog

Itens identificados mas não-aplicados — pra retomar quando for prioridade.

## ⚠️ Pre-launch dependency: lawyer review

Antes de Phase 9 (compliance) acontecer, há trabalho de validação
jurídica externa acumulando. Lista priorizada está em
**`study/lawyer-review-checklist.md`** — referência canônica desse
escopo. Inclui:

- 🔴 Bloqueadores: hierarquia normativa quando fontes secundárias
  mascaram primárias (ex: row 7 sanções), vigência overlay
  insuficiente, cross-doc gold incompleto
- 🟡 Importantes: 3rd precision tier, OOS adversariais, PII coverage
- 🟢 Refinamentos: citation prose check, source-as-of-date

D7 do `study/post-review-plan.md`: "vou conseguir antes de Phase 9 mas
não agora". Quando contratar, esse doc é o handoff list.

## Eval / gold

- **Revisar gold da query Tier-2 [T8] cross-doc** — "interação digital com o governo: proteção de dados e princípios". Proposta original em `eval/tier-2-queries-proposal.md` listava core = `14129 art.3 inc17` + `LGPD art.6` + `LGPD art.6;inc7`, supporting = `LGPD art.46` + `14063 art.5`. Cross-doc Tier-1×Tier-2 precisa validação manual: a query é abrangente e o gold pode estar incompleto (mesma classe de queries onde [13] foi corrigido em sessão anterior). Aplicar T1-T7 sem este, voltar com revisão dedicada.

- **Investigar 597 dedups silenciosos no parser CF** — logging em `_dedup_keep_last` (commit `449d89f`) expôs que o parser colapsa 597 chunks duplicados na Constituição, plus 140/35/26/15/4 em outras leis. Não fixei agora porque é refactor do parser. Pode estar perdendo conteúdo legítimo (semelhante ao bug do `len < 10` proxy que filtrava "multa;" como revogado).

## Parser

- **Refatorar parser.py** — atualmente monolítico, regex-heavy. Quebrar em estágios menores testáveis (extract paragraphs → classify partition → assign parents → strip notes). Fazer junto com 0.2 Parser protocol pra Tier-3 PDFs.

## Tier-3 (deferred)

- **AnpdPdfParser** — PDFs das resoluções ANPD. ~1 semana de trabalho (reviewer estimou).
- **Documentar synthetic URN scheme da ANPD** em `study/lexml-urn-spec-resumo.md` antes de qualquer chunk Tier-3 entrar.

## LLM stage (Phase 2)

Phase 2.1-2.7 implemented. Open items:

- **Sonnet-4-5 non-deterministic refusal on row 7 (sanções ANPD)** — across 3 runs of `eval/answer_queries.yaml`, the sanções LGPD query alternated between (a) a partial enumeração citing 1-2 of 10 incs and (b) a self-refusal "Não há informação suficiente" despite the gold being in top-10 context. Row 7's 10 gold URNs vs top_k=10 means the model often sees the caput + 9 incs and apparently judges that as not-enough. Two paths: (i) raise top_k for enumeração queries (need a query-type classifier; see Phase 2.6 deferred top_k decision), or (ii) tweak system prompt to be less defensive when ≥1 gold inciso is present. Both want measurement first — re-run row 7 alone N times to quantify the flip rate.

- **Lenient precision sweep** — currently `alternative_acceptable_urns` is set on 3 rows (2, 9, 10). Rows 1, 3, 5, 6, 8 might also benefit from sibling-as-alt curation; sweep them and see if mean lenient P stabilizes higher.

- **OOS test set is tiny** — 3 rows in v0. Need 8-12 OOS queries spanning different "kinds of OOS" (other domain entirely / adjacent domain with no Brazilian-digital-law connection / partially-in-corpus where 1 chunk references something the query asks about). Current 3 are all "other domain entirely".

- **Cosine fast-path threshold (0.40) is uncalibrated** — with the LLM self-refusal as primary OOS signal, the cosine gate matters only for the case "wrong-language paste" / "single emoji" type input. Worth a synthetic test set to confirm 0.40 doesn't false-positive any in-scope query AND does fast-path obvious garbage.

- **Phase 3 candidates**: retry policy on rejected_citations > 0; multi-turn (followup with refined query); reasoning trace exposure; per-query latency/cost reporting; hybrid generator (route enumeração to opus-4-7 for higher recall ceiling).

## Posts (`posts/`, gitignored)

- **Atualizar 3 drafts existentes** com números pós gold expansion (paráfrase MRR 0.40 → 0.86) e voyage rerank-2.5 re-eval.
- **Escrever 4º draft**: "Como gold incompleto mente sobre o seu retriever" — caso voyage rerank-2.5 que inverteu de +0.022 → ~zero com gold rico.
