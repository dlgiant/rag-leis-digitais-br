"""Phase 10d — unit tests for `rewrite_for_classification`.

Tests use a FakeLLM that records its inputs and returns a programmed
response. No network calls. The eval against the actual 10
conversation_queries.yaml rows is in
`scripts/phase_10d_conversation_eval.py` (runs against real Maritaca,
~$0.003 per pass).

Contract under test (from Phase 17.2 + eval/conversation_queries.yaml):
  1. Empty prior_turns → return current_query verbatim, NO LLM call.
  2. Non-empty prior_turns → calls llm.complete() once.
  3. LLM exception → fallback to current_query.
  4. Response cleaning: strips quotes, code fences, prefixes.
  5. System prompt includes the 4 invariants (topic-shift, OOS, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from rag_leis.query_type import (
    _REWRITER_SYSTEM_PROMPT,
    _build_rewriter_user_message,
    _clean_rewriter_response,
    classify_query,
    rewrite_for_classification,
)


@dataclass
class FakeLLM:
    """Records every call + returns a programmed response.

    `responses` is consumed in order — first call gets responses[0],
    second gets responses[1], etc. Tests that expect a single call set
    `responses=["..."]`; tests for no-call paths set `responses=[]`
    and assert `calls == []` afterward.
    """

    responses: list[str]
    calls: list[dict[str, Any]] = field(default_factory=list)

    # Match the LLM Protocol's complete() signature loosely.
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        self.calls.append({
            "system": system, "user": user,
            "max_tokens": max_tokens, "temperature": temperature,
        })
        if not self.responses:
            raise RuntimeError("FakeLLM exhausted (no programmed response)")
        return self.responses.pop(0)


# ---------------------------------------------------------------------------
# 1. Empty prior_turns short-circuit
# ---------------------------------------------------------------------------


def test_empty_prior_turns_returns_verbatim_no_llm_call():
    llm = FakeLLM(responses=["should-not-be-used"])
    out = rewrite_for_classification(
        prior_turns=[], current_query="qual a definição de dado pessoal?",
        llm=llm,
    )
    assert out == "qual a definição de dado pessoal?"
    # The LLM MUST NOT have been called. First-turn cost is zero.
    assert llm.calls == []


# ---------------------------------------------------------------------------
# 2. Non-empty prior_turns triggers one LLM call
# ---------------------------------------------------------------------------


def test_one_llm_call_per_rewrite():
    llm = FakeLLM(responses=["o que diz o art. 5 da LGPD?"])
    out = rewrite_for_classification(
        prior_turns=[
            ("user", "o que é dado pessoal na LGPD?"),
            ("assistant", "Dado pessoal é toda informação relacionada a pessoa natural identificada ou identificável (LGPD art. 5, I)."),
        ],
        current_query="e o art. 5 que você mencionou?",
        llm=llm,
    )
    assert out == "o que diz o art. 5 da LGPD?"
    assert len(llm.calls) == 1
    call = llm.calls[0]
    # System prompt is the canonical one
    assert call["system"] == _REWRITER_SYSTEM_PROMPT
    # User message embeds both prior turns + current query
    assert "o que é dado pessoal na LGPD?" in call["user"]
    assert "Dado pessoal é toda informação" in call["user"]
    assert "e o art. 5 que você mencionou?" in call["user"]


# ---------------------------------------------------------------------------
# 3. LLM exception → fallback
# ---------------------------------------------------------------------------


def test_llm_failure_falls_back_to_current_query():
    """Defensive — a transient LLM failure shouldn't crash the pipeline.
    Fallback returns the current_query unchanged; downstream classifier
    + retrieval proceed as if it were single-turn (degraded but
    correct behavior)."""
    class _BrokenLLM:
        def complete(self, **kwargs: Any) -> str:
            raise ConnectionError("transient network failure")

    out = rewrite_for_classification(
        prior_turns=[("user", "anything")],
        current_query="e o art. 5?",
        llm=_BrokenLLM(),
    )
    assert out == "e o art. 5?"


# ---------------------------------------------------------------------------
# 4. Response cleaning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    # Quotes stripped
    ('"qual a definição de X?"', "qual a definição de X?"),
    ("'qual a X?'", "qual a X?"),
    ("“qual a X?”", "qual a X?"),
    # Code fences stripped
    ("```\nqual a X?\n```", "qual a X?"),
    ("```text\nqual a X?\n```", "qual a X?"),
    # Common Portuguese prefixes stripped
    ("Reescrita: qual a definição?", "qual a definição?"),
    ("Aqui está: qual a X?", "qual a X?"),
    ("Pergunta reescrita: qual a Y?", "qual a Y?"),
    # Clean response passes through
    ("qual a definição de dado pessoal?", "qual a definição de dado pessoal?"),
    # Whitespace trimmed
    ("  qual a X?  ", "qual a X?"),
])
def test_clean_rewriter_response_normalizes(raw: str, expected: str):
    assert _clean_rewriter_response(raw, fallback="FALLBACK") == expected


def test_clean_rewriter_response_falls_back_on_empty():
    assert _clean_rewriter_response("", fallback="FALLBACK") == "FALLBACK"
    assert _clean_rewriter_response("   ", fallback="FALLBACK") == "FALLBACK"


# ---------------------------------------------------------------------------
# 5. System prompt covers the 4 invariants
# ---------------------------------------------------------------------------


def test_system_prompt_mentions_topic_shift():
    """Topic-shift handling must be in the prompt — tested explicitly so
    a future prompt iteration that drops this rule fails this test."""
    assert "mudando de assunto" in _REWRITER_SYSTEM_PROMPT.lower()
    assert ("ignorar o histórico" in _REWRITER_SYSTEM_PROMPT.lower()
            or "drop" in _REWRITER_SYSTEM_PROMPT.lower())


def test_system_prompt_mentions_oos_preservation():
    """The "don't launder OOS" rule must be in the prompt explicitly —
    this is the row-9 (jurisprudência) failure mode the eval names."""
    assert "fora do escopo" in _REWRITER_SYSTEM_PROMPT.lower()
    assert "stf" in _REWRITER_SYSTEM_PROMPT.lower() or "jurisprudência" in _REWRITER_SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_classifier_compatibility():
    """The prompt should hint at vocabulary that matches the classifier
    regex — "qual a definição", "art. N", "comparação entre", "quais"."""
    txt = _REWRITER_SYSTEM_PROMPT.lower()
    assert "qual a definição" in txt or "definição de" in txt
    assert "art. n" in txt or "artigo n" in txt
    assert "comparação" in txt or "diferença" in txt
    assert "quais" in txt


def test_system_prompt_no_markdown_no_quotes():
    """The output-format rule must say 'no quotes, no fences, no
    prefix'. Tested explicitly because LLMs default to chat-style
    formatting unless told otherwise."""
    txt = _REWRITER_SYSTEM_PROMPT.lower()
    assert "sem aspas" in txt
    assert "sem markdown" in txt or "sem ```" in txt
    assert "sem prefixo" in txt or "sem prefix" in txt


# ---------------------------------------------------------------------------
# 6. User-message format
# ---------------------------------------------------------------------------


def test_user_message_format_separates_turns():
    msg = _build_rewriter_user_message(
        prior_turns=[
            ("user", "o que é LGPD?"),
            ("assistant", "A LGPD é..."),
        ],
        current_query="e o art. 5?",
    )
    # Each turn has an explicit role label
    assert "[USUÁRIO] o que é LGPD?" in msg
    assert "[ASSISTENTE] A LGPD é..." in msg
    # Current query is clearly labeled
    assert "PERGUNTA ATUAL: e o art. 5?" in msg


def test_user_message_truncates_long_assistant_turns():
    """Assistant turns can be long answer text; the rewriter only needs
    topic + key entities, so we cap at 400 chars."""
    long_answer = "A LGPD é " + ("texto longo " * 100)  # >>400 chars
    msg = _build_rewriter_user_message(
        prior_turns=[("assistant", long_answer)],
        current_query="o que diz o caput?",
    )
    # The truncated answer must appear with an ellipsis marker
    assert "…" in msg
    # The full long_answer should NOT appear (something was truncated)
    assert long_answer not in msg


# ---------------------------------------------------------------------------
# 7. Integration with the existing classify_query — make sure typical
#    rewrites still satisfy the classifier contract.
# ---------------------------------------------------------------------------


def test_rewriter_output_classifies_correctly():
    """End-to-end smoke: 4 representative rewrites that an ideal
    rewriter would produce, run through classify_query — the type
    should match what the eval/conversation_queries.yaml row expects."""
    cases = [
        # Citação literal — should match art-N regex
        ("o que diz o art. 5º da LGPD sobre definição de dado pessoal?", "citacao-literal"),
        # Definição
        ("qual a definição mais detalhada de hipossuficiência no CDC?", "definicao"),
        # Enumeração
        ("quais são os direitos do titular dos dados pessoais segundo a LGPD?", "enumeracao"),
        # Cross-doc
        ("comparação entre os princípios da LGPD e os princípios do Marco Civil", "cross-doc"),
    ]
    for rewrite, expected_type in cases:
        actual = classify_query(rewrite)
        assert actual == expected_type, (
            f"rewrite {rewrite!r} classified as {actual!r}, expected {expected_type!r}"
        )
