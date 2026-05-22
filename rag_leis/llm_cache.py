"""Filesystem-backed cache for LLM responses.

Pays back on every eval iteration where the inputs (system prompt + user
message + tool schema + max_tokens) are identical to a previous run. The
canonical case is re-running the same eval after a non-LLM change (e.g.,
swapping a gate flag, adding a new aggregate field, fixing a bug in the
runner) — without caching, every re-run pays the full LLM bill.

Real-world example from this project: Phase 7.8.1 A/B'd Sabiá vs Opus
as the relevance-gate judge. Variant A (Sabiá) repeated calls already
made in Phase 7.8. Without caching, that ~$0.20 was paid twice.

Design constraints:

  - **Opt-in via cache_dir param on the LLM classes.** None = no
    caching (preserves existing behavior); a Path activates the cache.
    Production user-facing calls (each query is unique) leave it off;
    eval runners pass a project-level path.

  - **Hash the full call signature.** Missing any field that affects
    the response = silent false-hit = subtle bugs. We hash
    (provider, model, system, user, tool_schema, max_tokens, kind).

  - **Persist `last_call_usage` alongside the response.** Cost-folding
    in the pipeline reads token counts off the LLM instance after each
    call. The cache replays those counts on hit so cost reporting
    stays accurate.

  - **No auto-invalidation.** LLMs at temperature=0 should be
    deterministic; if they aren't (silent drift), I want the cache to
    pin one answer so I can compare. The only way to invalidate is to
    `rm` the file. Callers SHOULD only cache calls where temperature
    is 0 or unset; passing a non-zero temperature with caching gives
    you a single random sample frozen forever.

  - **Per-entry JSON files.** No SQLite, no LMDB. Easy to inspect,
    diff, and selectively delete. ~5KB per entry; a full eval suite
    cached is < 1MB.

Layout: `<cache_dir>/<sha256-of-key>.json` containing:
  {
    "kind": "complete" | "structured",
    "provider": "maritaca",
    "model": "sabia-4",
    "response": ...,           # str for complete, dict for structured
    "usage": {input_tokens, output_tokens},
    "cached_at": ISO timestamp,
    "key_inputs": {...}        # for debugging: shows what was hashed
  }

The on-disk file format intentionally includes the original key_inputs
(verbose but useful when debugging a "why did this cache?" question
months later). Storage cost is negligible.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

CacheKind = Literal["complete", "structured"]


def cache_key(
    *,
    provider: str,
    model: str,
    system: str,
    user: str,
    tool_schema: dict[str, Any] | None,
    max_tokens: int,
    kind: CacheKind,
) -> str:
    """Compute the canonical cache key for an LLM call.

    All inputs that can affect the response are part of the hash. We
    canonicalize the tool schema via JSON dump with sorted keys so dict
    iteration order doesn't produce different hashes for semantically
    identical schemas.

    The `kind` discriminator separates `complete` vs `complete_structured`
    so the same (system, user) pair sent to both call types doesn't
    collide.

    Temperature is intentionally OMITTED from the key. A non-zero
    temperature breaks the caching contract (responses become
    non-deterministic); we don't pretend to support that case. The
    cost of including temperature would be: someone iterates with
    temp=0.7 expecting variety, the cache pins the first sample, they
    get fooled. Better to make that breakage loud (single sample
    frozen) than subtle (different hash per call breaks the cache).
    """
    tool_blob = json.dumps(tool_schema, sort_keys=True, ensure_ascii=False) if tool_schema is not None else ""
    payload = "\x1f".join([  # \x1f = unit separator; not in normal text
        kind,
        provider,
        model,
        system,
        user,
        tool_blob,
        str(max_tokens),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lookup(
    cache_dir: Path, key: str
) -> tuple[Any, dict[str, int] | None] | None:
    """Return (response, usage) for a cached key, or None if absent/corrupt.

    Corruption (e.g., partial write from a crashed run) is treated as a
    miss. The next call will re-fetch and overwrite. We don't raise
    because the cache is a side channel — a broken entry shouldn't
    block the call.
    """
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        return entry["response"], entry.get("usage")
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def store(
    *,
    cache_dir: Path,
    key: str,
    kind: CacheKind,
    provider: str,
    model: str,
    response: Any,
    usage: dict[str, int] | None,
    key_inputs: dict[str, Any],
) -> None:
    """Persist a (response, usage) pair under `key`.

    Atomic-ish: writes to a tmp path then renames, so a crash mid-write
    can't produce a partial file that lookup() would mis-parse. (The
    `lookup` defensive try/except handles the residual corruption
    cases anyway.)
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "kind": kind,
        "provider": provider,
        "model": model,
        "response": response,
        "usage": usage,
        "cached_at": datetime.now(UTC).isoformat(),
        # Including the raw key inputs is verbose (~2-5KB per entry) but
        # invaluable when debugging "why did this hit?" months later.
        "key_inputs": key_inputs,
    }
    path = cache_dir / f"{key}.json"
    tmp = cache_dir / f"{key}.json.tmp"
    tmp.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
