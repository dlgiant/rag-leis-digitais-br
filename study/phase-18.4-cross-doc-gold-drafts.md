# Phase 18.4 — cross-doc gold drafts review checklist

**For:** the lawyer / D7 reviewer (intermittent attention path).
**Source spec:** `study/lawyer-review-checklist.md:110-122`.
**Operator status (2026-05-22):** schema + 5 drafts shipped; awaiting
review. No D7 contract gate.

## What changed

Two pieces of infrastructure landed alongside the drafts:

1. **Schema extension** — `rag_leis/run_answer_eval.py` `AnswerQuery`
   dataclass gained `companion_urns: tuple[tuple[str, str], ...]`. Each
   pair is `(urn, relationship)` where `relationship` ∈
   `{regulamenta, integra, contradiz, complementa}` validated at YAML
   load time.
2. **Drafts file** — `eval/answer_queries_cross_doc_drafts.yaml` holds
   the 5 row drafts. The production `eval/answer_queries.yaml` is
   unchanged — drafts can't pollute eval until manually merged.

## The relationship vocabulary

| Relationship | When to use | Example |
|---|---|---|
| `regulamenta` | A is a regulamento (decree, resolution) of B (lei) | Res. CD/ANPD 4/2023 *regulamenta* LGPD art. 52 |
| `integra` | A is structurally integral to B — same legal architecture | ECA art. 17 *integra* LGPD art. 14 (general personality rights ↔ data-specific rule) |
| `contradiz` | A contradicts / overrides / suspends B | (none in current drafts) |
| `complementa` | A and B both address the topic from different legal angles | CDC art. 14 *complementa* LGPD art. 42 (fornecedor liability ↔ controlador liability for same data breach) |

