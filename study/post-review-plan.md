# Post-Review Plan — Round 2 (legal-domain pass)

**Status**: design (não-implementado). 2026-05-14, post-Phase-2 merge.

Reviewer round 2 (legal-domain) flagged 12 items grouped by gravity. The
retrieval and pipeline layers are working; the failures from here on are
**legal, not technical**: the system is precise about *what the text
says* and naïve about *what the text is worth*.

This document maps each reviewer item to a concrete deliverable, sequenced
into 4 follow-on phases. Phase 2 is done (LLM contract); Phase 3 starts
here. The reviewer's own ranking (P0/P1/P2/P3) drives the phase boundaries
plus a couple of items we hoist forward because they're cheap.

## Mapping — reviewer item → phase → sizing

| # | Reviewer item | Phase | Pri | Size | Type |
|---|---|---|---|---|---|
| 1 | Vigência overlay (suspenso/sub judice/vacatio) | 3 | P0 | ½ d code + ½ d curation | Data + code |
| 2 | ANPD resoluções (Tier-3 PDF parser) | 4 | P1 | ~1 wk | Corpus + parser |
| 3 | Normative hierarchy (`legal_rank`) | 5 | P2 | 2 h | Code |
| 4 | Cross-doc undersized (8 → ≥30) | 5 | P2 | 1 d | Eval curation |
| 5 | Citation precision tier 3 ("juiz aceitaria") | 5 | P2 | ½ d code + ½ d curation | Eval + code |
| 6 | Human-citation regex check (`Art. 5, XII` vs URN) | 5 | P2 | 2 h | Code |
| 7 | Source-as-of-date in answer footer | 5 | P2 | 3 h | Code |
| 8 | Input PII redactor (CPF/CNPJ/email/phone) | 4 | P1 | 2 h | Code |
| 9 | OOS taxonomy (3 → ≥15, 5 subtypes) | 5 | P2 | ½ d | Eval curation |
| 10 | Query-type classifier + adaptive top_k | 4 | P1 | ½ d | Code |
| 11 | ADCT + EC linkage (`amended_by`) | 5 | P2 | ½ d | Parser |
| 12a | Add Lei 9.507/97 (habeas data procedimento) | 3 | P0 | 1 h | Corpus |
| 12b | Decreto 8.771 cross-test query | 5 | P2 | 30 min | Eval |
| 12c | Update README declared scope (CDC, etc.) | 3 | P0 | 5 min | Docs |
| (4) | STF/STJ jurisprudência (Tier-4) | 6 | P3 | ~2 wk | Corpus + URN spec |

## Phase 3 — P0 legal correctness (~1.5 dias)

**Goal**: eliminate the two errors a banca académica would flunk on sight.

### 3.1 Vigência overlay (~1 dia)

The big one. Today `is_revoked_text` only catches Planalto markers
`(Revogado)`/`(Vetado)`/`(Suprimido)`. Misses: revogação tácita,
suspensão por liminar, sub judice (ex: MCI art. 19, STF Tema 987),
vacatio legis parcial (LGPD sanções diferidas pra 2021), eficácia
limitada por regulamentação (LGPD art. 52 §1 → ANPD Res. 4/2023).

**Deliverables**:

- `data/vigencia/overlays.yaml` — hand-curated, ~20 dispositivos
  sensíveis. Schema:
  ```yaml
  - urn: urn:lex:br:federal:lei:2014-04-23;12965~art19
    status: sub_judice
    fundamento: STF RE 1.037.396 (Tema 987)
    desde: 2017-09-29
    descricao_curta: |
      Aplicação em discussão no STF. Tese de repercussão geral pendente.
  ```
- `rag_leis/vigencia.py` — `Vigencia` dataclass, `load_overlays(path)`,
  `apply_overlays(chunks, overlays)`
- `Chunk.vigencia: Vigencia | None` (field on chunk, populated post-parse)
- `RAGPipeline._build_context()` — when chunk has overlay, render in
  `<fonte>` tag: `<fonte urn="..." vigencia="sub_judice (STF Tema 987)">`
- `SYSTEM_PROMPT` update — explicit instruction: *"Se uma `<fonte>`
  tiver atributo `vigencia` diferente de 'vigente', SINALIZE no answer
  com formato '⚠️ Atenção: dispositivo com vigência ressalvada — <descricao>'."*
- `RAGAnswer.flagged_vigencia: list[dict]` — surface to caller for UI
- Golden test: `test_vigencia_mci_art19_flagged()` — pipeline answer
  for an MCI art. 19 query must contain the warning string

