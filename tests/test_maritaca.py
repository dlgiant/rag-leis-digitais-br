"""Tests for the Marítaca LLM adapter.

Two layers:
  1. Pure-logic on `_to_openai_tool` — schema translation correctness
  2. Live smoke (network-marked, skipped without MARITACA_API_KEY)
     — confirms tool_choice forces JSON, basic completion works
"""

from __future__ import annotations

import os

import pytest

from rag_leis.maritaca import (
    DEFAULT_MARITACA_MODEL,
    KNOWN_MARITACA_MODELS,
    MaritacaLLM,
    _to_openai_tool,
)

# ----------------------------------------------------------------------------
# Pure-logic: schema translation
# ----------------------------------------------------------------------------


def test_to_openai_tool_translates_anthropic_schema():
    anthropic = {
        "name": "responder",
        "description": "Submeta a resposta.",
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["answer", "citations"],
        },
    }
    openai = _to_openai_tool(anthropic)
    assert openai["type"] == "function"
    assert openai["function"]["name"] == "responder"
    assert openai["function"]["description"] == "Submeta a resposta."
    # Inner JSON Schema body must be passed through unchanged
    assert openai["function"]["parameters"] == anthropic["input_schema"]


def test_to_openai_tool_handles_missing_description():
    anthropic = {"name": "x", "input_schema": {"type": "object"}}
    openai = _to_openai_tool(anthropic)
    assert openai["function"]["description"] == ""


def test_default_model_is_in_known_list():
    """If we ever change the default, ensure it stays in KNOWN_MARITACA_MODELS."""
    assert DEFAULT_MARITACA_MODEL in KNOWN_MARITACA_MODELS


# ----------------------------------------------------------------------------
# Live smoke (network-marked)
# ----------------------------------------------------------------------------


pytestmark_network = pytest.mark.skipif(
    "MARITACA_API_KEY" not in os.environ,
    reason="MARITACA_API_KEY not set; skipping live API tests",
)


@pytest.mark.network
@pytestmark_network
def test_complete_returns_text():
    llm = MaritacaLLM()
    out = llm.complete(
        system="Você responde em português, em uma única frase curta.",
        user="Qual a capital do Brasil?",
        max_tokens=64,
    )
    assert isinstance(out, str)
    assert "Brasília" in out or "brasília" in out.lower()


@pytest.mark.network
@pytestmark_network
def test_complete_structured_forces_schema():
    """tool_choice must force the model to emit the named function call.

    Critical for Phase 4.0: the LLM Protocol contract assumes
    complete_structured returns a validated dict. If Marítaca's tool_choice
    doesn't force, this test fails and we know to add retry/JSON-mode
    fallback before running the full benchmark."""
    llm = MaritacaLLM()
    tool_schema = {
        "name": "responder_capital",
        "description": "Submeta a capital de um país.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pais": {"type": "string"},
                "capital": {"type": "string"},
                "populacao_aprox_milhoes": {"type": "number"},
            },
            "required": ["pais", "capital", "populacao_aprox_milhoes"],
        },
    }
    out = llm.complete_structured(
        system="Use a ferramenta fornecida para responder.",
        user="Qual a capital do Brasil e sua população aproximada (milhões)?",
        tool_schema=tool_schema,
        max_tokens=256,
    )
    assert isinstance(out, dict)
    assert set(out.keys()) >= {"pais", "capital", "populacao_aprox_milhoes"}
    assert "Brasil" in str(out["pais"])
    assert "Brasília" in str(out["capital"]) or "brasília" in str(out["capital"]).lower()
    assert isinstance(out["populacao_aprox_milhoes"], (int, float))
