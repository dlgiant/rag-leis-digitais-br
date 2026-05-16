"""Tests for rag_leis.legal_rank — URN type → rank mapping.

Pure-logic, no network. The mapping is constitutional law (literally —
Brazilian normative hierarchy is fixed by the CF/88), so the table is
the contract. These tests pin it.
"""

from __future__ import annotations

import pytest

from rag_leis.legal_rank import (
    DEFAULT_RANK,
    LEGAL_RANK_BY_TYPE,
    RANK_CONSTITUCIONAL,
    RANK_DECRETO,
    RANK_INFRALEGAL,
    RANK_LEI_COMPLEMENTAR,
    RANK_LEI_ORDINARIA,
    effective_legal_rank,
    legal_rank_for_urn,
    rank_name,
)


@pytest.mark.parametrize(
    "urn,expected",
    [
        # Rank 1 — CF/EC
        ("urn:lex:br:federal:constituicao:1988-10-05;1988", RANK_CONSTITUCIONAL),
        ("urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc4", RANK_CONSTITUCIONAL),
        ("urn:lex:br:federal:emenda.constitucional:2022-02-10;115", RANK_CONSTITUCIONAL),
        # Rank 2 — Lei Complementar + Súmula Vinculante STF (CF art. 103-A)
        ("urn:lex:br:federal:lei.complementar:1998-02-26;95", RANK_LEI_COMPLEMENTAR),
        (
            "urn:lex:br:supremo.tribunal.federal:sumula.vinculante:2008-08-13;11",
            RANK_LEI_COMPLEMENTAR,
        ),
        # Rank 3 — Lei Ordinária + Decreto-Lei + MP + STF Tema (tese fixada)
        ("urn:lex:br:federal:lei:2018-08-14;13709", RANK_LEI_ORDINARIA),  # LGPD
        ("urn:lex:br:federal:lei:2014-04-23;12965", RANK_LEI_ORDINARIA),  # MCI
        ("urn:lex:br:federal:decreto.lei:1940-12-07;2848", RANK_LEI_ORDINARIA),  # CP
        ("urn:lex:br:federal:medida.provisoria:2001-08-24;2200-2", RANK_LEI_ORDINARIA),
        ("urn:lex:br:supremo.tribunal.federal:tema:786", RANK_LEI_ORDINARIA),
        ("urn:lex:br:supremo.tribunal.federal:tema:987", RANK_LEI_ORDINARIA),
        # Rank 4 — Decreto
        ("urn:lex:br:federal:decreto:2016-05-11;8771", RANK_DECRETO),  # regulamenta MCI
        # Rank 5 — ANPD Resolução (Phase 4.3 corpus) + Súmula simples STJ
        (
            "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15",
            RANK_INFRALEGAL,
        ),
        (
            "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2023-02-24;4",
            RANK_INFRALEGAL,
        ),
        ("urn:lex:br:superior.tribunal.justica:sumula:1999-09-08;227", RANK_INFRALEGAL),
        ("urn:lex:br:superior.tribunal.justica:sumula:2012-06-27;479", RANK_INFRALEGAL),
    ],
)
def test_legal_rank_for_known_types(urn, expected):
    assert legal_rank_for_urn(urn) == expected


def test_legal_rank_for_unknown_type_defaults_to_infralegal():
    """Defensive: if a URN appears with a type not in our map, we MUST
    NOT silently treat it as a higher-authority source. Default to lowest."""
    urn = "urn:lex:br:federal:tipo.que.nao.existe:2024-01-01;1"
    assert legal_rank_for_urn(urn) == DEFAULT_RANK
    assert DEFAULT_RANK == RANK_INFRALEGAL  # explicitness for the reader


def test_legal_rank_for_malformed_urn_defaults_to_infralegal():
    """Malformed URN (too few segments) — same defensive default."""
    assert legal_rank_for_urn("not-a-urn") == DEFAULT_RANK
    assert legal_rank_for_urn("urn:lex:br") == DEFAULT_RANK
    assert legal_rank_for_urn("") == DEFAULT_RANK


def test_legal_rank_strips_partition():
    """The function should ignore partition tail (`~art7`) when looking
    up — rank is per-document, not per-chunk."""
    base_urn = "urn:lex:br:federal:constituicao:1988-10-05;1988"
    for partition in ["", "~art5", "~art5;inc4", "~art5;inc72;ali-a"]:
        assert legal_rank_for_urn(base_urn + partition) == RANK_CONSTITUCIONAL


