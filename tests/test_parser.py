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

# All tests in this file load raw HTML from data/raw/tier-1/ which is
# gitignored. CI doesn't have these files; mark module-level so the
# CI gate's `-m "not requires_local_data"` skips the whole file.
pytestmark = pytest.mark.requires_local_data

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


# ----------------------------------------------------------------------------
# Regression goldens for the 4 BLOCKER bugs surfaced by the chunk-auditor
# (2026-05-14): ADCT art1 leading dot, ADCT art120 missing, CF art231 fine
# but pinned, CP art187 missing (br-tag split fix).
# ----------------------------------------------------------------------------


def test_cf_adct_art1_text_clean(cf_chunks):
    """ADCT art. 1 must start with 'O Presidente' — no stray leading period
    from the 'Art. 1º.' ordinal+period pattern."""
    c = _find_chunk(cf_chunks, "~adct;art1")
    assert c.text.startswith("O Presidente da República"), (
        f"ADCT art1 should start clean; got {c.text[:40]!r}"
    )


def test_cf_adct_art120_present(cf_chunks):
    """ADCT art. 120 was being swallowed because the preceding `<p>` for
    art119's parágrafo único was malformed (closed with </div>)."""
    c = _find_chunk(cf_chunks, "~adct;art120")
    assert c.kind == "artigo"
    assert "estado de emergência" in c.text
    assert "2022" in c.text


def test_cp_arts_187_to_191_present_and_revoked(cp_chunks):
    """CP arts 187-191 are revogados (Lei 9.279/1996) and used to be missing
    because Planalto packs them with Nomen iuris titles into a single <p> +
    separates with <br>. Now extracted via <br>-split, marked revogados."""
    for n in (187, 188, 189, 190, 191):
        c = _find_chunk(cp_chunks, f"~art{n}")
        assert c.kind == "artigo"
        assert c.is_revoked, f"art{n} should be is_revoked (revogado pela Lei 9.279)"


# ----------------------------------------------------------------------------
# Phase 6.6 r3 — sub-paragraph suffix capture (Lei 14.155/21).
# Until 2026-05-16 _PARAGRAFO_HEAD captured only `(\d+)`, collapsing §2,
# §2-A and §2-B into the same partition `par2`. _dedup_keep_last then
# discarded all but the last seen — silently losing CP art.171 §2-A
# (Estelionato Eletrônico) and art.155 §4-B (Furto Eletrônico). Fix
# extends the regex with an optional `-[A-Z]` suffix anchored by a
# punctuation lookahead (so `§ Nº - Texto` separators don't false-match).
# These tests pin the corrected behavior so the bug can't silently regress.
# ----------------------------------------------------------------------------


def test_cp_art171_par2a_estelionato_eletronico(cp_chunks):
    """CP art. 171 §2-A — Estelionato Eletrônico (Lei 14.155/21) must be
    indexed as its own partition, not collapsed into par2."""
    c = _find_chunk(cp_chunks, "~art171;par2-a")
    assert c.kind == "paragrafo"
    assert c.label == "§ 2º-A"
    assert "fraude" in c.text.lower()


def test_cp_art171_par2_caput_intact(cp_chunks):
    """CP art. 171 §2 caput ("Nas mesmas penas incorre quem:") must NOT be
    overwritten by §2-B text. The dedup bug used to swap them."""
    c = _find_chunk(cp_chunks, "~art171;par2")
    assert c.kind == "paragrafo"
    assert "Nas mesmas penas" in c.text
    # Sanity: the §2-B text DOES NOT live here.
    assert "§ 2º-A" not in c.text


def test_cp_art155_par4b_furto_eletronico(cp_chunks):
    """CP art. 155 §4-B — Furto Eletrônico (Lei 14.155/21) must exist and
    not be clobbered by §4-C (the next sub-§)."""
    c = _find_chunk(cp_chunks, "~art155;par4-b")
    assert c.kind == "paragrafo"
    assert c.label == "§ 4º-B"
    assert "reclusão" in c.text.lower()


def test_cp_art171_par2_separator_hyphen_consumed(cp_chunks):
    """The Planalto separator `§ 2º - Nas mesmas penas...` should leave
    text starting with 'Nas', not '- Nas' — the regex eats the separator
    hyphen when no real suffix follows. This is also the boundary case
    that the lookahead must NOT confuse with `§ 2º-A` form."""
    c = _find_chunk(cp_chunks, "~art171;par2")
    assert c.text.startswith("Nas mesmas penas"), (
        f"separator hyphen leaked into text: {c.text[:40]!r}"
    )


# ----------------------------------------------------------------------------
# Phase 6.6 r5 — inciso suffix capture (EC 45/2004 etc).
# Until 2026-05-16 _INCISO_HEAD captured only `([IVXLCDM]+)`, collapsing
# I + I-A into the same partition `inc1` (and dedup_keep_last destroyed
# the original I). Surfaced by coverage-auditor agent. Fix mirrors the
# §-suffix pattern (commit 0effdc8): optional suffix with strict adjacency.
# These tests pin the recovered chunks on CF art.92 (EC 45/2004 added I-A
# for CNJ, EC 92/2016 added II-A for TST) and CF art.93 (VIII-A, VIII-B).
# ----------------------------------------------------------------------------


def test_cf_art92_inc1_stf_intact(cf_chunks):
    """CF art.92 inc I — STF — must NOT be overwritten by inc I-A's CNJ
    text. This was the symptom of the collapse bug."""
    c = _find_chunk(cf_chunks, "~art92;inc1")
    assert c.label == "I"
    assert "Supremo Tribunal Federal" in c.text


def test_cf_art92_inc1a_cnj_present(cf_chunks):
    """CF art.92 inc I-A — CNJ (incluído pela EC 45/2004) must exist as
    its own partition, not collapsed into inc1."""
    c = _find_chunk(cf_chunks, "~art92;inc1-a")
    assert c.label == "I-A"
    assert "Conselho Nacional de Justiça" in c.text


def test_cf_art92_inc2a_tst_present(cf_chunks):
    """CF art.92 inc II-A — TST (incluído pela EC 92/2016) — same
    pattern as inc1-a."""
    c = _find_chunk(cf_chunks, "~art92;inc2-a")
    assert c.label == "II-A"
    assert "Tribunal Superior do Trabalho" in c.text


def test_cf_art93_inc8_remocao_intact(cf_chunks):
    """CF art.93 inc VIII — disponibilidade do magistrado — original
    inciso must be present (was clobbered by VIII-A before fix)."""
    c = _find_chunk(cf_chunks, "~art93;inc8")
    assert c.label == "VIII"
    assert "remoção" in c.text.lower() or "disponibilidade" in c.text.lower()


def test_cf_art93_inc8a_inc8b_present(cf_chunks):
    """CF art.93 incs VIII-A (remoção a pedido) and VIII-B (permuta)
    — both added by EC 45/2004, both lost before the suffix fix."""
    a = _find_chunk(cf_chunks, "~art93;inc8-a")
    assert a.label == "VIII-A"
    b = _find_chunk(cf_chunks, "~art93;inc8-b")
    assert b.label == "VIII-B"
