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


# ----------------------------------------------------------------------------
# Phase 7.5.1 — false_refusal_rate + oos_refusal_recall as first-class metrics.
# Aggregate-level confusion-matrix split. The existing `refusal_accuracy`
# (macro avg over both in-scope and OOS) collapsed two distinct dimensions;
# these tests pin the explicit split.
# ----------------------------------------------------------------------------

from dataclasses import dataclass
from typing import Optional

from rag_leis.run_answer_eval import AnswerQuery, EvalRow, aggregate
from rag_leis.rag import RAGAnswer


def _row(*, oos: bool, refused: bool, query_type: str = "definicao") -> EvalRow:
    """Minimal EvalRow construction for aggregate-level tests."""
    aq = AnswerQuery(
        query="q",
        type=query_type,
        oos=oos,
        gold_urns=frozenset() if oos else frozenset({"u"}),
        alternative_acceptable_urns=frozenset(),
        expected_paragraph="" if oos else "p",
    )
    ans = RAGAnswer(
        answer="" if refused else "a",
        citations=[] if (refused or oos) else ["u"],
        unverified_claims=[],
        rejected_citations=[],
        refused=refused,
        refusal_reason="test" if refused else None,
        raw_retrieval=[],
    )
    return EvalRow(
        query=aq,
        answer=ans,
        cit_precision=None if oos else (1.0 if not refused else 0.0),
        cit_precision_lenient=None if oos else (1.0 if not refused else 0.0),
        cit_recall=None if oos else (1.0 if not refused else 0.0),
        cit_f1=None if oos else (1.0 if not refused else 0.0),
        faithfulness=None if oos else (5 if not refused else 0),
        refused_correctly=(refused if oos else (not refused)),
    )


def test_false_refusal_rate_perfect_pipeline_is_zero():
    """3 in-scope, all answered (refused=False). False refusal rate = 0."""
    rows = [_row(oos=False, refused=False) for _ in range(3)]
    agg = aggregate(rows)
    assert agg.false_refusal_rate == 0.0
    assert agg.n_inscope == 3
    assert agg.n_oos == 0


def test_false_refusal_rate_pipeline_refuses_one_inscope():
    """3 in-scope, 1 refused. false_refusal_rate = 1/3."""
    rows = [
        _row(oos=False, refused=False),
        _row(oos=False, refused=True),
        _row(oos=False, refused=False),
    ]
    agg = aggregate(rows)
    assert agg.false_refusal_rate == 1 / 3


def test_oos_refusal_recall_perfect_pipeline_is_one():
    """3 OOS, all refused. recall = 1."""
    rows = [_row(oos=True, refused=True) for _ in range(3)]
    agg = aggregate(rows)
    assert agg.oos_refusal_recall == 1.0
    assert agg.n_oos == 3


def test_oos_refusal_recall_pipeline_misses_two_of_three_oos():
    """3 OOS, 1 correctly refused, 2 wrongly answered. recall = 1/3."""
    rows = [
        _row(oos=True, refused=True),
        _row(oos=True, refused=False),
        _row(oos=True, refused=False),
    ]
    agg = aggregate(rows)
    assert agg.oos_refusal_recall == 1 / 3


def test_false_refusal_and_oos_recall_independent():
    """Mixed: 2 in-scope (1 refused), 2 OOS (1 refused).
    false_refusal_rate = 1/2 ; oos_refusal_recall = 1/2.
    These ARE independent dimensions — the macro `refusal_accuracy` of 0.5
    hides both being suboptimal."""
    rows = [
        _row(oos=False, refused=False),  # correct answer
        _row(oos=False, refused=True),   # false refusal
        _row(oos=True, refused=True),    # correct refusal
        _row(oos=True, refused=False),   # false answer (missed OOS)
    ]
    agg = aggregate(rows)
    assert agg.false_refusal_rate == 0.5
    assert agg.oos_refusal_recall == 0.5
    assert agg.refusal_accuracy == 0.5  # macro: 2 of 4 refused_correctly


