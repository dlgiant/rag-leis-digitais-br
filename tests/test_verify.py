"""Unit tests for cite-and-verify (rag_leis.verify).

Pure-logic, no network. Exercises the four cases the verifier has to
distinguish in the wild:

  1. Citation that's in corpus AND in context → verified
  2. Citation that's not in corpus at all → rejected (not-in-corpus)
  3. Citation that's in corpus but wasn't shown to the LLM → rejected
     (not-in-context); this is the subtle failure where the model leaks
     training data
  4. Duplicate citations → de-dup in verified, but each invalid copy still
     surfaces in rejected (so we don't silently swallow signal)
"""

from __future__ import annotations

from rag_leis.verify import verify_citations

CORPUS: frozenset[str] = frozenset({
    "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1",
    "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc2",
    "urn:lex:br:federal:lei:2018-08-14;13709~art11",
    "urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc4",
})


def test_all_verified_when_cited_subset_of_retrieved():
    retrieved = frozenset({
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1",
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc2",
    })
    cited = [
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1",
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc2",
    ]
    verified, rejected = verify_citations(cited, retrieved, CORPUS)
    assert verified == cited
    assert rejected == []


def test_not_in_corpus_rejected():
    """LLM fabricates an article number that doesn't exist."""
    retrieved = frozenset({"urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1"})
    cited = [
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1",
        "urn:lex:br:federal:lei:2018-08-14;13709~art99",  # hallucinated
    ]
    verified, rejected = verify_citations(cited, retrieved, CORPUS)
    assert verified == ["urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1"]
    assert rejected == [
        ("not-in-corpus", "urn:lex:br:federal:lei:2018-08-14;13709~art99"),
    ]


def test_not_in_context_rejected():
    """LLM cites a real URN that wasn't in the top-K — likely from training."""
    retrieved = frozenset({"urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1"})
    cited = [
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1",
        "urn:lex:br:federal:lei:2018-08-14;13709~art11",  # real, but not shown
    ]
    verified, rejected = verify_citations(cited, retrieved, CORPUS)
    assert verified == ["urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1"]
    assert rejected == [
        ("not-in-context", "urn:lex:br:federal:lei:2018-08-14;13709~art11"),
    ]


def test_duplicates_deduplicated_in_verified():
    retrieved = frozenset({"urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1"})
    cited = [
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1",
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1",
    ]
    verified, rejected = verify_citations(cited, retrieved, CORPUS)
    assert verified == ["urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1"]
    assert rejected == []


def test_empty_citations_returns_empty():
    verified, rejected = verify_citations([], frozenset(), CORPUS)
    assert verified == []
    assert rejected == []


def test_preserves_citation_order():
    """When the LLM orders citations meaningfully, we shouldn't shuffle."""
    retrieved = frozenset(CORPUS)
    cited = [
        "urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc4",
        "urn:lex:br:federal:lei:2018-08-14;13709~art11",
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1",
    ]
    verified, _ = verify_citations(cited, retrieved, CORPUS)
    assert verified == cited


def test_mixed_rejection_reasons():
    retrieved = frozenset({"urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1"})
    cited = [
        "urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1",   # verified
        "urn:lex:br:federal:lei:2018-08-14;13709~art99",       # not-in-corpus
        "urn:lex:br:federal:lei:2018-08-14;13709~art11",       # not-in-context
        "urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc4",  # not-in-context
    ]
    verified, rejected = verify_citations(cited, retrieved, CORPUS)
    assert verified == ["urn:lex:br:federal:lei:2018-08-14;13709~art7;inc1"]
    assert sorted(rejected) == sorted([
        ("not-in-corpus", "urn:lex:br:federal:lei:2018-08-14;13709~art99"),
        ("not-in-context", "urn:lex:br:federal:lei:2018-08-14;13709~art11"),
        ("not-in-context", "urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc4"),
    ])
