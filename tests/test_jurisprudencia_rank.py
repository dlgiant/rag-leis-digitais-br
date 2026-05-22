"""Phase 6.5 — effective rank for Tier-4 jurisprudência at load_chunks time.

The legal_rank table maps URN type → potential rank. But for STF temas
the vinculante difusa effect only kicks in once the tese is fixada; a
pendente tema (julgamento em andamento, ou tese pendente de transcrição
verbatim) doesn't have erga omnes effect and must rank-down.

This test reads the ACTUAL Tier-4 chunks on disk and asserts that the
IndexChunk.legal_rank produced by load_chunks reflects the effective
(status-aware) rank, not the URN-only rank.

Cross-validates with the per-chunk nav.status values written in
data/chunks/tier-4/jurisprudencia.jsonl.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_leis.eval_harness import load_chunks
from rag_leis.legal_rank import RANK_INFRALEGAL, RANK_LEI_ORDINARIA

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _by_urn():
    chunks = load_chunks(PROJECT_ROOT / "data" / "chunks")
    return {c.urn: c for c in chunks}


def test_tema_with_tese_fixada_keeps_rank_3():
    """Tema 786 (direito ao esquecimento) tem tese fixada em 2021 —
    deve carregar rank 3 (Lei Ordinária / Tema STF tese fixada)."""
    by_urn = _by_urn()
    chunk = by_urn.get("urn:lex:br:supremo.tribunal.federal:tema:786~tese")
    assert chunk is not None, "Tema 786 chunk não indexado — corpus regression?"
    assert chunk.legal_rank == RANK_LEI_ORDINARIA, (
        f"Tema 786 com status=tese-fixada deve ser rank 3, foi {chunk.legal_rank}"
    )


def test_tema_pendente_julgamento_excluded_from_retrieval():
    """Phase 16.3 supersedes the old Phase 6.5 rank-down policy for
    pending-judgment Temas. The chunks document their own confabulation
    risk in `notes` ("PENDENTE_JULGAMENTO" / "PENDENTE_REVISAO_JURIDICA")
    so load_chunks excludes them outright until verbatim transcription
    lands (Phase 19.1 / D7). Asserting absence is the stronger contract
    than rank-down."""
    by_urn = _by_urn()
    chunk = by_urn.get("urn:lex:br:supremo.tribunal.federal:tema:815~ementa")
    assert chunk is None, (
        "Tema 815 (PENDENTE_JULGAMENTO) deve ser excluído do índice em Phase 16.3 — "
        "voltará na transcrição verbatim (Phase 19.1)."
    )


def test_tema_tese_fixada_pendente_transcricao_excluded_from_retrieval():
    """Temas 987 e 533: tese juridicamente existe (fixada), mas o RAG não
    tem o texto verbatim transcrito — chunks são stubs e disparam
    confabulação ("LLM pode citar este chunk como se fosse a tese").

    Phase 16.3 política: stubs marcados com notes "PENDENTE_*" são
    excluídos no load_chunks. Política Phase 6.5 (rank-down para 5)
    permanece como defense-in-depth em legal_rank.py caso um futuro
    stub não siga a convenção de notes, mas o caminho primário é a
    exclusão. Voltará na transcrição verbatim (Phase 19.1 / D7)."""
    by_urn = _by_urn()
    for urn in [
        "urn:lex:br:supremo.tribunal.federal:tema:987~ementa",
        "urn:lex:br:supremo.tribunal.federal:tema:533~ementa",
    ]:
        chunk = by_urn.get(urn)
        assert chunk is None, (
            f"{urn} (stub PENDENTE_REVISAO_JURIDICA) deve ser excluído em Phase 16.3"
        )


def test_sumulas_stj_keep_rank_5():
    """STJ súmulas simples já são rank 5 base — status='vigente' é
    no-op (não contém 'pendente'). Confirma que a regra não regride
    chunks já infralegais."""
    by_urn = _by_urn()
    for urn in [
        "urn:lex:br:superior.tribunal.justica:sumula:1999-09-08;227~enunciado",
        "urn:lex:br:superior.tribunal.justica:sumula:2009-10-28;403~enunciado",
        "urn:lex:br:superior.tribunal.justica:sumula:2012-06-27;479~enunciado",
    ]:
        chunk = by_urn.get(urn)
        assert chunk is not None, f"{urn} não indexado"
        assert chunk.legal_rank == RANK_INFRALEGAL


@pytest.mark.requires_local_data
def test_legislacao_unaffected_by_status_logic():
    """Sanity: leis (LGPD, MCI) não têm nav.status — devem manter o rank
    URN-derivado, não cair em algum default mais baixo."""
    by_urn = _by_urn()
    lgpd_art7 = by_urn.get("urn:lex:br:federal:lei:2018-08-14;13709~art7")
    assert lgpd_art7 is not None
    assert lgpd_art7.legal_rank == RANK_LEI_ORDINARIA  # 3, não 5

    mci_art19 = by_urn.get("urn:lex:br:federal:lei:2014-04-23;12965~art19")
    assert mci_art19 is not None
    assert mci_art19.legal_rank == RANK_LEI_ORDINARIA
