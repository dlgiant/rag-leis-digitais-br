"""Tests for Phase 5.7 — Emenda Constitucional linkage on IndexChunk.

The parser already strips "(Incluído pela EC nº X, de YYYY)" /
"(Redação dada pela EC nº X, de YYYY)" into chunk.notes at parse time.
load_chunks then extracts these into a structured `amended_by` tuple
(e.g., ("EC-115/2022",)) — easier for downstream UI / observability
than free-text notes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_leis.eval_harness import _extract_amended_by, load_chunks

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------
# Pure-logic: _extract_amended_by from notes
# ----------------------------------------------------------------------------


def test_extract_incluido_pela():
    notes = ["(Incluído pela Emenda Constitucional nº 115, de 2022)"]
    assert _extract_amended_by(notes) == ["EC-115/2022"]


def test_extract_redacao_dada():
    notes = ["(Redação dada pela Emenda Constitucional nº 90, de 2015)"]
    assert _extract_amended_by(notes) == ["EC-90/2015"]


def test_extract_handles_inclusa_inflection():
    """Some notes use 'Incluída' (feminine — for 'cláusula', 'norma' etc)."""
    notes = ["(Incluída pela Emenda Constitucional nº 45, de 2004)"]
    assert _extract_amended_by(notes) == ["EC-45/2004"]


def test_extract_multiple_ecs_sorted_year_desc():
    """When a chunk has multiple EC mentions (rare), sort most-recent first."""
    notes = [
        "(Redação dada pela Emenda Constitucional nº 45, de 2004)",
        "(Incluído pela Emenda Constitucional nº 115, de 2022)",
    ]
    assert _extract_amended_by(notes) == ["EC-115/2022", "EC-45/2004"]


def test_extract_dedup():
    """Same EC mentioned twice (parser quirk possible) → single entry."""
    notes = [
        "(Incluído pela Emenda Constitucional nº 45, de 2004)",
        "(Incluído pela Emenda Constitucional nº 45, de 2004)",
    ]
    assert _extract_amended_by(notes) == ["EC-45/2004"]


def test_extract_empty_when_no_ec_mentions():
    """Notes about jurisprudência ('(Vide ADIN 3392)') don't trigger."""
    notes = ["(Vide ADIN 3392)", "(Vide Súmula 473 STF)"]
    assert _extract_amended_by(notes) == []


def test_extract_empty_when_notes_empty():
    assert _extract_amended_by([]) == []


def test_extract_ignores_non_ec_emendas():
    """'Emenda de Plenário' etc. should NOT match — only 'Emenda Constitucional'."""
    notes = ["(Emenda de Plenário nº 5)"]
    assert _extract_amended_by(notes) == []


# ----------------------------------------------------------------------------
# Real corpus integration
# ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def chunks():
    return load_chunks(PROJECT_ROOT / "data" / "chunks")


def test_cf_art5_inc79_amended_by_ec_115(chunks):
    """The canonical case — EC 115/2022 inserted o direito fundamental
    à proteção de dados pessoais. Used by reviewer round 2 as the test
    of constitutional EC tracking."""
    by_urn = {c.urn: c for c in chunks}
    inc79 = by_urn.get(
        "urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc79"
    )
    assert inc79 is not None
    assert "EC-115/2022" in inc79.amended_by
    # Sanity: the text describes proteção de dados
    assert "proteção" in inc79.text.lower() and "dados" in inc79.text.lower()


def test_non_cf_chunks_have_empty_amended_by(chunks):
    """Non-CF documents (LGPD, MCI, CP) shouldn't have EC linkage —
    they're not constitutional."""
    by_urn = {c.urn: c for c in chunks}
    lgpd_art7 = by_urn.get("urn:lex:br:federal:lei:2018-08-14;13709~art7")
    assert lgpd_art7 is not None
    assert lgpd_art7.amended_by == ()


def test_at_least_some_cf_chunks_amended_by_ec_45(chunks):
    """EC 45/2004 was a major reforma do Judiciário; many CF chunks
    bear its mark. Tests that the extraction works at scale."""
    ec45_chunks = [
        c for c in chunks
        if "EC-45/2004" in c.amended_by
    ]
    assert len(ec45_chunks) >= 5, (
        f"expected ≥5 chunks amended by EC 45/2004, got {len(ec45_chunks)}"
    )


def test_amended_by_chunks_count_at_scale(chunks):
    """Sanity: when load_chunks runs over the full CF, a substantial
    fraction of chunks (≥1000) should have EC linkage. The CF compilada
    has been amended by ~115 ECs over its history."""
    cf_chunks_with_ec = [
        c for c in chunks
        if c.amended_by and "constituicao" in c.urn
    ]
    assert len(cf_chunks_with_ec) >= 1000, (
        f"expected ≥1000 CF chunks with amended_by, got {len(cf_chunks_with_ec)}"
    )
