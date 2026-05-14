"""Embedding cache with content-hash validation.

The `.npz` cache files were keyed only by `(model, text_mode)`. When the
corpus changed (re-parse, new Tier, gold-prefix tweak, caput-resolution fix)
the file path stayed the same and `np.load` silently returned stale vectors
misaligned with the current chunk set.

This module adds a sidecar `.meta.json` next to each `.npz`. The meta carries
a SHA-256 hash of the actual embedded surface forms (`format_texts(chunks,
mode)`), so any change to the corpus, the formatting logic, or the chunk
contents invalidates the cache automatically.

Sidecar layout:

    data/index/voyage-3-large__label+nav+caput+text.npz
    data/index/voyage-3-large__label+nav+caput+text.meta.json

The meta also records `n_chunks` for fast eyeball checks; the hash is what
gates correctness.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def texts_hash(texts: list[str]) -> str:
    """SHA-256 over the embedded surface forms, hex-digested.

    Hashing the formatted texts (not raw chunks) catches every relevant
    change: corpus expansion, chunk edits, caput-resolution algorithm
    updates, nav-text rewording, label-prefix introduction, etc. If two
    cache builds produce the same `texts` list, they're embedding the same
    inputs — regardless of the chunks list's path or shape.
    """
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\0")  # length-independent separator
    return h.hexdigest()


def meta_path(npz_path: Path) -> Path:
    return npz_path.with_suffix(".meta.json")


def read_meta(npz_path: Path) -> dict[str, Any] | None:
    p = meta_path(npz_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_meta(npz_path: Path, *, content_hash: str, n_chunks: int, **extra: Any) -> None:
    meta_path(npz_path).write_text(
        json.dumps(
            {"content_hash": content_hash, "n_chunks": n_chunks, **extra},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def cache_is_fresh(npz_path: Path, expected_hash: str) -> bool:
    """True if both the npz and a matching meta sidecar exist with the right hash.

    Conservative: missing meta is treated as stale (fail closed). This means
    pre-existing `.npz` files without sidecars rebuild on first read after
    this module is wired up — which is the intended migration behavior.
    """
    if not npz_path.exists():
        return False
    meta = read_meta(npz_path)
    if meta is None:
        return False
    return meta.get("content_hash") == expected_hash