**Open decisions (surface to user before coding)**:
- Who curates the 20 entries? Two options:
  - (i) I draft 20 from public knowledge, user reviews
  - (ii) User dictates the list, I implement schema+code only
- Should `flagged_vigencia` block the answer or just annotate?
  Recommend annotate (consistent with existing `unverified_claims`
  pattern — let the UI / caller decide policy).

### 3.2 Add Lei 9.507/97 (procedimento do habeas data) (~1 hora)

Closes a gold-incompletude already shipped: the habeas data answer-eval
gold cites only CF art. 5º LXXII, but no senior lawyer answers habeas
data without the procedural law.

**Deliverables**:
- Append to `corpus.py` `TIER_1`: `Document(urn="urn:lex:br:federal:lei:1997-11-12;9507", ...)`
- `uv run python -m rag_leis.fetch_tier --tier 1` (incremental)
- `uv run python -m rag_leis.parse_all_tier --tier 1` (incremental)
- Rebuild voyage index: `uv run python -m rag_leis.run_eval --model voyage-3-large --text-mode label+nav+caput+text` (auto-rebuild via content hash)
- Update `eval/answer_queries.yaml` row 4 (habeas data definicao) and
  row 12 (cross-doc): add 2-4 chunks from 9.507 to gold + tweak
  expected_paragraph
- Run answer-eval to confirm metrics improve on rows 4/12

### 3.3 README scope declaration (~5 min)

The README claims coverage of "resoluções da ANPD" which don't exist
yet, and omits CDC (which is in the corpus with 471 chunks). Declared-
vs-actual mismatch is a compliance flag in itself.

**Deliverables**: edit README.md cobertura sentence to reflect actual
TIER_1 (12 docs) + TIER_2 (3 docs) + remove ANPD claim (or move to
"em construção (Phase 4)").

## Phase 4 — P1 practitioner-grade (~2 semanas)

**Goal**: take the system from "TCC demo" to "ferramenta auxiliar com
supervisão humana".

### 4.1 Query-type classifier + adaptive top_k (~½ dia)

Closes the deferred Phase 2.6 decision and the BACKLOG item about row 7
non-determinism. Today every query gets `top_k=10` regardless of whether
it's a literal citation (probably needs 1 chunk) or an enumeração
(needs 10-30).

**Deliverables**:
- `rag_leis/query_type.py` — regex classifier:
  - `r"\b(quais|liste|enumere)\b"` → enumeracao
  - `r"\b(o que (?:é|são)|defina)\b"` → definicao
  - `r"\bart(?:igo)?\.?\s*\d+"` → citacao-literal
  - `r"\b(diferença|comparação|relação)\b"` → cross-doc
  - fallback: parafrase
  - tests: 8-10 cases including ambiguities ("quais artigos da LGPD" → enumeracao not citacao-literal)
- `rag_leis/rag.py` — `RAGPipeline.answer()` runs classifier, picks
  `top_k_per_type = {definicao: 10, enumeracao: 25, citacao_literal: 8, cross_doc: 15, parafrase: 10}`
- Per-type prompt snippet appended to `SYSTEM_PROMPT` (eg enumeração
  gets "se a query é enumeração, prefira listas explícitas com todos
  os incisos disponíveis no contexto")
- Re-run answer-eval to confirm row 7 (enumeração sanções) improves

**Open decision**: query-type as field on `RAGAnswer`? Useful for
analysis. Recommend yes — `RAGAnswer.classified_type: str`.

### 4.2 Input PII redactor (~2 horas)

The system describes LGPD compliance and itself doesn't comply: a query
"O CPF 123.456.789-00 do João Silva foi vazado" sends dados pessoais
sensíveis to Anthropic verbatim.

**Deliverables**:
- `rag_leis/pii.py` — regex patterns:
  - CPF: `r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"` + variants
  - CNPJ: `r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"`
  - email: standard
  - phone: `\(?\d{2}\)?\s?\d{4,5}-?\d{4}` (BR formats)
  - RG: regional patterns (skip — too noisy)
  - CEP: `\d{5}-?\d{3}`
- `redact(text) → (redacted_text, mapping)` — substitutes with `[CPF#1]`, `[EMAIL#1]` etc., returns mapping
- `unredact(text, mapping)` — for symmetric reinjection if a UI wants original answer
- `RAGPipeline.answer()` — apply redact pre-LLM, optionally unredact post
- `run_answer_eval.py` — log `hash(query)` instead of literal query in JSON output (LGPD compliance for the eval logs themselves)
- 6-8 unit tests (positive + non-matching benign content)

**Defer**: pt-BR NER for nomes próprios (needs spaCy pt or HF model).
Big complexity uplift; not worth it pre-deploy. Add as Phase 5 nice-to-have.

### 4.3 ANPD resoluções — Tier-3 PDF parser (~1 semana)

Practitioner-grade requires the operational layer: ANPD Res. 1/2021
(sancionatório), 2/2022 (pequeno porte), 4/2023 (dosimetria), 15/2024
(notificação de incidente — **3 dias úteis**, the actual answer to
"prazo de notificação de incidente?"). Without these, LGPD art. 48
returns vague language and the practitioner doesn't see the deadline.

**Deliverables**:
- `rag_leis/parsers/anpd_pdf.py` — implements `Parser` protocol from
  Phase 0; uses `pdfplumber` (cleaner table handling than pypdf for ANPD's
  layout). Maps ANPD's resolução structure (Considerandos, Capítulos,
  Seções, Artigos, §§, Incs) to LCP-95 partitions
