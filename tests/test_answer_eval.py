"""Unit tests for pure-logic helpers in rag_leis.run_answer_eval.

Network-free. Validates citation metrics behavior before we spend tokens
running the full pipeline.
"""

from __future__ import annotations

from rag_leis.run_answer_eval import score_citations


def test_perfect_match_p_r_f1_all_one():
    gold = frozenset({"a", "b", "c"})
    cited = ["a", "b", "c"]
    p, r, f1 = score_citations(cited, gold)
    assert (p, r, f1) == (1.0, 1.0, 1.0)


def test_extra_citation_drops_precision():
    """3 hits + 1 fabrication → P=3/4=0.75, R=3/3=1.0."""
    gold = frozenset({"a", "b", "c"})
    cited = ["a", "b", "c", "fake"]
    p, r, f1 = score_citations(cited, gold)
    assert p == 0.75
    assert r == 1.0
    assert abs(f1 - (2 * 0.75 * 1.0 / 1.75)) < 1e-9


def test_missing_citation_drops_recall():
    """2 of 3 gold → P=1.0, R=2/3."""
    gold = frozenset({"a", "b", "c"})
    cited = ["a", "b"]
    p, r, f1 = score_citations(cited, gold)
    assert p == 1.0
    assert abs(r - 2 / 3) < 1e-9
    assert abs(f1 - (2 * 1.0 * (2 / 3) / (1.0 + 2 / 3))) < 1e-9


def test_empty_citations_with_gold_returns_zero():
    """Model refused / cited nothing on an answerable query."""
    gold = frozenset({"a", "b"})
    cited: list[str] = []
    p, r, f1 = score_citations(cited, gold)
    assert (p, r, f1) == (0.0, 0.0, 0.0)


def test_empty_gold_oos_path_returns_zero():
    """OOS sentinel — score_citations isn't normally called on OOS, but
    if it is, return all zeros rather than NaN."""
    gold: frozenset[str] = frozenset()
    cited = ["any"]
    p, r, f1 = score_citations(cited, gold)
    assert (p, r, f1) == (0.0, 0.0, 0.0)


def test_duplicate_citations_dont_inflate_precision():
    """LLM citing the same URN twice shouldn't game precision."""
    gold = frozenset({"a"})
    cited = ["a", "a", "fake"]
    p, r, f1 = score_citations(cited, gold)
    # cited_set = {"a", "fake"} → hits=1, P=0.5, R=1.0
    assert p == 0.5
    assert r == 1.0
