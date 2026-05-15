"""Marítaca AI LLM adapter — Sabiá-3 family, BR-resident.

Implements the `LLM` Protocol from rag_leis.llm. Uses the OpenAI-compatible
endpoint at `chat.maritaca.ai/api`, so we ride on the openai SDK.

Why this exists: D9 (LGPD data residency) — Anthropic doesn't host in BR.
Marítaca is São Paulo-based and Sabiá is fine-tuned for Portuguese.
Phase 4.0 benchmark compares against Anthropic on the project's
answer-eval to make D9 a data-driven decision.

Critical contract decision: tool_choice forcing.

  Anthropic: `tool_choice={"type": "tool", "name": ...}` is enforced
  by the SDK + server side. Returned `tool_use` block is validated
  against `input_schema`.

  Marítaca / OpenAI-compatible: `tool_choice={"type": "function",
  "function": {"name": ...}}` is the analogue. As of 2026-05-15
  smoke tests (commit context), all three Sabiá-3.x models honor
  this and return parseable JSON in `tool_calls[0].function.arguments`.

  We DON'T retry on parse failure here — if Sabiá returns invalid
  JSON, that's a quality signal the benchmark needs to surface
  (rejected_citation_rate proxy). A retry budget is appropriate
  for a production fallback layer (Phase 7.4), not for the v0 adapter.
"""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


MARITACA_BASE_URL = "https://chat.maritaca.ai/api"

# Default to sabia-3.1 — latest in the sabia-3 family, tool-call confirmed,
# best simple-question quality in 2026-05-15 smoke test. sabia-4 is
# available but defer to benchmark before committing to it.
DEFAULT_MARITACA_MODEL = "sabia-3.1"

# All Marítaca models that expose chat completions + function calling.
# Used by the comparison runner to iterate.
KNOWN_MARITACA_MODELS = ("sabia-4", "sabiazinho-4", "sabia-3.1", "sabia-3", "sabiazinho-3")


class MaritacaLLM:
    provider: str = "maritaca"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ):
        key = api_key or os.environ.get("MARITACA_API_KEY")
        if not key:
            raise RuntimeError(
                "MARITACA_API_KEY not set. Add it to .env or pass api_key= explicitly."
            )
        self.client = OpenAI(api_key=key, base_url=MARITACA_BASE_URL)
        self.model = model or DEFAULT_MARITACA_MODEL
        self.name = self.model  # protocol field — alias

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def complete_structured(
        self,
        system: str,
        user: str,
        tool_schema: dict[str, Any],
        max_tokens: int = 2048,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Force a function-call matching `tool_schema`.

        The supplied `tool_schema` is in Anthropic format
        (`{name, description, input_schema}`). Translate to OpenAI format
        (`{type: function, function: {name, description, parameters}}`).
        Return the parsed `arguments` dict.

        Raises RuntimeError if no tool_call comes back, or if the
        arguments fail to parse as JSON (no retry here — the benchmark
        needs to see the failure rate honestly).
        """
        openai_tool = _to_openai_tool(tool_schema)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": [openai_tool],
            "tool_choice": {
                "type": "function",
                "function": {"name": tool_schema["name"]},
            },
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            raise RuntimeError(
                f"Marítaca did not return a tool_call for {tool_schema['name']!r}; "
                f"finish_reason={resp.choices[0].finish_reason!r}, "
                f"content={msg.content!r}"
            )
        tc = msg.tool_calls[0]
        if tc.function.name != tool_schema["name"]:
            raise RuntimeError(
                f"Marítaca returned tool_call for {tc.function.name!r}, "
                f"expected {tool_schema['name']!r}"
            )
        try:
            return dict(json.loads(tc.function.arguments))
        except (json.JSONDecodeError, TypeError) as e:
            raise RuntimeError(
                f"Marítaca tool_call arguments not parseable as JSON: {tc.function.arguments!r}"
            ) from e


def _to_openai_tool(anthropic_tool: dict[str, Any]) -> dict[str, Any]:
    """Translate Anthropic tool schema to OpenAI function-call schema.

    Anthropic: `{name, description, input_schema}`
    OpenAI:    `{type: "function", function: {name, description, parameters}}`

    The JSON Schema body itself (the inner properties) is identical between
    the two — only the wrapper differs. Kept as a free function so it's
    reusable if other OpenAI-compatible providers join later (Bedrock,
    self-hosted vLLM, etc.).
    """
    return {
        "type": "function",
        "function": {
            "name": anthropic_tool["name"],
            "description": anthropic_tool.get("description", ""),
            "parameters": anthropic_tool["input_schema"],
        },
    }
