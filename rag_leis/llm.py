"""Anthropic LLM wrapper for the Phase 2 RAG pipeline.

Two surfaces:

* `complete()` — free-form text completion (used by the faithfulness judge).
* `complete_structured()` — forces a tool-call with `tool_choice`, so the
  model can only respond by emitting a JSON payload matching the supplied
  schema. We use this to enforce the `{answer, citations, unverified_claims}`
  contract for the generator.

Keys come from `.env` via python-dotenv (matches the pattern set by the
existing Voyage/Cohere integrations). Models hard-coded as defaults but
overridable per-instance.
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import Anthropic
from anthropic.types import TextBlock, ToolUseBlock
from dotenv import load_dotenv

load_dotenv()


DEFAULT_GENERATOR_MODEL = "claude-sonnet-4-5"
DEFAULT_JUDGE_MODEL = "claude-opus-4-7"


class AnthropicLLM:
    def __init__(self, model: str = DEFAULT_GENERATOR_MODEL, api_key: str | None = None):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env or pass api_key= explicitly."
            )
        self.client = Anthropic(api_key=key)
        self.model = model

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Pull all text blocks (typically one) and join — tool blocks shouldn't
        # appear here since we didn't pass `tools=`.
        parts = [b.text for b in resp.content if isinstance(b, TextBlock)]
        return "".join(parts)

    def complete_structured(
        self,
        system: str,
        user: str,
        tool_schema: dict[str, Any],
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Force the model to respond via the named tool.

        Returns the tool-call's `input` dict — validated by Anthropic against
        the supplied `input_schema`. Raises `RuntimeError` if no tool block
        comes back (shouldn't happen with `tool_choice`, but we guard).
        """
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool_schema],
            tool_choice={"type": "tool", "name": tool_schema["name"]},
        )
        for block in resp.content:
            if isinstance(block, ToolUseBlock) and block.name == tool_schema["name"]:
                # block.input is already a parsed dict (Anthropic SDK validates).
                return dict(block.input) if isinstance(block.input, dict) else {}
        raise RuntimeError(
            f"LLM did not return a tool_use block for {tool_schema['name']!r}; "
            f"stop_reason={resp.stop_reason!r}"
        )
