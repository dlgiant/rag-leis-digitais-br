"""Phase 11.0 — eval-set loader for the admin API.

Wraps `rag_leis.eval_harness.load_queries()` and adds:
  - Stable per-row IDs (SHA-256 prefix of the query string).
  - Chunk-text expansion for gold URNs (so the admin UI can show the
    chunk content without separate lookups).

The IDs are stable across YAML reorderings — same query text always
maps to the same ID, even if the YAML row order changes. That
matters because the lawyer-review UI persists proposals keyed by ID
to `data/review/proposals.jsonl`; if IDs were positional, a reorder
would silently break those references.

IDs are NOT stable across query-text edits. If the lawyer suggests
a query rewrite and the operator accepts it, the row's ID changes.
That's the right behavior: the new query is semantically a different
row from the old one.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from rag_leis.eval_harness import IndexChunk, Query, load_chunks, load_queries

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_PATH = PROJECT_ROOT / "eval" / "queries.yaml"
DEFAULT_CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"


@dataclass(frozen=True)
class EvalQueryRow:
    """A single eval row, enriched with a stable ID for the admin UI."""

    id: str
    query: str
    qtype: str | None
    core_urns: tuple[str, ...]
    supporting_urns: tuple[str, ...]
    notes: str | None


@dataclass(frozen=True)
class ChunkSummary:
    """A chunk's text + structural metadata, for the admin UI."""

    urn: str
    document_urn: str
    label: str  # joined citation chain, e.g., "Art. 7, I"
    nav: str  # navigation breadcrumb (capitulo/titulo/livro hierarchy)
    caput: str | None  # text of the parent caput, if any
    text: str
    kind: str  # artigo / paragrafo / inciso / alinea (derived from URN)


# ---------------------------------------------------------------------------
# ID derivation
# ---------------------------------------------------------------------------


def query_id(query_text: str) -> str:
    """SHA-256 prefix of the query string, normalized.

    Normalization: strip + lowercase. This means "Foo bar  " and "foo bar"
    map to the same ID. Doesn't strip accents — the lawyer can correct
    accent typos and that DOES change the ID (correct semantically).
    """
    normalized = query_text.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _row_from_query(q: Query) -> EvalQueryRow:
    return EvalQueryRow(
        id=query_id(q.query),
        query=q.query,
        qtype=q.qtype,
        core_urns=tuple(sorted(q.core)),
        supporting_urns=tuple(sorted(q.supporting)),
        notes=q.notes,
    )


def load_eval_queries(path: Path | None = None) -> list[EvalQueryRow]:
    """Load eval/queries.yaml into a list of EvalQueryRow.

    Order preserved from the YAML; IDs are content-derived so reordering
    the YAML doesn't change them.
    """
    p = path or DEFAULT_EVAL_PATH
    queries = load_queries(p)
    return [_row_from_query(q) for q in queries]


# ---------------------------------------------------------------------------
# Chunk lookups
# ---------------------------------------------------------------------------


_chunks_cache: dict[str, IndexChunk] | None = None


def _build_chunks_index(chunks_dir: Path) -> dict[str, IndexChunk]:
    """Build a URN→IndexChunk dict from the gitignored chunk files."""
    chunks = load_chunks(chunks_dir)
    return {c.urn: c for c in chunks}


def _ensure_chunks_loaded(chunks_dir: Path) -> dict[str, IndexChunk]:
    """Lazy-load chunks the first time a lookup happens; cache for reuse."""
    global _chunks_cache
    if _chunks_cache is None:
        _chunks_cache = _build_chunks_index(chunks_dir)
    return _chunks_cache


def get_chunk(urn: str, chunks_dir: Path | None = None) -> ChunkSummary | None:
    """Return a ChunkSummary for the given URN, or None if not in corpus."""
    d = chunks_dir or DEFAULT_CHUNKS_DIR
    index = _ensure_chunks_loaded(d)
    c = index.get(urn)
    if c is None:
        return None
    return _to_summary(c)


def get_chunks_for_urns(urns: list[str], chunks_dir: Path | None = None) -> list[ChunkSummary]:
    """Bulk lookup; returns ChunkSummary for each URN (missing URNs dropped)."""
    d = chunks_dir or DEFAULT_CHUNKS_DIR
    index = _ensure_chunks_loaded(d)
    out: list[ChunkSummary] = []
    for urn in urns:
        c = index.get(urn)
        if c is not None:
            out.append(_to_summary(c))
    return out


