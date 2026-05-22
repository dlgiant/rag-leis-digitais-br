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

Keys come from `os.environ` — callers MUST load `.env` themselves at
entry-point time (server lifespan, eval CLI top, test conftest).
Module-import-time `load_dotenv()` used to live here (Phase 4.0
through 17.2) but was removed in Phase 17.3 because the side effect
of populating env vars on lazy module import broke test isolation:
the three Clerk-auth test files needed `monkeypatch.setenv("CLERK_AUDIENCE", "")`
instead of `delenv` because a later transitive `import rag_leis.llm`
would repopulate cleared keys mid-test. Centralizing dotenv loading
at entry points + adding `tests/conftest.py` removes that fragility.

Models hard-coded as defaults but overridable per-instance.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from anthropic import Anthropic
from anthropic.types import TextBlock, ToolUseBlock

from rag_leis import llm_cache, obs


def _build_fallback_prompt(tool_schema: dict[str, Any], original_user: str) -> str:
    """Phase 17.4 — construct the JSON-mode fallback prompt.

    When the tool-use path fails (provider returned no tool block, or
    returned a parse-error JSON in the OpenAI-compatible path), we
    retry via free-form `complete()` asking the model to output JSON
    matching the schema. The prompt embeds the tool's name + input
    schema verbatim so the model has the same target as the tool path.

    The instruction wording is critical: "ONLY a JSON object" (not
    "respond with JSON") + "no markdown fences" — both common
    failure modes when models default to chat-style formatting.
    """
    schema_str = json.dumps(tool_schema.get("input_schema", {}), indent=2)
    return (
        f"{original_user}\n\n"
        f"---\n\n"
        f"INSTRUÇÃO TÉCNICA (fallback): a chamada `tool_use` falhou. "
        f"Responda agora APENAS com um objeto JSON válido que satisfaça "
        f"o seguinte schema:\n\n"
        f"```\n{schema_str}\n```\n\n"
        f"Sem texto explicativo, sem ```json fences, sem prefixo/sufixo. "
        f"Apenas o objeto JSON puro, começando com `{{` e terminando com `}}`."
    )


def _parse_fallback_json(text: str) -> dict[str, Any]:
    """Extract + parse JSON from a free-form completion.

    Models routinely wrap JSON in markdown code fences or prefix it
    with "Aqui está o JSON:" despite instructions to the contrary.
    Strip the most common shapes before attempting to parse. Raises
    `RuntimeError` (matching the existing `complete_structured`
    failure surface) if no valid JSON found.
    """
    stripped = text.strip()
    # Drop ```json … ``` and ``` … ``` fences.
    fence_re = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)
    m = fence_re.match(stripped)
    if m:
        stripped = m.group(1).strip()
    # If the model prepended prose, find the first `{` and try to parse
    # the balanced JSON object starting there.
    if not stripped.startswith("{"):
        idx = stripped.find("{")
        if idx == -1:
            raise RuntimeError(
                f"fallback completion contained no JSON object: {text!r}"
            )
        stripped = stripped[idx:]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"fallback completion JSON parse failed: {e}; text was {text!r}"
        ) from e
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"fallback completion JSON was not an object (got {type(parsed).__name__}): {text!r}"
        )
    return parsed


DEFAULT_GENERATOR_MODEL = "claude-sonnet-4-5"
DEFAULT_JUDGE_MODEL = "claude-opus-4-7"


@runtime_checkable
class LLM(Protocol):
    """Provider-agnostic LLM interface.

    Concrete impls expose `name` (model identifier — e.g., "claude-sonnet-4-5",
    "sabia-4") and `provider` (vendor — e.g., "anthropic", "maritaca") for
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
        # Phase 17.4 — set to True by the most recent `complete_structured`
        # call IFF it had to fall back to the `complete`+JSON-parse path
        # because the tool-use response was empty/malformed. Reset to
        # False at the top of each `complete_structured` call. Read by
        # RAGPipeline.answer to bump RAGAnswer.tool_use_fallback_count.
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
        the supplied `input_schema`.

        Phase 17.4 — provider-aware tool-use retry. If the primary
        tool-use call returns no tool block (e.g., the model refused
        or the SDK contract drifted), retry ONCE via `complete()` with
        a JSON-mode prompt that embeds the tool's input schema. On
        fallback success, set `self.last_call_used_fallback = True`
        and emit `llm.tool_use_fallback` to structured logs so
        downstream aggregators can compute the fallback rate. Both
        paths fail → raise the original RuntimeError.
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
        # Phase 17.4 — tool-use missing. Retry once via complete()+JSON
        # parse. Tokens from the fallback call OVERWRITE last_call_usage
        # so cost attribution stays honest (the failed primary call's
        # tokens are still in last_call_usage at this point, but the
        # fallback call's resp.usage above is what we report — the
        # primary call DID happen and DID consume tokens; for the
        # purposes of per-pipeline cost we sum both calls. Sum logic
        # lives in the next-call wrapper below).
        primary_input = self.last_call_usage.get("input_tokens", 0)
        primary_output = self.last_call_usage.get("output_tokens", 0)
        fallback_text = self.complete(
            system=system,
            user=_build_fallback_prompt(tool_schema, user),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        # complete() set last_call_usage to the fallback's tokens.
        fallback_input = (self.last_call_usage or {}).get("input_tokens", 0)
        fallback_output = (self.last_call_usage or {}).get("output_tokens", 0)
        # Total tokens for this complete_structured call = primary + fallback.
        # Cost attribution reflects the full retry; an operator looking at
        # `cost_estimate_usd` sees the true spend.
        self.last_call_usage = {
            "input_tokens": primary_input + fallback_input,
            "output_tokens": primary_output + fallback_output,
        }
        try:
            response = _parse_fallback_json(fallback_text)
        except RuntimeError:
            # Both paths failed — surface the original signal so the
            # operator sees that the primary tool-use returned nothing
            # AND the fallback couldn't be parsed.
            raise RuntimeError(
                f"LLM did not return a tool_use block for {tool_schema['name']!r}; "
                f"stop_reason={resp.stop_reason!r}. Fallback complete()+JSON "
                f"also failed to parse: {fallback_text!r}"
            )
        self.last_call_used_fallback = True
        obs.get_logger().info(
            "llm.tool_use_fallback",
            provider=self.provider,
            model=self.model,
            tool_name=tool_schema["name"],
            primary_stop_reason=str(resp.stop_reason),
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
                    "fallback": True,
                },
            )
        return response


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
