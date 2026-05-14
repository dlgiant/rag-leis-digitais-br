"""Golden tests for PlanaltoHtmlParser.

Regression safety: the parser is regex-heavy and silently degrades when
Planalto edits a `<p>` to a `<div>` or shifts class attributes. These tests
pin parsing behavior on 4 representative articles chosen to span the
hierarchy levels and the Tier-1 laws most commonly cited:

  - CF art. 5 IV         — short constitutional inciso
  - LGPD art. 7 I        — definition inciso inside a list-stem caput
  - CP art. 154-A        — caput of a long-form criminal type with §§
  - CDC art. 43          — caput that's itself the operative rule

If any of these stops matching, the parser regressed and the rest of the
project (eval, retrieval, write-ups) needs revalidation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_leis.parser import PlanaltoHtmlParser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "tier-1"


def _parse(filename: str, doc_urn: str):
    """Load a Planalto-fetched HTML and parse it via the PlanaltoHtmlParser."""
    html = (RAW_DIR / filename).read_text(encoding="utf-8")
    parser = PlanaltoHtmlParser()
    chunks = parser.parse(doc_urn, html)
    return {c.urn: c for c in chunks}


def _find_chunk(chunks_by_urn, target_tail):
    """Return the chunk whose URN ends with target_tail, asserting uniqueness."""
    matches = [u for u in chunks_by_urn if u.endswith(target_tail)]
    assert len(matches) == 1, (
        f"expected exactly one chunk with URN ending in {target_tail!r}, "
        f"got {len(matches)}: {matches[:5]}"
    )
    return chunks_by_urn[matches[0]]


# ----------------------------------------------------------------------------
# Constituição Federal — art. 5, IV (vedado o anonimato)
# ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cf_chunks():
    return _parse(
        "br_federal_constituicao_1988-10-05_1988.html",
        "urn:lex:br:federal:constituicao:1988-10-05;1988",
    )


def test_cf_art5_inc4_text(cf_chunks):
    c = _find_chunk(cf_chunks, "~art5;inc4")
    assert c.kind == "inciso"
    assert c.label == "IV"
    assert c.text.startswith("é livre a manifestação do pensamento")
    assert "vedado o anonimato" in c.text
    assert not c.is_revoked


def test_cf_art5_inc72_has_alineas(cf_chunks):
    """art.5;inc72 is habeas data, with sub-alíneas a and b."""
    parent = _find_chunk(cf_chunks, "~art5;inc72")
    assert parent.kind == "inciso"
    # The alíneas must exist as separate chunks parented on inc72.
    assert any(u.endswith("~art5;inc72;ali-a") for u in cf_chunks)
    assert any(u.endswith("~art5;inc72;ali-b") for u in cf_chunks)


# ----------------------------------------------------------------------------
# LGPD — art. 7, I (consentimento) inside the "hipóteses" enumeration
# ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lgpd_chunks():
    return _parse(
        "br_federal_lei_2018-08-14_13709.html",
        "urn:lex:br:federal:lei:2018-08-14;13709",
    )


def test_lgpd_art7_inc1_is_consent(lgpd_chunks):
    c = _find_chunk(lgpd_chunks, "~art7;inc1")
    assert c.kind == "inciso"
    assert c.label == "I"
    assert "consentimento" in c.text.lower()
    assert c.parent_partition == "art7"


def test_lgpd_art7_caput_is_stem(lgpd_chunks):
    """art.7 caput is a list stem ('nas seguintes hipóteses:'). Should parse as artigo."""
    c = _find_chunk(lgpd_chunks, "~art7")
    assert c.kind == "artigo"
    assert "tratamento de dados pessoais" in c.text.lower()
    assert c.text.rstrip().endswith(":")  # list-stem signature


# ----------------------------------------------------------------------------
# Código Penal — art. 154-A (invasão de dispositivo informático)
# ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cp_chunks():
    return _parse(
        "br_federal_decreto.lei_1940-12-07_2848.html",
        "urn:lex:br:federal:decreto.lei:1940-12-07;2848",
    )


def test_cp_art154a_caput(cp_chunks):
    c = _find_chunk(cp_chunks, "~art154-a")
    assert c.kind == "artigo"
    assert c.text.startswith("Invadir dispositivo informático")
    assert not c.is_revoked


def test_cp_art154a_has_paragraphs(cp_chunks):
    """The art.154-A typification expands into multiple §§ (penas, qualificadoras)."""
    paragraphs = [u for u in cp_chunks if u.startswith(
        "urn:lex:br:federal:decreto.lei:1940-12-07;2848~art154-a;par"
    )]
    assert len(paragraphs) >= 3, f"expected ≥3 §§ on art.154-A, found {len(paragraphs)}"


# ----------------------------------------------------------------------------
# CDC — art. 43 (acesso a cadastros do consumidor)
# ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cdc_chunks():
    return _parse(
        "br_federal_lei_1990-09-11_8078.html",
        "urn:lex:br:federal:lei:1990-09-11;8078",
    )


def test_cdc_art43_caput(cdc_chunks):
    c = _find_chunk(cdc_chunks, "~art43")
    assert c.kind == "artigo"
    assert c.text.startswith("O consumidor")
    assert "acesso às informações" in c.text


def test_cdc_art43_par4_pertencente(cdc_chunks):
    """§ 4 declares bancos de dados as 'entidades de caráter público' — a key
    operationalization for consumer rights queries."""
    c = _find_chunk(cdc_chunks, "~art43;par4")
    assert c.kind == "paragrafo"
    assert "entidades de caráter público" in c.text


# ----------------------------------------------------------------------------
# Cross-cutting smoke tests — corpus-level invariants
# ----------------------------------------------------------------------------


def test_no_chunk_has_empty_partition(lgpd_chunks):
    for urn, c in lgpd_chunks.items():
        assert c.partition, f"empty partition on {urn!r}"


def test_revoked_flag_set_on_placeholders(cdc_chunks):
    """CDC has many (Vetado) placeholders; verify the flag was populated."""
    vetados = [c for c in cdc_chunks.values() if c.text.strip().startswith("(Vetado)")]
    assert len(vetados) >= 5, f"expected several (Vetado) in CDC, got {len(vetados)}"
    assert all(c.is_revoked for c in vetados), (
        "is_revoked must be True for all (Vetado) chunks"
    )