# ---------------------------------------------------------------------------
# Phase 12.0 — corpus enumeration for the vigência review UI
# ---------------------------------------------------------------------------


def list_documents(chunks_dir: Path | None = None) -> list[dict]:
    """Return the distinct document URNs in the corpus, each with the
    count of chunks it contains. Sorted by document URN.

    Used by the /v1/admin/corpus/documents endpoint to populate the
    document picker in the Phase 12 vigência review UI.
    """
    d = chunks_dir or DEFAULT_CHUNKS_DIR
    index = _ensure_chunks_loaded(d)
    counts: dict[str, int] = {}
    for chunk in index.values():
        doc = chunk.urn.split("~")[0]
        counts[doc] = counts.get(doc, 0) + 1
    return [
        {"document_urn": doc, "chunk_count": n}
        for doc, n in sorted(counts.items())
    ]


def get_chunks_for_document(
    document_urn: str,
    *,
    offset: int = 0,
    limit: int = 50,
    chunks_dir: Path | None = None,
) -> tuple[int, list[ChunkSummary]]:
    """Paginated walk through chunks of a single document.

    Returns (total_count, page). Order: stable URN sort so the UI's
    "next chunk" button is deterministic.
    """
    d = chunks_dir or DEFAULT_CHUNKS_DIR
    index = _ensure_chunks_loaded(d)
    all_for_doc = [
        c for c in index.values() if c.urn.split("~")[0] == document_urn
    ]
    all_for_doc.sort(key=lambda c: c.urn)
    page = all_for_doc[offset : offset + limit]
    return len(all_for_doc), [_to_summary(c) for c in page]


def _kind_from_urn(urn: str) -> str:
    """Derive the partition kind (artigo/paragrafo/inciso/alinea) from URN suffix.

    URN shape: `urn:lex:br:federal:lei:YYYY-MM-DD;NUMBER~partition`
    The partition fragment names the kind (art5, art5;par1, art5;inc1, etc).
    Returns the leaf partition's prefix.
    """
    if "~" not in urn:
        return "documento"  # whole-document URN
    partition = urn.split("~", 1)[1]
    # Leaf segment is the last `;`-separated piece
    leaf = partition.split(";")[-1]
    if leaf.startswith("art"):
        return "artigo"
    if leaf.startswith("par"):
        return "paragrafo"
    if leaf.startswith("inc"):
        return "inciso"
    if leaf.startswith("alinea") or leaf.startswith("alin"):
        return "alinea"
    return leaf  # unknown — return the raw prefix


def _to_summary(c: IndexChunk) -> ChunkSummary:
    """Project an IndexChunk into the API-shaped ChunkSummary."""
    return ChunkSummary(
        urn=c.urn,
        document_urn=c.urn.split("~")[0],
        label=c.citation or "",
        nav=c.nav_text or "",
        caput=c.caput_text or None,
        text=c.text or "",
        kind=_kind_from_urn(c.urn),
    )


# ---------------------------------------------------------------------------
# Convenience: dump for JSON serialization
# ---------------------------------------------------------------------------


def row_to_json(row: EvalQueryRow) -> dict:
    """Plain-dict shape for FastAPI JSON serialization."""
    return {
        "id": row.id,
        "query": row.query,
        "qtype": row.qtype,
        "core_urns": list(row.core_urns),
        "supporting_urns": list(row.supporting_urns),
        "notes": row.notes,
    }


def chunk_to_json(chunk: ChunkSummary) -> dict:
    return {
        "urn": chunk.urn,
        "document_urn": chunk.document_urn,
        "label": chunk.label,
        "nav": chunk.nav,
        "caput": chunk.caput,
        "text": chunk.text,
        "kind": chunk.kind,
    }


def reset_caches() -> None:
    """Test helper — clear the chunks cache between tests."""
    global _chunks_cache
    _chunks_cache = None


# Suppress flake on unused import — yaml is re-exported for callers
# that may need to dump YAML diffs of proposals later (Phase 11.4).
_ = yaml
