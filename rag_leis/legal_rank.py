"""Hierarquia normativa brasileira → numeric rank for retrieval & answer auditing.

Reviewer round 2 item 3: Brazilian legal sources are NOT equivalent in
authority. CF/EC outranks Lei Complementar; LC outranks Lei Ordinária;
LO outranks Decreto; Decreto outranks Resolução. Today the cosine
retriever can rank Decreto 8.771 above MCI art. 9 if the lexical match
is closer — that's a misrepresentation of how a lawyer weighs sources.

This module attaches a numeric `legal_rank` to every chunk via its URN
type. Used by:

  - `IndexChunk.legal_rank` — populated at load_chunks time
  - `RAGAnswer.hierarchy_warning` — set when the LLM cites lower-rank
    sources while higher-rank ones were in top-K context

Rank scale (lower = higher authority):

  1  Constituição / Emenda Constitucional
  2  Lei Complementar
  3  Lei Ordinária / Decreto-Lei / Medida Provisória
  4  Decreto
  5  Resolução / Portaria / Instrução Normativa (and unknown defaults)

The mapping is hard-coded because Brazilian normative hierarchy is
fixed by the Constitution itself; the RAG can't legitimately reinterpret
it. Adding a new act type means deciding its rank in this table.
"""

from __future__ import annotations

# Rank constants — exposed for callers that compare directly.
RANK_CONSTITUCIONAL = 1
RANK_LEI_COMPLEMENTAR = 2
RANK_LEI_ORDINARIA = 3
RANK_DECRETO = 4
RANK_INFRALEGAL = 5


# URN type segment → rank. Matches `type` slot of `urn:lex:br:<jur>:<type>:<date>;<id>`.
LEGAL_RANK_BY_TYPE: dict[str, int] = {
    # Rank 1 — Constituição / Emendas
    "constituicao": RANK_CONSTITUCIONAL,
    "emenda.constitucional": RANK_CONSTITUCIONAL,
    # Rank 2 — Lei Complementar
    "lei.complementar": RANK_LEI_COMPLEMENTAR,
    # Rank 3 — Lei Ordinária + equiparados (Decreto-Lei sob CF/88 = LO; MP idem)
    "lei": RANK_LEI_ORDINARIA,
    "decreto.lei": RANK_LEI_ORDINARIA,
    "medida.provisoria": RANK_LEI_ORDINARIA,
    # Rank 4 — Decreto (regulamentar)
    "decreto": RANK_DECRETO,
    # Rank 2 — Súmula Vinculante STF tem efeito vinculante GERAL (CF art. 103-A,
    # incluído pela EC 45/2004). Atos normativos posteriores não podem
    # contrariá-la; juízes devem aplicá-la. Trata-se como rank 2 (alongside
    # Lei Complementar) por essa generalidade vinculante. (Phase 6 — Tier-4)
    "sumula.vinculante": RANK_LEI_COMPLEMENTAR,
    # Rank 3 — Tema com tese de repercussão geral STF: vinculante difusa
    # (precedente vincula instâncias inferiores, mas só após tese fixada).
    # Pendente (sem tese) cai no infralegal por convenção; distinção vem
    # via nav.status, não via URN type. (Phase 6 — Tier-4)
    "tema": RANK_LEI_ORDINARIA,
    # Rank 5 — Infralegal (resoluções, portarias, instruções normativas,
    # súmulas simples STJ/STF)
    "resolucao": RANK_INFRALEGAL,
    "resolucao.cd": RANK_INFRALEGAL,  # ANPD Conselho Diretor (Phase 4.3.a/b)
    "portaria": RANK_INFRALEGAL,
    "instrucao.normativa": RANK_INFRALEGAL,
    # Súmula simples (não-vinculante) é orientativa — vincula só os tribunais
    # internos do órgão emissor; não tem efeito erga omnes. (Phase 6 — Tier-4)
    "sumula": RANK_INFRALEGAL,
}

# When a URN type is not in the map, default to lowest authority. The
# RAG should NEVER silently treat an unknown act as Constitutional level.
DEFAULT_RANK = RANK_INFRALEGAL


# Human-readable rank names for warnings/UI.
RANK_NAMES: dict[int, str] = {
    RANK_CONSTITUCIONAL: "Constituição/EC",
    RANK_LEI_COMPLEMENTAR: "Lei Complementar / Súmula Vinculante",
    RANK_LEI_ORDINARIA: "Lei Ordinária / Tema STF (tese fixada)",
    RANK_DECRETO: "Decreto",
    RANK_INFRALEGAL: "Resolução/Portaria/Súmula simples/Infralegal",
}


def legal_rank_for_urn(document_urn: str) -> int:
    """Extract the type segment from a document URN and look up its rank.

    URN shape: `urn:lex:<jurisdição>:<autoridade>:<tipo>:<data>;<id>`.
    Splitting on ':' the type is the segment at index 4.

    Examples:
        urn:lex:br:federal:lei:2018-08-14;13709        → 3 (LO)
        urn:lex:br:federal:constituicao:1988-10-05;1988 → 1 (CF)
        urn:lex:br:federal:decreto.lei:1940-12-07;2848 → 3 (decreto-lei)
        urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15 → 5
    """
    # Strip any partition tail (after `~`) — we only need the document URN.
    doc_urn = document_urn.split("~", 1)[0]
    parts = doc_urn.split(":")
    if len(parts) < 5:
        # Malformed URN — return lowest rank (safe default).
        return DEFAULT_RANK
    type_segment = parts[4]
    return LEGAL_RANK_BY_TYPE.get(type_segment, DEFAULT_RANK)


def effective_legal_rank(document_urn: str, nav: dict[str, str] | None = None) -> int:
    """Resolved rank that takes runtime status into account.

    URN type drives the *potential* rank (e.g. `tema` → 3). But for STF
    temas, the vinculante difusa effect only kicks in once the tese is
    fixed. A pendente tema (julgamento em andamento, ou tese pendente
    de transcrição verbatim) does not have erga omnes/vinculante effect
    and should be treated as infralegal/orientativa.

    The convention (Phase 6 — see study/lexml-urn-spec-resumo.md §9.5):
    when `nav["status"]` contains the substring "pendente", rank-down to
    RANK_INFRALEGAL. Otherwise return the URN-derived rank.

    Examples:
        tema:786 + nav.status="tese-fixada"                              → 3
        tema:987 + nav.status="tese-fixada-pendente-transcricao-verbatim" → 5
        tema:815 + nav.status="pendente_julgamento"                       → 5
        sumula.vinculante:11 + nav={}                                    → 2
        lei:13709 + nav={}                                               → 3 (status irrelevant for legislação)
    """
    base = legal_rank_for_urn(document_urn)
    if nav and "pendente" in (nav.get("status") or "").lower():
        return RANK_INFRALEGAL
    return base


def rank_name(rank: int) -> str:
    """Human-readable name for a rank number."""
    return RANK_NAMES.get(rank, f"rank-{rank}")