- Extend `study/lexml-urn-spec-resumo.md` — synthetic URN scheme for
  ANPD: `urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:<date>;<num>`
- `rag_leis/corpus.py` — new `TIER_3` list with 4 resoluções
- `data/raw/tier-3/` — fetch HTML if available, PDF as fallback
- New tests: parser golden tests (1 fixture per resolução), URN format check
- Re-run full pipeline (parse → chunk → embed → eval)

**Open decisions (need user input before)**:
- Which 4 resoluções to include? Reviewer named 4; defer beyond MVP.
- HTML or PDF source? ANPD publishes both; HTML preferred.
- Indexing alongside Tier-1/2 in same voyage index? Recommend yes
  (`run_eval` already supports rglob).

## Phase 5 — P2 robustness (~4-5 dias)

### 5.1 OOS taxonomy + 3 → ≥15 expansion (~½ dia)

Current 3 OOS rows are all "different domain entirely" — trivial. Real
hallucination risk is **adjacent OOS**: query touches the corpus's
neighborhood but no answer exists.

**Deliverables**:
- Schema extension: `oos_subtype` field with 5 values
  - `(a)` other_domain — outras matérias inteiras (IRPF, divórcio)
  - `(b)` adjacent_no_coverage — direito digital com matéria fora (Marco Legal Startups, processual)
  - `(c)` projeto_de_lei — PLs não promulgados (PL 2338 IA, PL 2630 fake news)
  - `(d)` materia_estadual_municipal — fora da competência federal
  - `(e)` doutrina_sem_positivacao — direito ao esquecimento pré-Tema 786
- Add 12 OOS rows (~2-3 per subtype)
- Type-specific refusal templates in SYSTEM_PROMPT (eg `(c)` triggers "esta matéria não tem norma federal vigente; existem PLs em tramitação que esta base não acompanha")
- Re-run answer-eval to measure subtype-level refusal accuracy

### 5.2 `legal_rank` + tie-breaker (~2 horas)

Today the retriever can rank Decreto 8.771 above MCI art. 9 if it's
lexically closer. A `top-K` mix of CF + Decreto with no precedence
misrepresents how a lawyer weighs sources.

**Deliverables**:
- `Chunk.legal_rank: int` — auto-derived from URN type:
  - 1 = CF / EC (`constituicao`, `emenda.constitucional`)
  - 2 = LC (`lei.complementar`)
  - 3 = LO/MP (`lei`, `decreto.lei`, `medida.provisoria`)
  - 4 = Decreto (`decreto`)
  - 5 = Resolução / Portaria (`resolucao`, `portaria`)
- Tie-breaker on cosine equality: lower `legal_rank` wins (rare in dense retrieval, more relevant for hybrid)
- `RAGAnswer.hierarchy_warning: str | None` — set when answer cites
  rank≥4 chunk while rank≤3 chunk was in top-K
- Render warning in answer footer (consistent with vigência overlay)

### 5.3 Human-citation regex check (~2 horas)

`verify_citations` checks JSON `citations[]`. The `answer` prose can
say "Art. 5º, **XII**" while URN points to `inc10` — verifier doesn't
see that. The reader sees "XII".

**Deliverables**:
- `rag_leis/verify.py` — new `verify_prose_citations(answer_text, citation_urns, chunks_by_urn) → list[ProseMismatch]`
- Regex extract `Art\.\s*\d+(-[A-Z])?[º°]?(?:,\s*§?\s*\d+[º°]?)?(?:,\s*[IVXLCDM]+)?(?:,\s*[a-z]\))?`
- For each match, look up the corresponding URN via citation chain
  (the `IndexChunk.citation` field already gives reverse mapping)
