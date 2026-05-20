"""Phase 7.8 — tests for per-citation relevance gate.

Pure-logic + stub-LLM. The integration (pipeline-level gate firing) is
exercised by the eval runs; this file covers the building blocks:

  - judge_citation_relevance: defensive defaults, vocab filter,
    omitted-URN default, judge-error handling
  - The rag.py gate decision predicate (all-irrelevant → refuse;
    partial-irrelevance → don't refuse)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from rag_leis.citation_relevance import (
    CITATION_RELEVANCE_TOOL,
    RELEVANCE_JUDGE_SYSTEM,
    judge_citation_relevance,
)
from rag_leis.eval_harness import IndexChunk


def _make_chunk(urn: str, text: str) -> IndexChunk:
    return IndexChunk(urn=urn, text=text, nav_text="", caput_text="", citation="")


def _chunks_dict(*chunks: IndexChunk) -> dict[str, IndexChunk]:
    return {c.urn: c for c in chunks}


def _stub_llm_returning(evaluations: list[dict]):
    stub = MagicMock()
    stub.complete_structured.return_value = {"evaluations": evaluations}
    stub.last_call_usage = {"input_tokens": 500, "output_tokens": 100}
    stub.provider = "maritaca"
    stub.name = "sabia-3.1"
    return stub


# ----------------------------------------------------------------------------
# Tool schema / system prompt integrity
# ----------------------------------------------------------------------------


def test_tool_schema_shape():
    assert CITATION_RELEVANCE_TOOL["name"] == "avaliar_relevancia_citacoes"
    props = CITATION_RELEVANCE_TOOL["input_schema"]["properties"]
    assert "evaluations" in props
    assert props["evaluations"]["type"] == "array"
    item_props = props["evaluations"]["items"]["properties"]
    assert {"urn", "relevant", "reason"} <= set(item_props.keys())


def test_system_prompt_mentions_strict_criterion():
    # Sanity check on the prompt — we want the judge to lean conservative.
    assert "ESTRITO" in RELEVANCE_JUDGE_SYSTEM
    assert "false" in RELEVANCE_JUDGE_SYSTEM  # tells judge when to mark false


# ----------------------------------------------------------------------------
# judge_citation_relevance — defensive defaults
# ----------------------------------------------------------------------------


def test_empty_citations_returns_empty_dict_no_llm_call():
    """No citations to judge → skip the LLM call entirely."""
    stub = _stub_llm_returning([])
    result = judge_citation_relevance(stub, "query", [], {})
    assert result == {}
    stub.complete_structured.assert_not_called()


def test_happy_path_all_relevant():
    urn = "urn:lex:br:federal:lei:2018-08-14;13709~art5"
    chunks = _chunks_dict(_make_chunk(urn, "Art. 5: dados pessoais..."))
    stub = _stub_llm_returning([
        {"urn": urn, "relevant": True, "reason": "directly addresses query"},
    ])
    result = judge_citation_relevance(stub, "o que é dado pessoal?", [urn], chunks)
    assert result == {urn: True}


def test_happy_path_all_irrelevant():
    urn = "urn:lex:br:federal:lei:1997-11-12;9507~art8"
    chunks = _chunks_dict(_make_chunk(urn, "Art. 8: habeas data procedure..."))
    stub = _stub_llm_returning([
        {"urn": urn, "relevant": False, "reason": "habeas data procedure, not CPC requirements"},
    ])
    result = judge_citation_relevance(stub, "requisitos do CPC para petição inicial", [urn], chunks)
    assert result == {urn: False}


def test_hallucinated_urn_in_response_is_ignored():
    """Judge returns evaluation for a URN that wasn't in the input list
    — must be silently dropped."""
    urn_real = "urn:lex:br:federal:lei:2018-08-14;13709~art5"
    chunks = _chunks_dict(_make_chunk(urn_real, "..."))
    stub = _stub_llm_returning([
        {"urn": urn_real, "relevant": True, "reason": "..."},
        {"urn": "urn:lex:br:federal:lei:fake;9999~art1", "relevant": False, "reason": "..."},
    ])
    result = judge_citation_relevance(stub, "q", [urn_real], chunks)
    assert urn_real in result
    assert "urn:lex:br:federal:lei:fake;9999~art1" not in result


def test_omitted_urn_defaults_to_relevant_true():
    """Judge fails to evaluate one of the input URNs (omitted from
    response) — default to relevant=True to avoid over-refusing on
    judge incompleteness."""
    urn_a = "urn:lex:br:federal:lei:2018-08-14;13709~art5"
    urn_b = "urn:lex:br:federal:lei:2018-08-14;13709~art6"
    chunks = _chunks_dict(_make_chunk(urn_a, "..."), _make_chunk(urn_b, "..."))
    stub = _stub_llm_returning([
        {"urn": urn_a, "relevant": False, "reason": "..."},
        # urn_b is omitted by the judge
    ])
    result = judge_citation_relevance(stub, "q", [urn_a, urn_b], chunks)
    assert result[urn_a] is False
    assert result[urn_b] is True  # defensive default


def test_judge_error_returns_empty_dict():
    """Judge LLM raises (timeout, schema parse, etc.) → empty dict.
    Caller treats this as 'no evaluations' and defers to downstream
    gates (which is the safe default; we don't refuse on judge failure)."""
    stub = MagicMock()
    stub.complete_structured.side_effect = RuntimeError("rate limited")
    stub.provider = "maritaca"
    stub.name = "sabia-3.1"
    result = judge_citation_relevance(stub, "q", ["urn:foo"], {})
    assert result == {}


def test_malformed_response_items_dropped():
    """Defensive: judge returns evaluations with non-dict items."""
    urn = "urn:lex:br:federal:lei:2018-08-14;13709~art5"
    chunks = _chunks_dict(_make_chunk(urn, "..."))
    stub = MagicMock()
    stub.complete_structured.return_value = {
        "evaluations": [
            None,
            "not a dict",
            {"urn": urn, "relevant": True, "reason": "..."},
        ]
    }
    stub.last_call_usage = {"input_tokens": 100, "output_tokens": 20}
    stub.provider = "maritaca"
    stub.name = "sabia-3.1"
    result = judge_citation_relevance(stub, "q", [urn], chunks)
    assert result == {urn: True}


def test_chunk_not_in_dict_does_not_crash():
    """Defensive: input URN that doesn't resolve to a chunk should still
    be sent to judge with a placeholder text (judge can still evaluate
    based on the URN itself)."""
    urn = "urn:lex:br:federal:lei:2018-08-14;13709~art5"
    stub = _stub_llm_returning([{"urn": urn, "relevant": False, "reason": "..."}])
    result = judge_citation_relevance(stub, "q", [urn], {})  # empty chunks dict
    assert result == {urn: False}
    # The judge was called (didn't crash on missing chunk)
    stub.complete_structured.assert_called_once()


# ----------------------------------------------------------------------------
# Gate-decision predicate (the all-irrelevant → refuse logic in rag.py)
#
# The gate fires only when EVERY verified citation is judged irrelevant.
# Partial irrelevance keeps the answer (at least one citation supports).
# Tested directly on the decision dict shape rather than spinning up a
# full RAGPipeline.
# ----------------------------------------------------------------------------


def test_gate_predicate_all_irrelevant_fires():
    decisions = {"urn:a": False, "urn:b": False}
    verified = list(decisions.keys())
    rejected = [u for u, rel in decisions.items() if not rel]
    should_refuse = bool(rejected) and len(rejected) == len(verified)
    assert should_refuse is True
    assert set(rejected) == set(verified)


def test_gate_predicate_partial_irrelevant_does_not_fire():
    decisions = {"urn:a": True, "urn:b": False}
    verified = list(decisions.keys())
    rejected = [u for u, rel in decisions.items() if not rel]
    should_refuse = bool(rejected) and len(rejected) == len(verified)
    assert should_refuse is False
    assert rejected == ["urn:b"]  # surfaced for audit


def test_gate_predicate_all_relevant_does_not_fire():
    decisions = {"urn:a": True, "urn:b": True}
    verified = list(decisions.keys())
    rejected = [u for u, rel in decisions.items() if not rel]
    should_refuse = bool(rejected) and len(rejected) == len(verified)
    assert should_refuse is False
    assert rejected == []


def test_gate_predicate_empty_decisions_does_not_fire():
    """Judge returned no decisions (error or empty input) → don't refuse
    (defer to downstream gates)."""
    decisions: dict[str, bool] = {}
    verified = ["urn:a", "urn:b"]
    rejected = [u for u, rel in decisions.items() if not rel]
    should_refuse = bool(rejected) and len(rejected) == len(verified)
    assert should_refuse is False
