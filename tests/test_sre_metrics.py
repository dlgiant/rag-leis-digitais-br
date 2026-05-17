"""Phase 7.5.7 — SRE Golden Signals completeness tests.

Verifies that the four SRE-relevant fields are populated by both eval
runners (answer_eval + concurso_eval) on a baseline run shape:

  - latency_p50_ms / p95_ms / p99_ms / mean_ms
  - error_count / error_rate

Plus the judge-cost bug fix (Phase 7.5.7): cost accumulates judge spend,
not only generator spend.

These tests intentionally use stub LLMs (no network) so they run in CI
without API keys. The arithmetic + dataclass field surface is what we
guarantee; the actual production latencies (~5-20s per Sabiá call) are
out of scope for unit tests.

Cited gold-standard frame: Beyer et al., "Site Reliability Engineering"
(Google, 2016), ch.6 — the Four Golden Signals are Latency, Errors,
Saturation, Traffic. Saturation/Traffic are inapplicable to offline
batch eval (no queue, no QPS); Latency + Errors are.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from rag_leis.rag import RAGAnswer
from rag_leis.run_answer_eval import Aggregate, EvalRow, aggregate
from rag_leis.run_concurso_eval import (
    ConcursoAggregate,
    ConcursoEvalRecord,
    ConcursoRow,
    _fold_judge_cost_into_answer,
    aggregate as concurso_aggregate,
)


# ----------------------------------------------------------------------------
# Stub LLM — mimics the .last_call_usage shape without making network calls
# ----------------------------------------------------------------------------


class StubJudge:
    provider = "anthropic"
    name = "claude-opus-4-7"

    def __init__(self, in_tokens: int, out_tokens: int):
        self.last_call_usage = {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
        }


def _make_answer(
    *,
    latency_ms: float = 100.0,
    cost: float = 0.001,
    in_tok: int = 500,
    out_tok: int = 100,
    refused: bool = False,
    refusal_reason: str | None = None,
) -> RAGAnswer:
    """Build a minimal RAGAnswer matching the production shape."""
    return RAGAnswer(
        answer="test answer",
        citations=[],
        unverified_claims=[],
        rejected_citations=[],
        refused=refused,
        refusal_reason=refusal_reason,
        raw_retrieval=[],
        cost_estimate_usd=cost,
        tokens_used={"input_tokens": in_tok, "output_tokens": out_tok},
        llm_calls=1,
        latency_ms=latency_ms,
    )


# ----------------------------------------------------------------------------
# RAGAnswer has the latency field (the source of truth for the SRE signal)
# ----------------------------------------------------------------------------


def test_rag_answer_has_latency_ms_field():
    """latency_ms is a first-class field on RAGAnswer, default 0.0."""
    ans = RAGAnswer(
        answer="x",
        citations=[],
        unverified_claims=[],
        rejected_citations=[],
        refused=False,
        refusal_reason=None,
        raw_retrieval=[],
    )
    assert hasattr(ans, "latency_ms")
    assert ans.latency_ms == 0.0


def test_rag_answer_latency_ms_accepts_floats():
    ans = _make_answer(latency_ms=2453.7)
    assert ans.latency_ms == pytest.approx(2453.7)


# ----------------------------------------------------------------------------
# ConcursoAggregate computes p50/p95/p99 + error_rate
# ----------------------------------------------------------------------------


def _concurso_record(ans: RAGAnswer, category: str = "inscope") -> ConcursoEvalRecord:
    row = ConcursoRow(
        source_id=f"test/{category}",
        category=category,
        query="test",
    )
    return ConcursoEvalRecord(row=row, answer=ans, refused_correctly=not ans.refused)


def test_concurso_aggregate_latency_percentiles():
    """Latency p50/p95/p99 computed via nearest-rank percentile.
    For latencies [100, 200, 300, 400, 500]:
      - p50 → rank ceil(5*0.5)=3 → 300
      - p95 → rank ceil(5*0.95)=5 → 500
      - p99 → rank ceil(5*0.99)=5 → 500
    """
    records = [_concurso_record(_make_answer(latency_ms=lat)) for lat in (100, 200, 300, 400, 500)]
    agg = concurso_aggregate(records)
    assert agg.latency_p50_ms == 300.0
    assert agg.latency_p95_ms == 500.0
    assert agg.latency_p99_ms == 500.0
    assert agg.latency_mean_ms == 300.0


def test_concurso_aggregate_error_count_and_rate():
    """A row marked with refusal_reason starting 'ERROR:' counts toward
    error_count and is excluded from the latency distribution."""
    records = [
        _concurso_record(_make_answer(latency_ms=100)),
        _concurso_record(_make_answer(latency_ms=200)),
        _concurso_record(_make_answer(
            latency_ms=99999.0,  # would skew p99 if not filtered
            refused=True,
            refusal_reason="ERROR: ConnectionError: rate limited",
        )),
    ]
    agg = concurso_aggregate(records)
    assert agg.error_count == 1
    assert agg.error_rate == pytest.approx(1 / 3, abs=1e-4)
    # Latency distribution should only include the 2 non-error rows.
    # Nearest-rank percentile on sorted [100, 200]:
    #   p50 → rank ceil(2*0.5)=1 → xs[0] = 100
    #   p99 → rank ceil(2*0.99)=2 → xs[1] = 200 (max)
    assert agg.latency_p50_ms == 100.0
    assert agg.latency_p99_ms == 200.0


def test_concurso_aggregate_empty_returns_zeros():
    """Empty records → all SRE fields are 0 (no division-by-zero)."""
    agg = concurso_aggregate([])
    assert agg.latency_p50_ms == 0.0
    assert agg.latency_p95_ms == 0.0
    assert agg.error_count == 0
    assert agg.error_rate == 0.0


# ----------------------------------------------------------------------------
# answer_eval Aggregate: same shape on the other runner
# ----------------------------------------------------------------------------


def _eval_row(ans: RAGAnswer, oos: bool = False) -> EvalRow:
    from rag_leis.run_answer_eval import AnswerQuery
    q = AnswerQuery(
        query="test",
        type="paráfrase",
        oos=oos,
        gold_urns=frozenset(),
        alternative_acceptable_urns=frozenset(),
        expected_paragraph="",
    )
    return EvalRow(query=q, answer=ans, refused_correctly=not ans.refused if not oos else ans.refused)


def test_answer_eval_aggregate_has_sre_fields():
    """Aggregate dataclass exposes the SRE-Golden-Signals fields."""
    rows = [_eval_row(_make_answer(latency_ms=150))]
    agg = aggregate(rows)
    assert hasattr(agg, "latency_p50_ms")
    assert hasattr(agg, "latency_p95_ms")
    assert hasattr(agg, "latency_p99_ms")
    assert hasattr(agg, "latency_mean_ms")
    assert hasattr(agg, "error_count")
    assert hasattr(agg, "error_rate")
    assert agg.latency_p50_ms == 150.0


def test_answer_eval_aggregate_filters_errors_from_latency():
    rows = [
        _eval_row(_make_answer(latency_ms=100)),
        _eval_row(_make_answer(
            latency_ms=88888.0,
            refused=True,
            refusal_reason="ERROR: timeout",
        )),
    ]
    agg = aggregate(rows)
    assert agg.error_count == 1
    assert agg.latency_p99_ms == 100.0  # error row excluded


# ----------------------------------------------------------------------------
# Judge cost bug fix — _fold_judge_cost_into_answer accumulates correctly
# ----------------------------------------------------------------------------


def test_fold_judge_cost_adds_opus_pricing_to_answer():
    """Opus is $15/$75 per 1M (input/output). Folding 1000/500 should add
    1000*15/1M + 500*75/1M = 0.015 + 0.0375 = 0.0525 USD.
    Pre-existing cost on the RAGAnswer is preserved (cumulative)."""
    ans = _make_answer(cost=0.01, in_tok=1000, out_tok=200)
    judge = StubJudge(in_tokens=1000, out_tokens=500)
    _fold_judge_cost_into_answer(ans, judge)
    # Generator cost (0.01) + judge cost (0.0525) = 0.0625
    assert ans.cost_estimate_usd == pytest.approx(0.0625, abs=1e-6)
    # Tokens accumulate
    assert ans.tokens_used["input_tokens"] == 2000  # 1000 gen + 1000 judge
    assert ans.tokens_used["output_tokens"] == 700  # 200 gen + 500 judge
    assert ans.llm_calls == 2  # initial + judge


def test_fold_judge_cost_handles_missing_last_call_usage():
    """If judge.last_call_usage is missing or None, fold is a no-op (cost
    unchanged). Defensive: a judge implementation without usage tracking
    must not crash the eval."""
    ans = _make_answer(cost=0.005)

    class JudgeWithoutUsage:
        provider = "anthropic"
        name = "claude-opus-4-7"
        last_call_usage = None

    pre_cost = ans.cost_estimate_usd
    _fold_judge_cost_into_answer(ans, JudgeWithoutUsage())
    assert ans.cost_estimate_usd == pre_cost


def test_fold_judge_cost_initializes_empty_tokens_dict():
    """RAGAnswer.tokens_used can be empty {}; fold must populate it
    without raising KeyError."""
    ans = RAGAnswer(
        answer="x",
        citations=[],
        unverified_claims=[],
        rejected_citations=[],
        refused=False,
        refusal_reason=None,
        raw_retrieval=[],
        cost_estimate_usd=0.0,
        tokens_used={},  # empty
        llm_calls=0,
    )
    judge = StubJudge(in_tokens=100, out_tokens=50)
    _fold_judge_cost_into_answer(ans, judge)
    assert ans.tokens_used["input_tokens"] == 100
    assert ans.tokens_used["output_tokens"] == 50
    assert ans.llm_calls == 1