- Return mismatches: `("Art. 5º, XII", expected_urn=art5;inc12, but cited URNs are [art5;inc10])`
- `RAGAnswer.prose_citation_mismatches: list[ProseMismatch]`
- **Decision pendente**: refuse on mismatch (re-prompt) OR flag (annotate).
  Recommend flag for v1; refuse adds latency + complexity.

### 5.4 Cross-doc expansion 8 → ≥30 (~1 dia)

Direito digital is cross-doc by nature: LGPD ↔ MCI ↔ CDC ↔ CF ↔ CP.
Current 8 cross-doc queries are inadequate. Reviewer flags 3 missing:
vazamento+CDC+STJ Súmula 479, direito ao esquecimento, dados de crianças.

**Deliverables**:
- 22 new cross-doc rows in `eval/queries.yaml` (retrieval) + ~5 in
  `eval/answer_queries.yaml` (answer-eval)
- Schema extension on cross-doc rows:
  ```yaml
  type: cross-doc
  cross_doc_relationship:
    primary: urn:...
    companions:
      - urn: urn:...
        relationship: regulamenta | derroga | integra | contradiz | complementa
  ```
- Update eval-set-reviewer subagent prompt to validate cross-doc gold

### 5.5 Source-as-of-date (~3 horas)

Practitioner-grade output needs `consultado em DD/MM/AAAA` per source.

**Deliverables**:
- `rag_leis/fetch_tier.py` already records `fetched_at`? Check; if not, add
- Propagate through Chunk metadata → IndexChunk → RAGAnswer
- `RAGAnswer.sources_consulted_at: dict[doc_urn, ISO_date]` (one date per doc, not per chunk)
- `SYSTEM_PROMPT` instructs to render footer: *"Fontes consultadas em: LGPD (14/05/2026), MCI (14/05/2026), ..."*
- Render the footer outside the LLM-controlled `answer` field — append in
  Pipeline post-process so we control format

### 5.6 3rd precision tier ("juiz aceitaria") (~½ dia)

Current `gold_urns` (strict) + `alternative_acceptable_urns` (lenient)
hides the practitioner-relevant question: cita o dispositivo na
**granularidade que um juiz aceitaria**? A peça processual that cites
"art. 7" when the rule is in `art. 7, § 6º` is sloppy — accepted by
lenient, rejected by judicial standards.

**Deliverables**:
- 3rd column in answer-eval YAML: `judicial_acceptable_urns` (subset
  of strict gold, with explicit granularity)
- 3rd metric: `cit_precision_judicial = |cited ∩ judicial_acceptable| / |cited|`
- Type-aware floors enforced *as a metric*, not a hard reject:
  - `definicao` → top cite must be `kind=artigo` (not § or inc)
  - `enumeracao` → all vigente incs cited (not just caput)
  - `citacao-literal` → exact requested URN (the requested label resolved)
- Hand-curate 3rd column for the 12 in-scope rows
- Aggregate now reports 3 precision numbers: strict, judicial, lenient

### 5.7 ADCT + EC linkage (`amended_by`) (~½ dia)

Constitutional chunks need to carry which EC introduced their current
redação. Today the dedup-last-wins discards that linkage.

**Deliverables**:
- Parser change: extract `(Redação dada pela Emenda Constitucional nº X)` from text and into `Chunk.amended_by: list[str]` (e.g., `["EC-115/2022"]`)
- Verify CF `art5;inc79` (EC 115/2022 — proteção de dados como direito fundamental) is indexed
- Add eval query: *"proteção de dados é direito fundamental?"* — gold should put `art5;inc79` first

### 5.8 Decreto 8.771 cross-test query (~30 min)

Add to `eval/queries.yaml`: *"O que o decreto regulamentador do MCI diz sobre guarda de logs?"* — forces lei → decreto traversal. Gold:
Decreto 8.771 art. 13 + MCI art. 13.

## Phase 6 — P3 pesquisa-jurídica tool (~2-3 semanas)

### 6.1 STF/STJ jurisprudência Tier-4 (~2 semanas)

Synthetic URN scheme + scraper + parser for:
- STJ Súmulas (227, 403, 479)
- STF Temas vinculantes (786 direito ao esquecimento, 987 MCI 19 pendente)
- Possivelmente: STF/STJ informativos selecionados

**Deliverables**:
- Extend `study/lexml-urn-spec-resumo.md` with jurisprudência URN form:
  - `urn:lex:br:supremo.tribunal.federal:tema:987`
  - `urn:lex:br:superior.tribunal.justica:sumula:227`
