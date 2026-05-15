"""Unit tests for pure-logic helpers in rag_leis.run_answer_eval.

Network-free. Validates citation metrics behavior before we spend tokens
running the full pipeline.
"""

from __future__ import annotations

from rag_leis.run_answer_eval import score_citations


def test_perfect_match_p_r_f1_all_one():
    gold = frozenset({"a", "b", "c"})
    cited = ["a", "b", "c"]
    p_strict, p_lenient, r, f1 = score_citations(cited, gold)
    assert (p_strict, p_lenient, r, f1) == (1.0, 1.0, 1.0, 1.0)


def test_extra_citation_drops_precision():
    """3 hits + 1 fabrication → P=3/4=0.75, R=3/3=1.0."""
    gold = frozenset({"a", "b", "c"})
    cited = ["a", "b", "c", "fake"]
    p_strict, p_lenient, r, f1 = score_citations(cited, gold)
    assert p_strict == 0.75
    assert p_lenient == 0.75  # no alt → strict == lenient
    assert r == 1.0
    assert abs(f1 - (2 * 0.75 * 1.0 / 1.75)) < 1e-9


def test_missing_citation_drops_recall():
    """2 of 3 gold → P=1.0, R=2/3."""
    gold = frozenset({"a", "b", "c"})
    cited = ["a", "b"]
    p_strict, p_lenient, r, f1 = score_citations(cited, gold)
    assert p_strict == 1.0
    assert p_lenient == 1.0
    assert abs(r - 2 / 3) < 1e-9
    assert abs(f1 - (2 * 1.0 * (2 / 3) / (1.0 + 2 / 3))) < 1e-9


def test_empty_citations_with_gold_returns_zero():
    """Model refused / cited nothing on an answerable query."""
    gold = frozenset({"a", "b"})
    cited: list[str] = []
    p_strict, p_lenient, r, f1 = score_citations(cited, gold)
    assert (p_strict, p_lenient, r, f1) == (0.0, 0.0, 0.0, 0.0)


def test_empty_gold_oos_path_returns_zero():
    """OOS sentinel — score_citations isn't normally called on OOS, but
    if it is, return all zeros rather than NaN."""
    gold: frozenset[str] = frozenset()
    cited = ["any"]
    p_strict, p_lenient, r, f1 = score_citations(cited, gold)
    assert (p_strict, p_lenient, r, f1) == (0.0, 0.0, 0.0, 0.0)


def test_duplicate_citations_dont_inflate_precision():
    """LLM citing the same URN twice shouldn't game precision."""
    gold = frozenset({"a"})
    cited = ["a", "a", "fake"]
    p_strict, p_lenient, r, f1 = score_citations(cited, gold)
    # cited_set = {"a", "fake"} → hits=1, P=0.5, R=1.0
    assert p_strict == 0.5
    assert p_lenient == 0.5
    assert r == 1.0


def test_alt_lifts_lenient_but_not_strict_or_recall():
    """The MCI art.9 case: gold = single URN, alt = §§ exceções, model
    cites caput + 2 §§. Strict precision drops to 1/3; lenient stays at
    3/3 because all cited URNs are in gold ∪ alt; recall stays at 1.0."""
    gold = frozenset({"art9"})
    alt = frozenset({"art9;par1", "art9;par2", "art9;par3"})
    cited = ["art9", "art9;par1", "art9;par2"]
    p_strict, p_lenient, r, f1 = score_citations(cited, gold, alt)
    assert abs(p_strict - 1 / 3) < 1e-9
    assert p_lenient == 1.0
    assert r == 1.0  # alt doesn't change the recall denominator
    # F1 uses strict P, so it reflects the over-citation cost
    assert abs(f1 - (2 * (1 / 3) * 1.0 / (1 / 3 + 1.0))) < 1e-9


def test_alt_does_not_help_a_fabrication():
    """A URN outside both gold and alt is still rejected for lenient P."""
    gold = frozenset({"a"})
    alt = frozenset({"a;par1"})
    cited = ["a", "totally-fake"]
    p_strict, p_lenient, _r, _f1 = score_citations(cited, gold, alt)
    assert p_strict == 0.5
    assert p_lenient == 0.5  # "totally-fake" not in gold ∪ alt


def test_alt_alone_does_not_count_as_recall_hit():
    """If model cites ONLY alt URNs (and none of gold), recall is 0."""
    gold = frozenset({"a"})
    alt = frozenset({"a;par1", "a;par2"})
    cited = ["a;par1", "a;par2"]
    _p_s, p_l, r, _f1 = score_citations(cited, gold, alt)
    assert r == 0.0
    assert p_l == 1.0  # both cited URNs are in alt
