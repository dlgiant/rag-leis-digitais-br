"""Phase 7.9 — tests for the LLM-response cache module.

The cache lives outside the LLM classes, so it's testable without any
network. Focus areas:

- Key determinism: same inputs → same key; any field changed → different key.
  Silent collisions are the worst failure mode (false hits = wrong cached
  response served).
- Defensive corruption handling: a partially-written or hand-edited file
  must not crash the lookup — it just becomes a miss.
- Round-trip: store then lookup returns what we put in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_leis import llm_cache

# ----------------------------------------------------------------------------
# Key determinism
# ----------------------------------------------------------------------------


def _base_args() -> dict:
    return dict(
        provider="maritaca",
        model="sabia-3.1",
        system="you are a helpful assistant",
        user="what is LGPD?",
        tool_schema=None,
        max_tokens=1024,
        kind="complete",
    )


def test_identical_args_produce_identical_key():
    """Sanity: this is the cache-hit case. Without it, no caching works."""
    k1 = llm_cache.cache_key(**_base_args())
    k2 = llm_cache.cache_key(**_base_args())
    assert k1 == k2


def test_key_is_sha256_hex():
    """64-char hex string — the file-name format the on-disk cache expects."""
    k = llm_cache.cache_key(**_base_args())
    assert len(k) == 64
    assert all(c in "0123456789abcdef" for c in k)


@pytest.mark.parametrize("field, new_value", [
    ("provider", "anthropic"),
    ("model", "sabia-3"),
    ("system", "you are a different assistant"),
    ("user", "what is MCI?"),
    ("max_tokens", 2048),
    ("kind", "structured"),
])
def test_any_field_change_produces_different_key(field, new_value):
    """Hard constraint: every input that affects the LLM response is part
    of the hash. A change in any one of these must produce a different
    key, otherwise we'd serve the wrong cached response."""
    base = _base_args()
    base_key = llm_cache.cache_key(**base)
    base[field] = new_value
    new_key = llm_cache.cache_key(**base)
    assert base_key != new_key, f"changing {field} did not change the key — false hits possible"


