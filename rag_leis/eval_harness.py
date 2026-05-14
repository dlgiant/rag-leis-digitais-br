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
    citation: str  # joined label chain ("Art. 7, I" / "Art. 18, § 2") — empty for top-level if label missing


@dataclass(frozen=True)
class Query:
    query: str
    core: frozenset[str]
    supporting: frozenset[str] = frozenset()
    qtype: str | None = None
    notes: str | None = None

    @property
    def relevant(self) -> frozenset[str]:
        # Union of graded levels — for binary metrics (recall, MRR) and back-compat.
        return self.core | self.supporting

    def relevance_of(self, urn: str) -> int:
        if urn in self.core:
            return 2
        if urn in self.supporting:
            return 1
        return 0


def load_chunks(chunks_dir: Path, min_text_chars: int = 10) -> list[IndexChunk]:
    """Load all chunks from `chunks_dir`, recursively.

    Accepts either a tier-specific dir (`data/chunks/tier-1`, legacy) or the
    chunks root (`data/chunks/`). Uses rglob so multi-tier layouts work
    transparently without callers touching paths.
    """
    # First pass: read all raw rows (before the empty-chunk filter) into a urn→row
    # map. We need the unfiltered set because a child's caput may itself be too
    # short to index (e.g. an artigo whose body is a colon and a list) but still
    # carries the parent context for its children.
    raw_by_urn: dict[str, dict[str, Any]] = {}
    for jsonl in sorted(chunks_dir.rglob("*.jsonl")):
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

    def _resolve_citation(obj: dict[str, Any]) -> str:
        """Join this chunk's label with its ancestors' labels, outermost-first.

        Output: "Art. 7, I" / "Art. 18, § 2, III" / "Art. 7" (top-level artigo).
        Empty for chunks without any label in the chain.
        """
        labels: list[str] = []
        doc_urn: str = obj["document_urn"]
        cur: dict[str, Any] | None = obj
        for _ in range(8):
            if cur is None:
                break
            lbl = cur.get("label")
            if lbl:
                labels.append(lbl)
            parent_part = cur.get("parent_partition")
            if not parent_part:
                break
            cur = raw_by_urn.get(f"{doc_urn}~{parent_part}")
        return ", ".join(reversed(labels))

    from rag_leis.chunks import is_revoked_text

    out: list[IndexChunk] = []
    for obj in raw_by_urn.values():
        # Skip placeholders (revogado/vetado/suprimido/stub). Prefer the explicit
        # `is_revoked` flag set at parse time; fall back to text-pattern detection
        # for JSONL written before the flag existed.
        if obj.get("is_revoked", False) or is_revoked_text(obj["text"]):
            continue
        nav = obj.get("nav") or {}
        nav_text = " > ".join(v for v in nav.values() if v)
        caput_text = _resolve_caput_chain(obj)
        citation = _resolve_citation(obj)
        out.append(
            IndexChunk(
                urn=obj["urn"],
                text=obj["text"],
                nav_text=nav_text,
                caput_text=caput_text,
                citation=citation,
            )
        )
    return out


def load_queries(path: Path) -> list[Query]:
    raw: list[dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[Query] = []
    for item in raw:
        rel = item["relevant"]
        if isinstance(rel, list):
            # v1 (binary) schema — flat URN list. All gold treated as core (rel=2).
            core = frozenset(rel)
            supporting: frozenset[str] = frozenset()
        else:
            core = frozenset(rel.get("core", []))
            supporting = frozenset(rel.get("supporting", []))
        out.append(
            Query(
                query=item["query"],
                core=core,
                supporting=supporting,
                qtype=item.get("type"),
                notes=item.get("notes"),
            )
        )
    return out


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
    if mode == "label+nav+caput+text":
        # Prefixes the chunk's citation chain ("Art. 7, I") so that literal
        # article references in queries have an explicit token to match.
        out = []
        for c in chunks:
            body = f"{c.caput_text} {c.text}".strip() if c.caput_text else c.text
            mid = f"{c.nav_text} :: {body}" if c.nav_text else body
            out.append(f"{c.citation} :: {mid}" if c.citation else mid)
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


def ndcg_at_k(
    retrieved: list[str],
    gold: frozenset[str] | dict[str, int] | Query,
    k: int,
) -> float:
    """Normalized DCG with graded relevance (2^rel - 1 gain).

    `gold` accepts three forms for caller convenience:
      * frozenset[str] (legacy): every URN is treated as rel=1 (gain=1) —
        reduces to the binary nDCG formula since the gain factor cancels in
        the DCG/IDCG ratio.
      * dict[str, int]: explicit URN→relevance-level mapping.
      * Query: uses Query.core (rel=2) and Query.supporting (rel=1).
    """
    if isinstance(gold, Query):
        rels: dict[str, int] = {urn: 2 for urn in gold.core}
        for urn in gold.supporting:
            rels.setdefault(urn, 1)
    elif isinstance(gold, frozenset):
        rels = {urn: 1 for urn in gold}
    else:
        rels = dict(gold)

    dcg = 0.0
    for i, urn in enumerate(retrieved[:k]):
        rel = rels.get(urn, 0)
        if rel > 0:
            dcg += (2**rel - 1) / math.log2(i + 2)

    ideal = sorted(rels.values(), reverse=True)[:k]
    idcg = sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(ideal) if rel > 0)
    return dcg / idcg if idcg > 0 else 0.0


def mrr_at_k(retrieved: list[str], relevant: frozenset[str], k: int) -> float:
    for i, r in enumerate(retrieved[:k]):
        if r in relevant:
            return 1.0 / (i + 1)
    return 0.0
