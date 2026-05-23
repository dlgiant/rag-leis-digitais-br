"""Marítaca AI LLM adapter — Sabiá family, BR-resident.

Implements the `LLM` Protocol from rag_leis.llm. Uses the OpenAI-compatible
endpoint at `chat.maritaca.ai/api`, so we ride on the openai SDK.

Why this exists: D9 (LGPD data residency) — Anthropic doesn't host in BR.
Marítaca is São Paulo-based and Sabiá is fine-tuned for Portuguese.
Phase 4.0 benchmark compared against Anthropic on the project's
answer-eval to make D9 a data-driven decision. Phase 8.0.1 (2026-05-19)
then A/B'd Sabiá-3.1 vs Sabiá-4 and swapped production to Sabiá-4 (key
fix: row 12 / Decreto 8.771 false-refusal). Sabiá-3.x is now being
deprecated by Marítaca and has been removed from `KNOWN_MARITACA_MODELS`
below.

Critical contract decision: tool_choice forcing.

  Anthropic: `tool_choice={"type": "tool", "name": ...}` is enforced
  by the SDK + server side. Returned `tool_use` block is validated
  against `input_schema`.

  Marítaca / OpenAI-compatible: `tool_choice={"type": "function",
  "function": {"name": ...}}` is the analogue. As of 2026-05-15
  smoke tests (commit context), the Sabiá-4 family honors this and
  returns parseable JSON in `tool_calls[0].function.arguments`.

  Phase 17.4 added a complete()+JSON-mode fallback for the three
  failure surfaces (no tool_call / wrong tool name / invalid JSON
  arguments) — see `complete_structured` for the retry path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from rag_leis import llm_cache, obs
from rag_leis.llm import _build_fallback_prompt, _parse_fallback_json

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
# Used by the comparison runner to iterate. The Sabiá-3 family
# (sabia-3, sabia-3.1, sabiazinho-3) was removed in 2026-05-22 after
# Marítaca announced deprecation — they would error at runtime once the
# endpoints sunset, so keeping them as iteration targets would just burn
# budget on doomed calls. Historical cost rates remain in cost.py so
# eval cache lookups can still attribute spend to old runs.
KNOWN_MARITACA_MODELS = ("sabia-4", "sabiazinho-4")


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
        # Phase 17.4 — see rag_leis.llm.AnthropicLLM for the contract.
        # Set True iff this provider had to fall back from tool-use to
        # complete()+JSON-parse. The benchmark stance from the module
        # docstring ("don't retry on parse failure here") is reversed
        # in 17.4: production resilience matters more than honest
        # benchmark surface — the failure rate is still visible via
        # the structured `llm.tool_use_fallback` log event.
        self.last_call_used_fallback: bool = False

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

        Phase 17.4 — when the function-call path fails (no tool_call,
        wrong tool, JSON parse error), retry ONCE via complete()+JSON
        parse with a fallback prompt. Resilience > benchmark honesty
        for production reliability; the underlying failure rate is
        still observable via structured `llm.tool_use_fallback` logs.
        """
        self.last_call_used_fallback = False
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
        # Phase 17.4 — three failure surfaces are folded into a single
        # fallback retry: (1) no tool_calls returned, (2) wrong tool
        # name, (3) JSON parse error on arguments. All three are
        # recoverable via the complete()+JSON-mode fallback below.
        fallback_reason: str | None = None
        response: dict[str, Any] | None = None
        if not msg.tool_calls:
            fallback_reason = (
                f"no tool_call returned (finish_reason="
                f"{resp.choices[0].finish_reason!r}, content={msg.content!r})"
            )
        else:
            tc = msg.tool_calls[0]
            if tc.function.name != tool_schema["name"]:
                fallback_reason = (
                    f"wrong tool name returned ({tc.function.name!r} vs "
                    f"expected {tool_schema['name']!r})"
                )
            else:
                try:
                    response = dict(json.loads(tc.function.arguments))
                except (json.JSONDecodeError, TypeError):
                    fallback_reason = (
                        f"tool_call arguments not parseable as JSON: "
                        f"{tc.function.arguments!r}"
                    )

        if response is None:
            assert fallback_reason is not None
            primary_input = (self.last_call_usage or {}).get("input_tokens", 0)
            primary_output = (self.last_call_usage or {}).get("output_tokens", 0)
            fallback_text = self.complete(
                system=system,
                user=_build_fallback_prompt(tool_schema, user),
                max_tokens=max_tokens,
                temperature=temperature,
            )
            fallback_input = (self.last_call_usage or {}).get("input_tokens", 0)
            fallback_output = (self.last_call_usage or {}).get("output_tokens", 0)
            self.last_call_usage = {
                "input_tokens": primary_input + fallback_input,
                "output_tokens": primary_output + fallback_output,
            }
            try:
                response = _parse_fallback_json(fallback_text)
            except RuntimeError as err:
                # Both paths failed — combine signals.
                raise RuntimeError(
                    f"Marítaca tool_use failed ({fallback_reason}); "
                    f"fallback complete()+JSON also failed: {fallback_text!r}"
                ) from err
            self.last_call_used_fallback = True
            obs.get_logger().info(
                "llm.tool_use_fallback",
                provider=self.provider,
                model=self.model,
                tool_name=tool_schema["name"],
                primary_failure=fallback_reason,
                fallback_input_tokens=fallback_input,
                fallback_output_tokens=fallback_output,
            )

        if self.cache_dir is not None:
            llm_cache.store(
                cache_dir=self.cache_dir, key=key, kind="structured",
                provider=self.provider, model=self.model,
                response=response, usage=self.last_call_usage,
                key_inputs={
                    "system": system, "user": user,
                    "tool_name": tool_schema["name"],
                    "max_tokens": max_tokens,
                    "fallback": self.last_call_used_fallback,
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
