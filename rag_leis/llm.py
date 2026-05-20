"""LLM provider abstraction for the RAG pipeline.

The pipeline talks to LLMs through the `LLM` Protocol (mirrors the
`Embedder` pattern in rag_leis.embeddings). One protocol, multiple
provider impls — currently `AnthropicLLM`; Phase 4.0 adds `MaritacaLLM`
for the LGPD-residency comparison; future Phase 7.4 may add Bedrock or
self-hosted impls for fallback.

Two surfaces every impl must support:

* `complete()` — free-form text completion (used by the faithfulness judge).
* `complete_structured()` — emit JSON matching the supplied tool/function
  schema. Anthropic forces this via `tool_choice`; OpenAI-compatible
  providers via `tool_choice={"type": "function", ...}` or function-call
  forcing. The contract from the pipeline's perspective is that the
  returned dict matches the tool's `input_schema`.

Keys come from `.env` via python-dotenv. Models hard-coded as defaults
but overridable per-instance.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from anthropic import Anthropic
from anthropic.types import TextBlock, ToolUseBlock
from dotenv import load_dotenv

from rag_leis import llm_cache

load_dotenv()


DEFAULT_GENERATOR_MODEL = "claude-sonnet-4-5"
DEFAULT_JUDGE_MODEL = "claude-opus-4-7"


@runtime_checkable
class LLM(Protocol):
    """Provider-agnostic LLM interface.

    Concrete impls expose `name` (model identifier — e.g., "claude-sonnet-4-5",
    "sabia-3") and `provider` (vendor — e.g., "anthropic", "maritaca") for
    logging, cost attribution, and per-provider fallback decisions.

    `complete_structured` must return a dict that matches the supplied
    `tool_schema["input_schema"]`. If the underlying provider can't force
    the schema (e.g., JSON mode without strict validation), the impl is
    expected to retry or raise — never return a partial / invalid dict.
    """

    name: str
    provider: str

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str: ...

    def complete_structured(
        self,
        system: str,
        user: str,
        tool_schema: dict[str, Any],
        max_tokens: int = 2048,
        temperature: float | None = None,
    ) -> dict[str, Any]: ...


class AnthropicLLM:
    provider: str = "anthropic"

    def __init__(
        self,
        model: str = DEFAULT_GENERATOR_MODEL,
        api_key: str | None = None,
        cache_dir: Path | None = None,
    ):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env or pass api_key= explicitly."
            )
        self.client = Anthropic(api_key=key)
        self.model = model
        self.name = model  # protocol field — alias of model for callers
        # Phase 7.5.2: token usage from the most recent call, populated by
        # complete() and complete_structured(). Pipeline reads after each
        # call to attribute cost. Reset to None before each call to detect
        # "did the LLM actually report usage?"
        self.last_call_usage: dict[str, int] | None = None
        # Phase 7.9 — opt-in filesystem cache. None = no caching (existing
        # behavior preserved). A Path activates the cache for both complete()
        # and complete_structured(). See rag_leis.llm_cache module docstring.
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
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        # opus-4-7 deprecated `temperature`; only pass it when the caller
        # explicitly sets a value (sonnet-4-5 etc. still accept it).
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = self.client.messages.create(**kwargs)
        self.last_call_usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
        # Pull all text blocks (typically one) and join — tool blocks shouldn't
        # appear here since we didn't pass `tools=`.
        parts = [b.text for b in resp.content if isinstance(b, TextBlock)]
        text = "".join(parts)
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
        """Force the model to respond via the named tool.

        Returns the tool-call's `input` dict — validated by Anthropic against
        the supplied `input_schema`. Raises `RuntimeError` if no tool block
        comes back (shouldn't happen with `tool_choice`, but we guard).
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
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [tool_schema],
            "tool_choice": {"type": "tool", "name": tool_schema["name"]},
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = self.client.messages.create(**kwargs)
        self.last_call_usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
        for block in resp.content:
            if isinstance(block, ToolUseBlock) and block.name == tool_schema["name"]:
                # block.input is already a parsed dict (Anthropic SDK validates).
                response = dict(block.input) if isinstance(block.input, dict) else {}
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
        raise RuntimeError(
            f"LLM did not return a tool_use block for {tool_schema['name']!r}; "
            f"stop_reason={resp.stop_reason!r}"
        )


def get_llm(
    provider: str = "anthropic",
    model: str | None = None,
    cache_dir: Path | None = None,
) -> LLM:
    """Factory: construct an LLM by provider name.

    `model=None` uses each provider's default generator model. Use
    DEFAULT_JUDGE_MODEL etc. directly when you need a non-default.

    `cache_dir=None` (default) disables LLM-response caching. Pass a
    Path to activate filesystem caching (see rag_leis.llm_cache). Eval
    runners typically pass `data/cache/llm` to amortize the cost of
    re-runs with unchanged inputs.
    """
    if provider == "anthropic":
        return AnthropicLLM(model=model or DEFAULT_GENERATOR_MODEL, cache_dir=cache_dir)
    if provider == "maritaca":
        # Imported lazily so callers without openai installed can still
        # use the Anthropic path.
        from rag_leis.maritaca import MaritacaLLM

        return MaritacaLLM(model=model, cache_dir=cache_dir)
    raise ValueError(f"Unknown LLM provider: {provider!r}. Known: anthropic, maritaca.")
