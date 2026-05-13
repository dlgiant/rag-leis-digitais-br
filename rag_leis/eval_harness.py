from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from rag_leis.embeddings import Embedder, Vec


@dataclass(frozen=True)
class IndexChunk:
    urn: str
    text: str
    nav_text: str
    caput_text: str  # concatenation of all ancestor caput texts (artigo→…→parent), "" for top-level chunks


@dataclass(frozen=True)
class Query:
    query: str
    relevant: frozenset[str]
    notes: str | None = None


def load_chunks(chunks_dir: Path, min_text_chars: int = 10) -> list[IndexChunk]:
    # First pass: read all raw rows (before the empty-chunk filter) into a urn→row
    # map. We need the unfiltered set because a child's caput may itself be too
    # short to index (e.g. an artigo whose body is a colon and a list) but still
    # carries the parent context for its children.
    raw_by_urn: dict[str, dict[str, Any]] = {}
    for jsonl in sorted(chunks_dir.glob("*.jsonl")):
        with jsonl.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                raw_by_urn[obj["urn"]] = obj

    def _resolve_caput_chain(obj: dict[str, Any]) -> str:
        parent_part = obj.get("parent_partition")
        if not parent_part:
            return ""
        parts: list[str] = []
        doc_urn: str = obj["document_urn"]
        cur_part: str | None = parent_part
        # Walk up; cap at 8 levels as a safety net (artigo→§→inciso→alínea→item is 5).
        for _ in range(8):
            if cur_part is None:
                break
            parent_urn = f"{doc_urn}~{cur_part}"
            parent = raw_by_urn.get(parent_urn)
            if parent is None:
                break
            parts.append(parent["text"])
            cur_part = parent.get("parent_partition")
        # Outermost (artigo caput) first → innermost last, matching reading order.
        return " ".join(reversed(parts))

    out: list[IndexChunk] = []
    for obj in raw_by_urn.values():
        # Skip revoked/empty chunks (e.g. art7;par1 with text=".").
        if len(obj["text"].strip(". ")) < min_text_chars:
            continue
        nav = obj.get("nav") or {}
        nav_text = " > ".join(v for v in nav.values() if v)
        caput_text = _resolve_caput_chain(obj)
        out.append(
            IndexChunk(
                urn=obj["urn"], text=obj["text"], nav_text=nav_text, caput_text=caput_text
            )
        )
    return out


def load_queries(path: Path) -> list[Query]:
    raw: list[dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Query(
            query=item["query"],
            relevant=frozenset(item["relevant"]),
            notes=item.get("notes"),
        )
        for item in raw
    ]


def format_texts(chunks: list[IndexChunk], mode: str) -> list[str]:
    if mode == "text":
        return [c.text for c in chunks]
    if mode == "nav+text":
        return [f"{c.nav_text} :: {c.text}" if c.nav_text else c.text for c in chunks]
    if mode == "caput+text":
        return [f"{c.caput_text} {c.text}".strip() if c.caput_text else c.text for c in chunks]
    if mode == "nav+caput+text":
        out: list[str] = []
        for c in chunks:
            body = f"{c.caput_text} {c.text}".strip() if c.caput_text else c.text
            out.append(f"{c.nav_text} :: {body}" if c.nav_text else body)
        return out
    raise ValueError(f"Unknown text mode: {mode!r}")


def build_index(
    chunks: list[IndexChunk], embedder: Embedder, mode: str = "text"
) -> tuple[list[str], Vec]:
    texts = format_texts(chunks, mode)
    vecs = embedder.embed_docs(texts)
    urns = [c.urn for c in chunks]
    return urns, vecs


def search(query_vec: Vec, doc_vecs: Vec, k: int) -> list[int]:
    # Vectors are L2-normalized at index time → dot product = cosine similarity.
    sims = doc_vecs @ query_vec
    return list(np.argsort(-sims)[:k])


def recall_at_k(retrieved: list[str], relevant: frozenset[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for r in retrieved[:k] if r in relevant)
    return hits / len(relevant)


def ndcg_at_k(retrieved: list[str], relevant: frozenset[str], k: int) -> float:
    dcg = 0.0
    for i, r in enumerate(retrieved[:k]):
        if r in relevant:
            dcg += 1.0 / math.log2(i + 2)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


def mrr_at_k(retrieved: list[str], relevant: frozenset[str], k: int) -> float:
    for i, r in enumerate(retrieved[:k]):
        if r in relevant:
            return 1.0 / (i + 1)
    return 0.0
