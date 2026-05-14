"""Smoke tests for the Anthropic LLM wrapper.

Marked `network` because they hit the live Anthropic API and consume tokens.
Run explicitly:

    uv run pytest tests/test_llm.py -m network -v

The structured-output test is the load-bearing one: it proves that
`tool_choice` forces the model to respond via the supplied schema, which is
the contract Phase 2 relies on (no free-form parsing, no JSON-mode retries).
"""

from __future__ import annotations

import os

import pytest

from rag_leis.llm import AnthropicLLM

pytestmark = pytest.mark.skipif(
    "ANTHROPIC_API_KEY" not in os.environ,
    reason="ANTHROPIC_API_KEY not set; skipping live API tests",
)


@pytest.mark.network
def test_complete_returns_text():
    llm = AnthropicLLM()
    out = llm.complete(
        system="Você responde em português, em uma única frase curta.",
        user="Qual a capital do Brasil?",
        max_tokens=64,
    )
    assert isinstance(out, str)
    assert "Brasília" in out or "brasília" in out.lower()


@pytest.mark.network
def test_complete_structured_forces_schema():
    """tool_choice must force the model to emit the named tool's input."""
    llm = AnthropicLLM()
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
    assert "Brasil" in out["pais"] or "Brazil" in out["pais"]
    assert "Brasília" in out["capital"] or "brasília" in out["capital"].lower()
    assert isinstance(out["populacao_aprox_milhoes"], (int, float))
