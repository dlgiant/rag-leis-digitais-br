"""Unit tests for rag_leis.prose_check — prose citation extraction and
mismatch detection.

Pure-logic. The contract is:
  - extract_prose_citations() returns ALL recognizable Art. N citations
    in prose order
  - check_prose_vs_citations() emits ProseMismatch for each prose
    citation that doesn't match any cited URN's partition suffix
  - The matching is exact suffix (anchored on `~`) to avoid art.5
    matching art.50
"""

from __future__ import annotations

import pytest

from rag_leis.prose_check import (
    ProseMismatch,
    build_reprompt_message,
    check_prose_vs_citations,
    extract_prose_citations,
    roman_to_int,
)

# ----------------------------------------------------------------------------
# Roman numeral helper
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "roman,expected",
    [("I", 1), ("IV", 4), ("V", 5), ("IX", 9), ("X", 10),
     ("XII", 12), ("XX", 20), ("LXXII", 72), ("LXXIX", 79)],
)
def test_roman_to_int(roman, expected):
    assert roman_to_int(roman) == expected


def test_roman_to_int_invalid():
    assert roman_to_int("ZZZ") is None
    assert roman_to_int("") is None


# ----------------------------------------------------------------------------
# extract_prose_citations
# ----------------------------------------------------------------------------


def test_extract_simple_artigo():
    cites = extract_prose_citations("Conforme o Art. 5 da Constituição.")
    assert len(cites) == 1
    assert cites[0].article_num == "5"
    assert cites[0].paragraph_num is None
    assert cites[0].inciso_roman is None
    assert cites[0].partition_path == "art5"


def test_extract_artigo_with_ordinal():
    cites = extract_prose_citations("O Art. 5º da CF é claro.")
    assert len(cites) == 1
    assert cites[0].article_num == "5"
    assert cites[0].partition_path == "art5"


def test_extract_artigo_with_inciso_roman():
    cites = extract_prose_citations("O Art. 5, XII da Constituição")
    assert len(cites) == 1
    assert cites[0].article_num == "5"
    assert cites[0].inciso_roman == "XII"
    assert cites[0].inciso_num == 12
    assert cites[0].partition_path == "art5;inc12"


def test_extract_artigo_with_paragrafo():
    cites = extract_prose_citations("Por força do Art. 7, § 6º da LGPD")
    assert len(cites) == 1
    assert cites[0].article_num == "7"
    assert cites[0].paragraph_num == "6"
    assert cites[0].partition_path == "art7;par6"


def test_extract_artigo_with_paragrafo_and_inciso():
    cites = extract_prose_citations("Vide o Art. 7, § 6, I da LGPD")
    assert len(cites) == 1
    assert cites[0].partition_path == "art7;par6;inc1"


def test_extract_artigo_with_dash_suffix():
    """Art. 154-A is a real CP article. The regex must capture the suffix."""
    cites = extract_prose_citations("O Art. 154-A do CP define...")
    assert len(cites) == 1
    assert cites[0].article_num == "154-A"
    assert cites[0].partition_path == "art154-a"


def test_extract_multiple_in_one_paragraph():
    text = (
        "A LGPD (Art. 5, I) trata de dados pessoais; o Art. 7, § 6º "
        "regula consentimento; e o Art. 18, II garante acesso."
    )
    cites = extract_prose_citations(text)
    assert len(cites) == 3
    assert cites[0].partition_path == "art5;inc1"
    assert cites[1].partition_path == "art7;par6"
    assert cites[2].partition_path == "art18;inc2"


def test_extract_handles_alternate_spellings():
    """'art.', 'Art.', 'artigo' all work."""
    cites = extract_prose_citations("art. 5, artigo 7, Art. 18")
    assert len(cites) == 3
    assert [c.article_num for c in cites] == ["5", "7", "18"]


def test_extract_no_cites_in_clean_prose():
    """A prose with no article citations returns []."""
    text = "Conforme o entendimento jurisprudencial, o tratamento de dados é tema sensível."
    assert extract_prose_citations(text) == []


# ----------------------------------------------------------------------------
# check_prose_vs_citations
# ----------------------------------------------------------------------------


def test_no_mismatch_when_prose_matches_cited_exactly():
    text = "O Art. 5, XII da CF estabelece o sigilo das comunicações."
    cited = ["urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc12"]
    assert check_prose_vs_citations(text, cited) == []


def test_mismatch_when_prose_says_inc12_but_url_says_inc10():
    """The canonical scenario: model wrote 'XII' but cited inc10."""
    text = "O Art. 5, XII protege a intimidade."
    cited = ["urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc10"]
    mm = check_prose_vs_citations(text, cited)
    assert len(mm) == 1
    assert mm[0].surface == "Art. 5, XII"
    assert mm[0].expected_partition == "art5;inc12"
    assert mm[0].nearest_cited_urn == cited[0]


def test_mismatch_when_prose_has_paragrafo_but_cited_doesnt():
    text = "O Art. 7, § 6 trata disso."
    cited = ["urn:lex:br:federal:lei:2018-08-14;13709~art7"]
    mm = check_prose_vs_citations(text, cited)
    assert len(mm) == 1
    assert mm[0].expected_partition == "art7;par6"