def test_rank_name_returns_human_readable():
    assert "Constituição" in rank_name(RANK_CONSTITUCIONAL)
    assert "Lei Ordinária" in rank_name(RANK_LEI_ORDINARIA)
    assert rank_name(99) == "rank-99"  # unknown — synthesized


# Phase 6.5 — effective_legal_rank: status-aware downgrade for pendente
# jurisprudência. URN type alone says "tema → 3", but a tema without
# tese fixada doesn't have vinculante difusa effect → rank-down to 5.

@pytest.mark.parametrize(
    "urn,nav,expected",
    [
        # tese fixada — URN rank stands
        (
            "urn:lex:br:supremo.tribunal.federal:tema:786",
            {"status": "tese-fixada"},
            RANK_LEI_ORDINARIA,
        ),
        # pendente julgamento — rank-down
        (
            "urn:lex:br:supremo.tribunal.federal:tema:815",
            {"status": "pendente_julgamento"},
            RANK_INFRALEGAL,
        ),
        # tese fixada mas transcrição verbatim pendente (curador stub) — rank-down
        # (a tese existe juridicamente, mas o RAG não pode citar verbatim com
        # confiança, então se comporta como infralegal para evitar overreach)
        (
            "urn:lex:br:supremo.tribunal.federal:tema:987",
            {"status": "tese-fixada-pendente-transcricao-verbatim"},
            RANK_INFRALEGAL,
        ),
        # nav ausente / sem status → comporta como legal_rank_for_urn puro
        ("urn:lex:br:supremo.tribunal.federal:tema:786", {}, RANK_LEI_ORDINARIA),
        ("urn:lex:br:supremo.tribunal.federal:tema:786", None, RANK_LEI_ORDINARIA),
        # status que NÃO contém "pendente" — sem rank-down
        (
            "urn:lex:br:supremo.tribunal.federal:tema:786",
            {"status": "tese-fixada"},
            RANK_LEI_ORDINARIA,
        ),
        # Caso estranho: lei com nav.status pendente — status só faz sentido
        # para jurisprudência, mas a regra é uniforme. Aceitamos rank-down.
        # (Hoje nenhum chunk de lei tem nav.status, mas defensivo.)
        (
            "urn:lex:br:federal:lei:2018-08-14;13709",
            {"status": "algo_pendente_aqui"},
            RANK_INFRALEGAL,
        ),
        # Súmula vinculante sempre rank 2, status irrelevante quando ausente
        (
            "urn:lex:br:supremo.tribunal.federal:sumula.vinculante:2008-08-13;11",
            {},
            RANK_LEI_COMPLEMENTAR,
        ),
        # Súmula simples já é rank 5 — nada muda mesmo com pendente
        (
            "urn:lex:br:superior.tribunal.justica:sumula:1999-09-08;227",
            {"status": "vigente"},
            RANK_INFRALEGAL,
        ),
    ],
)
def test_effective_legal_rank_with_status(urn, nav, expected):
    assert effective_legal_rank(urn, nav) == expected


def test_effective_rank_pendente_substring_is_case_insensitive():
    """Defensive: 'PENDENTE_JULGAMENTO' (uppercase) should also rank-down."""
    urn = "urn:lex:br:supremo.tribunal.federal:tema:815"
    assert effective_legal_rank(urn, {"status": "PENDENTE_JULGAMENTO"}) == RANK_INFRALEGAL
    assert effective_legal_rank(urn, {"status": "Pendente"}) == RANK_INFRALEGAL


def test_all_rank_constants_in_table():
    """Sanity: every rank value present in LEGAL_RANK_BY_TYPE should be
    one of the five named constants. Catches accidental free-floating numbers."""
    valid_ranks = {
        RANK_CONSTITUCIONAL,
        RANK_LEI_COMPLEMENTAR,
        RANK_LEI_ORDINARIA,
        RANK_DECRETO,
        RANK_INFRALEGAL,
    }
    for type_, rank in LEGAL_RANK_BY_TYPE.items():
        assert rank in valid_ranks, (
            f"Type {type_!r} maps to rank {rank} which is not a named constant. "
            f"Either fix the value or add a new RANK_* constant."
        )
