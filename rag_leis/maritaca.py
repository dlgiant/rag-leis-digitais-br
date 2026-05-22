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
from pathlib import Path
from typing import Any

from openai import OpenAI

from rag_leis import llm_cache

# Phase 17.3 — dotenv loading moved to entry points (server lifespan,
# eval CLI tops, tests/conftest.py). See rag_leis/llm.py module
# docstring for the rationale.


MARITACA_BASE_URL = "https://chat.maritaca.ai/api"

# Default to sabia-4 — newer architecture, fixes the Sabiá-family
# blindspot on row 12 (Decreto 8.771 art13 §2 incisos misclassified
# as irrelevant by sabia-3.1 AND sonnet-4-5; sabia-4 joins opus on
# the right side). 2026-05-19 A/B (study/phase-8-0-1-sabia-3.1-vs-4-findings.md):
# in-scope false_refusal_rate 0.143 → 0.071, OOS recall 0.594 → 0.672,
# cost ratio 1.20× (under the 2× cap), latency p95 +5× (614ms → 2865ms
# on the answered subset; cosine-fast-path p50 unchanged at 306ms).
DEFAULT_MARITACA_MODEL = "sabia-4"

# All Marítaca models that expose chat completions + function calling.
# Used by the comparison runner to iterate.
KNOWN_MARITACA_MODELS = ("sabia-4", "sabiazinho-4", "sabia-3.1", "sabia-3", "sabiazinho-3")


class MaritacaLLM:
    provider: str = "maritaca"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        cache_dir: Path | None = None,
    ):
        key = api_key or os.environ.get("MARITACA_API_KEY")
        if not key:
            raise RuntimeError(
                "MARITACA_API_KEY not set. Add it to .env or pass api_key= explicitly."
            )
        self.client = OpenAI(api_key=key, base_url=MARITACA_BASE_URL)
        self.model = model or DEFAULT_MARITACA_MODEL
        self.name = self.model  # protocol field — alias
        # Phase 7.5.2: token usage from the most recent call, populated by
        # complete() and complete_structured(). Marítaca returns OpenAI-style
        # `usage` with `prompt_tokens` + `completion_tokens` — we map to
        # the same `input_tokens`/`output_tokens` shape as AnthropicLLM so
        # the caller sees a uniform schema across providers.
        self.last_call_usage: dict[str, int] | None = None
        # Phase 7.9 — opt-in filesystem cache (same mechanism as AnthropicLLM).
        self.cache_dir = cache_dir

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        if self.cache_dir is not None:
            key = llm_cache.cache_key(
                provider=self.provider, model=self.model,
                system=system, user=user, tool_schema=None,
                max_tokens=max_tokens, kind="complete",
            )
            hit = llm_cache.lookup(self.cache_dir, key)
            if hit is not None:
                response, usage = hit
                self.last_call_usage = usage
                return str(response)
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
        self.last_call_usage = _extract_usage(resp)
        text = resp.choices[0].message.content or ""
        if self.cache_dir is not None:
            llm_cache.store(
                cache_dir=self.cache_dir, key=key, kind="complete",
                provider=self.provider, model=self.model,
                response=text, usage=self.last_call_usage,
                key_inputs={"system": system, "user": user, "max_tokens": max_tokens},
            )
        return text

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
        if self.cache_dir is not None:
            key = llm_cache.cache_key(
                provider=self.provider, model=self.model,
                system=system, user=user, tool_schema=tool_schema,
                max_tokens=max_tokens, kind="structured",
            )
            hit = llm_cache.lookup(self.cache_dir, key)
            if hit is not None:
                response, usage = hit
                self.last_call_usage = usage
                return dict(response) if isinstance(response, dict) else {}
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
        self.last_call_usage = _extract_usage(resp)
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
            response = dict(json.loads(tc.function.arguments))
        except (json.JSONDecodeError, TypeError) as e:
            raise RuntimeError(
                f"Marítaca tool_call arguments not parseable as JSON: {tc.function.arguments!r}"
            ) from e
        if self.cache_dir is not None:
            llm_cache.store(
                cache_dir=self.cache_dir, key=key, kind="structured",
                provider=self.provider, model=self.model,
                response=response, usage=self.last_call_usage,
                key_inputs={
                    "system": system, "user": user,
                    "tool_name": tool_schema["name"],
                    "max_tokens": max_tokens,
                },
            )
        return response


def _extract_usage(resp: Any) -> dict[str, int] | None:
    """Pull token usage from an OpenAI-compatible response, mapped to the
    uniform `{input_tokens, output_tokens}` shape AnthropicLLM also uses.
    Returns None if the response object doesn't expose `usage` (some
    providers omit on streaming / partial responses)."""
    u = getattr(resp, "usage", None)
    if u is None:
        return None
    return {
        "input_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(u, "completion_tokens", 0) or 0,
    }


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