def test_empty_oos_subset_does_not_crash():
    """All in-scope, no OOS. oos_refusal_recall = 0 by safe-div default."""
    rows = [_row(oos=False, refused=False) for _ in range(2)]
    agg = aggregate(rows)
    assert agg.oos_refusal_recall == 0.0  # 0/0 → 0 by _safe_div
    assert agg.false_refusal_rate == 0.0
    assert agg.n_oos == 0


def test_empty_inscope_subset_does_not_crash():
    """All OOS, no in-scope. false_refusal_rate = 0 by safe-div default."""
    rows = [_row(oos=True, refused=True) for _ in range(2)]
    agg = aggregate(rows)
    assert agg.false_refusal_rate == 0.0  # 0/0 → 0
    assert agg.oos_refusal_recall == 1.0


# ----------------------------------------------------------------------------
# Phase 7.5.2 — cost + token aggregates.
# Pipeline populates RAGAnswer.{cost_estimate_usd, tokens_used, llm_calls};
# aggregate() sums into the Aggregate dataclass. These tests use synthetic
# RAGAnswer objects with pre-set cost fields to avoid mocking LLM.
# ----------------------------------------------------------------------------


def _row_with_cost(*, cost: float, in_tok: int, out_tok: int, calls: int) -> EvalRow:
    """In-scope answered row with explicit cost fields set."""
    aq = AnswerQuery(
        query="q", type="definicao", oos=False,
        gold_urns=frozenset({"u"}), alternative_acceptable_urns=frozenset(),
        expected_paragraph="p",
    )
    ans = RAGAnswer(
        answer="a", citations=["u"], unverified_claims=[], rejected_citations=[],
        refused=False, refusal_reason=None, raw_retrieval=[],
        cost_estimate_usd=cost,
        tokens_used={"input_tokens": in_tok, "output_tokens": out_tok},
        llm_calls=calls,
    )
    return EvalRow(
        query=aq, answer=ans,
        cit_precision=1.0, cit_precision_lenient=1.0, cit_recall=1.0, cit_f1=1.0,
        faithfulness=5, refused_correctly=True,
    )


def test_cost_total_sums_across_rows():
    rows = [
        _row_with_cost(cost=0.01, in_tok=1000, out_tok=500, calls=1),
        _row_with_cost(cost=0.02, in_tok=2000, out_tok=1000, calls=1),
        _row_with_cost(cost=0.03, in_tok=3000, out_tok=1500, calls=2),  # retry fired
    ]
    agg = aggregate(rows)
    assert agg.cost_total_usd == 0.06  # 0.01 + 0.02 + 0.03
    assert agg.total_input_tokens == 6000
    assert agg.total_output_tokens == 3000
    assert agg.total_llm_calls == 4  # 1 + 1 + 2


def test_cost_mean_per_query():
    rows = [
        _row_with_cost(cost=0.10, in_tok=0, out_tok=0, calls=1),
        _row_with_cost(cost=0.30, in_tok=0, out_tok=0, calls=1),
    ]
    agg = aggregate(rows)
    assert agg.cost_mean_usd == 0.20


def test_cost_zero_when_pipeline_does_not_populate():
    """Backwards-compat: pre-Phase-7.5.2 RAGAnswer instances lack the new
    fields (default 0). Aggregate should still compute without crashing."""
    rows = [_row(oos=False, refused=False) for _ in range(2)]
    # `_row` uses bare RAGAnswer() which gets cost_estimate_usd=0 default
    agg = aggregate(rows)
    assert agg.cost_total_usd == 0.0
    assert agg.cost_mean_usd == 0.0
    assert agg.total_input_tokens == 0


def test_aggregate_empty_rows_does_not_crash():
    agg = aggregate([])
    assert agg.cost_total_usd == 0.0
    assert agg.cost_mean_usd == 0.0  # avoid div-by-zero
    assert agg.n_total == 0
