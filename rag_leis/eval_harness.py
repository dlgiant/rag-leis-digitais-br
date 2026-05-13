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


@dataclass(frozen=True)
class Query:
    query: str
    relevant: frozenset[str]
    notes: str | None = None


def load_chunks(chunks_dir: Path, min_text_chars: int = 10) -> list[IndexChunk]:
    out: list[IndexChunk] = []
    for jsonl in sorted(chunks_dir.glob("*.jsonl")):
        with jsonl.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj: dict[str, Any] = json.loads(line)
                # Skip revoked/empty chunks (e.g. art7;par1 with text=".").
                if len(obj["text"].strip(". ")) < min_text_chars:
                    continue
                nav = obj.get("nav") or {}
                nav_text = " > ".join(v for v in nav.values() if v)
                out.append(IndexChunk(urn=obj["urn"], text=obj["text"], nav_text=nav_text))
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