- New parser type (`Parser` protocol implementation)
- New `Chunk.kind = "jurisprudencia"`
- `legal_rank = 6` (or out-of-band — jurisprudência é vinculante mas não é norma)
- ~50-100 chunks total

### 6.2 Lei 12.414/2011 (Cadastro Positivo), Decreto 10.474/2020 (~2 hours)

Reviewer flags as "silent" gaps. Both are simple TIER_1 / TIER_2 adds.

## Cross-cutting design decisions

These touch multiple phases; resolve before starting Phase 3.

### CC1. Parser refactor

Phase 5 introduces 3 new fields on `Chunk`: `vigencia`, `legal_rank`,
`amended_by`. Plus `fetched_at` propagation. The parser is already
flagged for refactor in BACKLOG. Recommendation: do parser refactor
**alongside** Phase 3 vigência (since it's the first new field), not
separately. Sized as part of Phase 3 (~2 extra hours).

### CC2. RAGAnswer field proliferation

After Phase 5 the RAGAnswer dataclass grows several status fields:
`flagged_vigencia`, `hierarchy_warning`, `prose_citation_mismatches`,
`sources_consulted_at`. Consider grouping into a `RAGAnswer.warnings:
list[Warning]` with structured types. Defer — premature abstraction
without the call sites speaking yet.

### CC3. Eval set v3

Phase 5 expands answer-eval significantly: cross-doc 8 → ≥30, OOS 3 → ≥15,
3rd precision tier hand-curated. By end of Phase 5 we'll have ~40-50 rows.
Worth versioning: rename `answer_queries.yaml` → `answer_queries_v3.yaml`
when 5.4+5.6 land, or mantain v2 → v3 in study notes.

### CC4. README scope declaration is the cheapest legal-risk fix in the project

Item 12c is 5 minutes and closes a "compliance flag" (declared vs actual).
Hoist it to Phase 3 even though it's not technically P0 — same delivery
window, zero coupling to other items.

## Suggested phase ordering & timing

| Phase | Items | Wall clock | API/data cost |
|---|---|---|---|
| **3** | 3.1, 3.2, 3.3 + parser refactor groundwork | ~1.5 dias | $0 (no new corpus) |
| **4** | 4.1, 4.2, 4.3 (Tier-3 ANPD is the long pole) | ~2 semanas | ~$5 voyage re-embed |
| **5** | 5.1-5.8 (5.4 cross-doc curation is the long pole) | ~4-5 dias | ~$1 eval re-runs |
| **6** | 6.1, 6.2 | ~2-3 semanas | ~$5 |

**Sequential reasoning**: Phase 3 must come first (corrigir o que está
publicado errado). Phase 4 ANPD (4.3) is the biggest single piece — could
parallelize 4.1 + 4.2 if you're impatient. Phase 5 items mostly
independent; can pick-and-choose. Phase 6 is "nice to have" for academic
demo, "essential" for production tool.

## Decisões a surface antes de começar Phase 3

| # | Decisão | Recomendação default |
|---|---|---|
| D1 | Quem cura os 20 dispositivos da `vigencia/overlays.yaml`? | (i) eu rascunho, você revisa |
| D2 | `flagged_vigencia` bloqueia ou anota? | anota (consistente com `unverified_claims`) |
| D3 | Phase 3 inclui parser refactor (CC1)? | sim, ~+2h, evita 2 mudanças de mesma natureza |
| D4 | Lei 9.507/97 fica em Tier-1 ou novo subgrupo "instrumentos"? | Tier-1 (mesma natureza) |
| D5 | Phase 4 ordem: ANPD primeiro (longo) ou query-classifier+PII (curtos) primeiro? | curtos primeiro — compounding gain pra todas as queries |

## Open items NOT in this plan

- Phase 2.8 write-up (`study/phase-2-results.md`) — completar antes ou
  depois de Phase 3? Recomendação: depois de Phase 3, pra incluir o
  vigência overlay como evidência "fix the data, not the model" estende
  pra dimensão jurídica.
- BACKLOG "597 silent dedups in CF parser" — investigar como parte do
  parser refactor (CC1).
- Posts (`posts/`, gitignored) — atualizar quando Phase 3 fechar pra
  capturar a evolução "engineering review → legal review".

## Verdict do reviewer

> Phase 3 (P0) closes the two failures an academic banca would flunk on
> sight. Phase 4 (P1) takes the system from "TCC demo" to "ferramenta
> auxiliar de escritório com supervisão humana". Phase 6 (P3) separates
> this from a real pesquisa-jurídica tool.

Concordo. Recomendação: começar Phase 3 **agora**, antes do write-up de
2.8, porque P0 não é "incremento" — é correção do que já foi publicado.