def test_no_mismatch_for_partial_prose_when_deeper_urn_cited():
    """'Art. 7' alone in prose, but URN points to art7;par6 (a child of
    art7). The prose is consistent with citing art7;par6 — citing the
    paragraph is a valid grounding for a reference to the article. NO
    mismatch (Phase 5.3 prefix-match-anchored-on-~ contract)."""
    text = "Conforme o Art. 7 da LGPD"
    cited = ["urn:lex:br:federal:lei:2018-08-14;13709~art7;par6"]
    assert check_prose_vs_citations(text, cited) == []


def test_no_mismatch_for_artigo_when_alinea_cited():
    """Same prefix-match logic at deeper levels: prose 'Art. 5, LXXII'
    matches a cited art5;inc72;ali-a (the alínea is a child of inc72)."""
    text = "O Art. 5, LXXII da Constituição"
    cited = ["urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc72;ali-a"]
    assert check_prose_vs_citations(text, cited) == []


def test_no_false_positive_art5_vs_art50():
    """The suffix match must anchor on `~` so 'Art. 5' doesn't match
    a URN ending in `~art50`."""
    text = "O Art. 5 estabelece..."
    cited = ["urn:lex:br:federal:lei:2014-04-23;12965~art50"]  # art. 50, not 5
    mm = check_prose_vs_citations(text, cited)
    assert len(mm) == 1, "art.5 mismatched against art.50 should be flagged"


def test_multiple_mismatches_collected_in_order():
    text = "Art. 5, XII (correto) e Art. 7, § 99 (não está nas citações)"
    cited = ["urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc12"]
    mm = check_prose_vs_citations(text, cited)
    # Only the second one is a mismatch (first matches inc12)
    assert len(mm) == 1
    assert mm[0].expected_partition == "art7;par99"


def test_nearest_cited_urn_picks_same_article():
    """When prose says Art. 5, XII but cited URNs are mixed, nearest
    should pick a URN with art5 in it (any partition under art5)."""
    text = "Art. 5, XII"
    cited = [
        "urn:lex:br:federal:lei:2018-08-14;13709~art18",  # different article
        "urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc10",  # same article
    ]
    mm = check_prose_vs_citations(text, cited)
    assert len(mm) == 1
    assert "art5" in mm[0].nearest_cited_urn


def test_no_nearest_when_no_same_article_cited():
    text = "Art. 99, X"
    cited = ["urn:lex:br:federal:lei:2014-04-23;12965~art1"]
    mm = check_prose_vs_citations(text, cited)
    assert len(mm) == 1
    assert mm[0].nearest_cited_urn is None


# ----------------------------------------------------------------------------
# build_reprompt_message
# ----------------------------------------------------------------------------


def test_reprompt_empty_when_no_mismatches():
    assert build_reprompt_message([]) == ""


def test_reprompt_includes_surface_and_expected():
    mm = [
        ProseMismatch(
            surface="Art. 5, XII",
            expected_partition="art5;inc12",
            span_start=0, span_end=11,
            nearest_cited_urn="urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc10",
        ),
    ]
    msg = build_reprompt_message(mm)
    assert "Art. 5, XII" in msg
    assert "art5;inc12" in msg
    # The instruction must tell the model what to do
    assert "consistentes" in msg.lower() or "correção" in msg.lower() or "remov" in msg.lower()


def test_reprompt_handles_no_nearest():
    mm = [
        ProseMismatch(
            surface="Art. 99",
            expected_partition="art99",
            span_start=0, span_end=8,
            nearest_cited_urn=None,
        ),
    ]
    msg = build_reprompt_message(mm)
    assert "Art. 99" in msg
    assert "nenhuma URN" in msg


# ----------------------------------------------------------------------------
# Realistic integration scenarios
# ----------------------------------------------------------------------------


def test_realistic_clean_lgpd_answer():
    """A typical clean LGPD answer should produce no mismatches."""
    text = (
        "A LGPD (art. 5º, I) define dado pessoal como toda informação "
        "relacionada a pessoa natural identificada ou identificável. "
        "O Art. 7 lista as bases legais para tratamento."
    )
    cited = [
        "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1",
        "urn:lex:br:federal:lei:2018-08-14;13709~art7",
    ]
    assert check_prose_vs_citations(text, cited) == []


def test_realistic_cross_doc_with_shared_article_numbers():
    """CF art. 5 vs LGPD art. 5 — both exist; the prose 'Art. 5, XII' must
    map to whichever URN was cited. If only LGPD art.5;inc1 is cited but
    prose says 'Art. 5, XII', it's a mismatch (inc1 != inc12)."""
    text = "O Art. 5, XII da Constituição protege as comunicações."
    cited = ["urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1"]  # LGPD only
    mm = check_prose_vs_citations(text, cited)
    assert len(mm) == 1
    assert mm[0].expected_partition == "art5;inc12"