**Open question for the lawyer:** the current 4-category schema doesn't
have a clean slot for jurisprudência that interprets a rule (Súmula 479
STJ interpreting CDC art. 14; Tema 786 STF interpreting "direito ao
esquecimento"). The drafts use `complementa` as a stand-in. If a 5th
relationship (`interpreta`?) is needed, propose it and the schema can
be extended.

## Per-row questions

### Row 1 — Vazamento de dados de consumidor

**Query:** "houve vazamento de dados de um consumidor pessoa física;
qual a responsabilidade civil do controlador segundo a LGPD e o CDC?"

**Operator draft:** primary gold = LGPD art. 42; companions = CDC
art. 14 (`complementa`) + Súmula 479 STJ (`complementa`).

**For the lawyer:**
- Is art. 42 the right primary gold, or should art. 43 (eximentes) be
  primary in any common framing?
- Should CDC art. 14 be `complementa` or maybe `integra` (when the
  titular is consumidor, CDC is structurally integral to the
  liability analysis)?
- Súmula 479 STJ is currently `complementa` — propose a better
  relationship if available.
- Is the `expected_paragraph` wording the right legal characterization?

### Row 2 — Direito ao esquecimento

**Query:** "existe direito ao esquecimento na internet no direito
brasileiro?"

**Operator draft:** primary gold = STF Tema 786 ~tese; companions =
CF art. 5 X (`integra`) + MCI art. 19 (`complementa`).

**For the lawyer:**
- The answer is "no — STF rejected it as autonomous tese". Is naming
  Tema 786 as primary the right framing, or should CF art. 5 X be
  primary with Tema 786 as supporting (since the constitutional
  basis remains the underlying right)?
- MCI art. 19 is currently under `alterado_por_jurisprudencia`
  (Tema 987, 2024-06-26). Should this be reflected in the answer
  with the ⚠️ marker the SYSTEM_PROMPT generates?
- The current paragraph mentions the vigência overlay — is this the
  right way to surface it in a cross-doc context?

### Row 3 — Crianças e adolescentes

**Query:** "como a LGPD trata dados pessoais de crianças e
adolescentes?"

**Operator draft:** primary gold = LGPD art. 14; companions = ECA
art. 17 (`integra`) + CDC art. 39 (`complementa`).

**For the lawyer:**
- ECA art. 17 was indexed in Phase 18.1 specifically to close this
  cross-doc. Is it the right ECA article — or is art. 78 (exposição
  em ato infracional) also relevant for the "data tratamento" framing?
- CDC art. 39 IV is about "fraqueza/ignorância do consumidor" — a
  stretch to apply to data treatment of minors? Drop it or keep it?

### Row 4 — Notificação de incidente

**Query:** "qual o prazo e o conteúdo da notificação de incidente de
segurança envolvendo dados pessoais?"

**Operator draft:** primary gold = LGPD art. 48; companion = Res.
CD/ANPD 15/2024 art. 6 (`regulamenta`).

**For the lawyer (operator self-correction 2026-05-22):**
- An earlier draft of this section incorrectly described Res. 15/2024
  as a public-sector small-agents regulation. Reading the actual chunk
  text (art. 1) disproved it — **Res. 15/2024 IS the incident-
  notification regulamento**: "Este Regulamento tem por objetivo
  estabelecer os procedimentos para Comunicação de Incidente de
  Segurança, que possa acarretar risco ou dano relevante aos
  titulares, nos termos do art. 48 da Lei nº 13.709/2018". Art. 6
  fixes the 3-business-day deadline.
- The lawyer-review-checklist citation (Res. 15/2024 art. 6) is
  therefore CORRECT and the `regulamenta` relationship typing holds.
- Open question for the lawyer: is the `expected_paragraph`'s "prazo
  razoável (a LGPD não fixa um número específico — a ANPD considera
  razoável 3 dias úteis nos termos de sua regulamentação setorial)"
  phrasing right? The current draft soft-pedals the deadline; given
  Res. 15/2024 art. 6 actually fixes 3 dias úteis as the rule (with
  the "ressalvada legislação específica" carve-out), it might be
  more accurate to say the deadline IS 3 business days.

### Row 5 — Sanções / dosimetria

**Query:** "como funciona a dosimetria das sanções da LGPD pela ANPD?"

**Operator draft:** primary gold = LGPD art. 52; companion = Res.
CD/ANPD 4/2023 art. 1 (`regulamenta`).

**For the lawyer:**
- Res. CD/ANPD 1/2021 (regimento interno) and 2/2022 (agentes de
  pequeno porte) are NOT yet indexed (Phase 18.2 work). The draft
  doesn't cite them in companion_urns (would generate eval misses).
  When Phase 18.2 lands, this row should be updated with both as
  `regulamenta`. **Decision needed:** is Res. 4/2023 art. 1 enough
  for now, or should the row be deferred entirely until 18.2
  closes?
- The current `expected_paragraph` lists all 8 sanções (advertência
  through proibição parcial/total). A senior litigator might
  compress to 3-4 most-used. Lawyer's call.

## How to merge after review

When the lawyer signs off (per-row), the operator runs:

```
# For each blessed row, copy the dict from
# eval/answer_queries_cross_doc_drafts.yaml into
# eval/answer_queries.yaml under the # cross-doc section.
# Remove the `draft_status:` field. Delete the blessed row from
# the drafts file. When all 5 are blessed, delete the drafts file
# entirely.
```

No tooling beyond manual YAML editing — the rows are small enough
that a script would be more error-prone than a copy-paste.

## What to NOT change

- The schema (`AnswerQuery.companion_urns` + `_VALID_RELATIONSHIPS`)
  ships now; reviewing it is in scope but reverting is not (other
  Phase 18.x work may build on it).
- The 5 drafts can have their **content** edited freely (URNs,
  relationships, paragraphs); the **structure** (the YAML keys)
  must match the schema or load_answer_queries will raise.
- Adding new relationship values: ok if needed, but ping the
  operator to update `_VALID_RELATIONSHIPS` first.

## Status flag in BACKLOG

Phase 18.4 will move from "drafts ready" → "shipped" only when at
least 3 of the 5 rows are blessed AND merged into
`eval/answer_queries.yaml`. Until then, the BACKLOG entry stays
"⏳ drafts awaiting lawyer review".
