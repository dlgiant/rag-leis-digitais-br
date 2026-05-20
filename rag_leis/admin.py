"""Phase 11.0 — `/v1/admin/*` read-only endpoints for the review UI.

Gated by Clerk JWT verification (`rag_leis.clerk_auth`). All endpoints
require the caller's email to be in `RAG_ADMIN_ALLOWLIST`. Operator-
only endpoints (Phase 11.2+) additionally check `is_operator`.

Read endpoints shipped in 11.0:
  GET /v1/admin/eval/queries          — paginated list of eval rows
  GET /v1/admin/eval/queries/{id}     — single row with expanded chunks
  GET /v1/admin/chunks/{urn}          — single chunk by URN

Write endpoints (Phase 11.2) and refinement (Phase 11.3) land in
subsequent commits.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from rag_leis.clerk_auth import ClerkClaims, clerk_auth_dependency
from rag_leis.eval_loader import (
    chunk_to_json,
    get_chunk,
    get_chunks_for_urns,
    load_eval_queries,
    row_to_json,
)

# urn:lex URNs contain `:` and `;` which collide with FastAPI path-param
# parsing. We accept URNs via a `{urn:path}` catch-all so the entire
# remaining path becomes the URN.
router = APIRouter(prefix="/v1/admin", tags=["admin"])

ClaimsDep = Annotated[ClerkClaims, Depends(clerk_auth_dependency)]


# ---------------------------------------------------------------------------
# Eval queries
# ---------------------------------------------------------------------------


@router.get("/eval/queries")
def list_eval_queries(
    claims: ClaimsDep,
    qtype: str | None = Query(default=None, description="Filter by classified type"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List eval rows, optionally filtered by qtype, paginated."""
    rows = load_eval_queries()
    if qtype:
        rows = [r for r in rows if r.qtype == qtype]
    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "qtype_filter": qtype,
        "rows": [row_to_json(r) for r in page],
        # Echo who made the request — useful for the UI dashboard.
        "viewer": {"email": claims.email, "is_operator": claims.is_operator},
    }


@router.get("/eval/queries/{query_id}")
def get_eval_query(query_id: str, claims: ClaimsDep) -> dict:
    """Single eval row with expanded chunk text for each gold URN.

    The chunk text is included so the review UI doesn't have to make
    a second round-trip per URN. Missing URNs (corpus drift) are
    silently dropped from `gold_chunks` but still present in
    `core_urns` / `supporting_urns` so the lawyer can flag them.
    """
    rows = load_eval_queries()
    row = next((r for r in rows if r.id == query_id), None)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"eval query not found: {query_id}",
        )
    all_urns = list(row.core_urns) + list(row.supporting_urns)
    chunks = get_chunks_for_urns(all_urns)
    return {
        **row_to_json(row),
        "gold_chunks": [chunk_to_json(c) for c in chunks],
        "missing_urns": [u for u in all_urns if not any(c.urn == u for c in chunks)],
        "viewer": {"email": claims.email, "is_operator": claims.is_operator},
    }


# ---------------------------------------------------------------------------
# Chunk lookup
# ---------------------------------------------------------------------------


@router.get("/chunks/{urn:path}")
def get_chunk_endpoint(urn: str, claims: ClaimsDep) -> dict:
    """Look up a single chunk by URN. URN passed as a catch-all path
    segment to handle the `:` and `;` characters that would otherwise
    collide with FastAPI's path-param parsing."""
    chunk = get_chunk(urn)
    if chunk is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"chunk not found: {urn}",
        )
    return {
        **chunk_to_json(chunk),
        "viewer": {"email": claims.email, "is_operator": claims.is_operator},
    }