def test_tool_schema_dict_order_does_not_affect_key():
    """Schema dicts can be built in any key order; the JSON canonical
    form ensures the hash is invariant. Catches a real bug where
    `{a: 1, b: 2}` and `{b: 2, a: 1}` would have hashed differently."""
    args = _base_args()
    args["tool_schema"] = {"name": "foo", "input_schema": {"properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}}
    args["kind"] = "structured"
    k1 = llm_cache.cache_key(**args)
    # Same schema, different insertion order — should produce same key.
    args["tool_schema"] = {"input_schema": {"properties": {"b": {"type": "integer"}, "a": {"type": "string"}}}, "name": "foo"}
    k2 = llm_cache.cache_key(**args)
    assert k1 == k2


def test_tool_schema_None_vs_empty_dict_differ():
    """None tool_schema (complete) vs {} tool_schema (structured with empty
    schema) are semantically different. Hash must differ."""
    args = _base_args()
    k_none = llm_cache.cache_key(**args)
    args["tool_schema"] = {}
    args["kind"] = "structured"
    k_empty = llm_cache.cache_key(**args)
    assert k_none != k_empty


# ----------------------------------------------------------------------------
# Round-trip: store + lookup
# ----------------------------------------------------------------------------


def test_store_then_lookup_returns_response_and_usage(tmp_path: Path):
    """The basic contract: what goes in comes out."""
    key = "test-key-001"
    llm_cache.store(
        cache_dir=tmp_path, key=key, kind="structured",
        provider="anthropic", model="opus-4-7",
        response={"score": 5, "reasoning": "looks good"},
        usage={"input_tokens": 100, "output_tokens": 20},
        key_inputs={"system": "judge", "user": "...", "tool_name": "rate", "max_tokens": 512},
    )
    hit = llm_cache.lookup(tmp_path, key)
    assert hit is not None
    response, usage = hit
    assert response == {"score": 5, "reasoning": "looks good"}
    assert usage == {"input_tokens": 100, "output_tokens": 20}


def test_lookup_missing_key_returns_None(tmp_path: Path):
    """Cache miss is expected behavior, not an error."""
    assert llm_cache.lookup(tmp_path, "does-not-exist") is None


def test_lookup_corrupt_file_returns_None(tmp_path: Path):
    """A corrupted JSON file shouldn't crash the pipeline — the cache is
    a side channel. Treat as miss; the next call refetches + overwrites."""
    key = "corrupt-key"
    (tmp_path / f"{key}.json").write_text("{not valid json", encoding="utf-8")
    assert llm_cache.lookup(tmp_path, key) is None


def test_lookup_missing_response_field_returns_None(tmp_path: Path):
    """Defensive: a file missing the `response` key (shouldn't happen, but
    if a write was interrupted) shouldn't crash."""
    key = "incomplete-key"
    (tmp_path / f"{key}.json").write_text(json.dumps({"usage": {}}), encoding="utf-8")
    assert llm_cache.lookup(tmp_path, key) is None


def test_store_overwrites_existing_entry(tmp_path: Path):
    """If a key is stored twice, the second write wins. Useful when
    re-fetching after a cache-corruption miss."""
    key = "overwrite-test"
    llm_cache.store(
        cache_dir=tmp_path, key=key, kind="complete",
        provider="maritaca", model="sabia-3.1",
        response="first answer",
        usage={"input_tokens": 10, "output_tokens": 5},
        key_inputs={"system": "s", "user": "u", "max_tokens": 100},
    )
    llm_cache.store(
        cache_dir=tmp_path, key=key, kind="complete",
        provider="maritaca", model="sabia-3.1",
        response="second answer",
        usage={"input_tokens": 11, "output_tokens": 6},
        key_inputs={"system": "s", "user": "u", "max_tokens": 100},
    )
    hit = llm_cache.lookup(tmp_path, key)
    assert hit is not None
    response, usage = hit
    assert response == "second answer"
    assert usage == {"input_tokens": 11, "output_tokens": 6}


def test_store_creates_cache_dir_if_missing(tmp_path: Path):
    """Defensive: the cache dir may not exist on first run. store()
    should create it rather than crash."""
    sub = tmp_path / "deeper" / "still-deeper"
    assert not sub.exists()
    llm_cache.store(
        cache_dir=sub, key="autocreate-test", kind="complete",
        provider="anthropic", model="opus-4-7",
        response="ok",
        usage=None,
        key_inputs={},
    )
    assert sub.exists()
    assert (sub / "autocreate-test.json").exists()


def test_store_persists_usage_None(tmp_path: Path):
    """Some providers omit usage on streaming/partial responses. The cache
    must round-trip None correctly (not crash, not convert to {})."""
    llm_cache.store(
        cache_dir=tmp_path, key="usage-none", kind="complete",
        provider="x", model="y",
        response="text",
        usage=None,
        key_inputs={},
    )
    hit = llm_cache.lookup(tmp_path, "usage-none")
    assert hit is not None
    response, usage = hit
    assert response == "text"
    assert usage is None


# ----------------------------------------------------------------------------
# File-format inspection (the verbose key_inputs payload)
# ----------------------------------------------------------------------------


def test_stored_file_includes_key_inputs_for_debugging(tmp_path: Path):
    """On-disk entries record the raw key inputs as a debugging aid.
    A future "why did this cache?" question can be answered by reading
    the file."""
    key = "debug-aid"
    inputs = {"system": "judge", "user": "long prompt here", "max_tokens": 512}
    llm_cache.store(
        cache_dir=tmp_path, key=key, kind="complete",
        provider="anthropic", model="opus-4-7",
        response="ok",
        usage=None,
        key_inputs=inputs,
    )
    raw = json.loads((tmp_path / f"{key}.json").read_text(encoding="utf-8"))
    assert raw["key_inputs"] == inputs
    assert "cached_at" in raw  # ISO timestamp present
