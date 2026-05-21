"""Phase 11.0 + 11.2 + 11.3 — `/v1/admin/*` endpoints for the review UI.

Gated by Clerk JWT verification (`rag_leis.clerk_auth`). All endpoints
require the caller's email to be in `RAG_ADMIN_ALLOWLIST`. Operator-
only endpoints additionally check `is_operator`.

Read endpoints (Phase 11.0):
  GET /v1/admin/eval/queries          — paginated list of eval rows
  GET /v1/admin/eval/queries/{id}     — single row with expanded chunks
  GET /v1/admin/chunks/{urn}          — single chunk by URN

Write endpoints (Phase 11.2):
  POST /v1/admin/eval/queries/{id}/review  — submit a verdict on an
                                              existing row (any
                                              allowlisted user)
  GET  /v1/admin/proposals                 — list pending proposals
                                              (operator-only)

Refinement (Phase 11.3):
  POST /v1/admin/eval/queries/{id}/refine  — retrieval-only re-run with
                                              an alternate query phrasing;
                                              optionally saves a
                                              kind=refinement proposal.

The merge tool (Phase 11.4) is an OFFLINE operator CLI; not an HTTP
endpoint. See scripts/phase_11_4_merge_proposals.py.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from rag_leis.clerk_auth import ClerkClaims, clerk_auth_dependency, require_operator
from rag_leis.eval_loader import (
    chunk_to_json,
    get_chunk,
    get_chunks_for_urns,
    load_eval_queries,
    row_to_json,
)
from rag_leis.proposals import (
    Proposal,
    append_proposal,
    load_pending_proposals,
    new_proposal_id,
    to_jsonable,
    utc_now_iso,
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


# ---------------------------------------------------------------------------
# Review submission (Phase 11.2) — write path
# ---------------------------------------------------------------------------


class ReviewSubmission(BaseModel):
    """Body for POST /v1/admin/eval/queries/{id}/review."""

    verdict: Literal["correct", "incorrect", "needs_followup"]
    notes: str = Field(default="", max_length=4000)
    suggested_gold_urns: list[str] = Field(default_factory=list, max_length=64)
    suggested_classified_type: str | None = Field(default=None, max_length=64)


@router.post("/eval/queries/{query_id}/review")
def submit_review(
    query_id: str,
    body: ReviewSubmission,
    claims: ClaimsDep,
) -> dict:
    """Submit a verdict on an existing eval row.

    The verdict + notes + any URN suggestions are appended to
    `data/review/proposals.jsonl` as a single Proposal record. This
    endpoint NEVER edits `eval/queries.yaml` — the operator merges
    proposals via Phase 11.4's CLI tool.

    Open to any user on the admin allowlist (lawyer + operator).
    """
    # Validate the query_id exists. Reviews referencing a deleted
    # row would clutter the queue.
    rows = load_eval_queries()
    if not any(r.id == query_id for r in rows):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"eval query not found: {query_id}",
        )

    proposal = Proposal(
        id=new_proposal_id(),
        ts=utc_now_iso(),
        reviewer_email=claims.email,
        is_operator=claims.is_operator,
        kind="review",
        query_id=query_id,
        verdict=body.verdict,
        notes=body.notes,
        suggested_gold_urns=tuple(body.suggested_gold_urns),
        suggested_classified_type=body.suggested_classified_type,
    )
    append_proposal(proposal)
    return {
        "ok": True,
        "proposal": to_jsonable(proposal),
    }


# ---------------------------------------------------------------------------
# Refinement (Phase 11.3) — retrieval-only re-run with alternate phrasing
# ---------------------------------------------------------------------------


class RefineRequest(BaseModel):
    """Body for POST /v1/admin/eval/queries/{id}/refine.

    `top_k` controls how many chunks to return; capped at 50 so a
    runaway request can't expand into a multi-MB response.
    """

    refined_query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    save_as_proposal: bool = True


@router.post("/eval/queries/{query_id}/refine")
def refine_query(
    query_id: str,
    body: RefineRequest,
    claims: ClaimsDep,
    request: Request,
) -> dict:
    """Run a retrieval-only pass with an alternate query phrasing.

    Returns the original row + the refined query's top-k retrieved
    URNs, each annotated with whether it matches one of the
    original's gold URNs (core or supporting). Lets the lawyer see
    at a glance whether the alternate phrasing retrieves the same
    chunks the eval set expects.

    Retrieval-only by design — we do NOT call the full pipeline
    (no LLM generation, no relevance judge). Reasons:
      * cost: a full pipeline run is ~$0.005-0.01 in Sabiá spend;
        retrieval-only is essentially free (just embedding the query)
      * latency: full pipeline is 15-20s warm; retrieval is <100ms
      * the lawyer's primary question is "did this phrasing pull the
        right chunks?", which retrieval answers directly

    If `save_as_proposal=True`, writes a kind=refinement Proposal to
    Postgres with the refined_query_text + retrieved URNs as
    new_core_urns. The Phase 11.4 merge tool can later promote it to
    a new eval row.

    Open to any allowlisted user. Cost-sensitive: each call burns one
    query embedding (~$0.0001 with Voyage, free with BGE-M3).
    """
    # Validate query_id + capture the eval row for the response
    rows = load_eval_queries()
    row = next((r for r in rows if r.id == query_id), None)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"eval query not found: {query_id}",
        )

    # Pull the pipeline off app.state. The lifespan loads it on startup.
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        # Should be unreachable in normal operation; here for clarity.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="pipeline not loaded",
        )

    # Retrieval-only — `_retrieve` is underscore-prefixed (internal-ish)
    # but stable since it's used by `answer()` itself.
    retrieved: list[tuple[str, float]] = pipeline._retrieve(
        body.refined_query, top_k=body.top_k,
    )

    gold_urns: set[str] = set(row.core_urns) | set(row.supporting_urns)

    # Build a JSON-friendly response with chunk snippets so the UI can
    # render snippets next to each retrieved URN without a second
    # round-trip.
    retrieved_payload: list[dict] = []
    for rank, (urn, score) in enumerate(retrieved, start=1):
        chunk = get_chunk(urn)
        retrieved_payload.append({
            "rank": rank,
            "urn": urn,
            "score": score,
            "matches_gold": urn in gold_urns,
            # `chunk` may be None if the URN is in the index but the
            # chunk file is missing (data drift); defensive None-check.
            "snippet": _snippet(chunk),
            "citation": chunk.citation if chunk else None,
            "nav_text": chunk.nav_text if chunk else None,
        })

    proposal_json: dict | None = None
    if body.save_as_proposal:
        # Capture as kind=refinement. The merge tool (Phase 11.4) sees
        # it as a candidate for promotion to a new eval row.
        proposal = Proposal(
            id=new_proposal_id(),
            ts=utc_now_iso(),
            reviewer_email=claims.email,
            is_operator=claims.is_operator,
            kind="refinement",
            query_id=query_id,
            refined_query_text=body.refined_query,
            # Store the retrieved URNs so the operator can promote-as-new-row
            # without re-running retrieval. Only top-3 to keep the proposal
            # focused; the full list is reproducible from refined_query_text.
            new_core_urns=tuple(urn for urn, _ in retrieved[:3]),
        )
        append_proposal(proposal)
        proposal_json = to_jsonable(proposal)

    return {
        "ok": True,
        "original": {
            "query_id": row.id,
            "query": row.query,
            "type": row.classified_type,
            "core_urns": list(row.core_urns),
            "supporting_urns": list(row.supporting_urns),
        },
        "refined": {
            "query": body.refined_query,
            "top_k": body.top_k,
            "retrieved": retrieved_payload,
            "n_matches_gold": sum(1 for r in retrieved_payload if r["matches_gold"]),
            "n_gold_total": len(gold_urns),
        },
        "proposal": proposal_json,
        "viewer": {"email": claims.email, "is_operator": claims.is_operator},
    }


def _snippet(chunk, max_chars: int = 240) -> str | None:
    """Truncate a chunk's text to a single-line preview for the UI list.

    Replaces internal newlines with spaces; trims; ellipsizes."""
    if chunk is None:
        return None
    text = (chunk.text or "").replace("\n", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


# ---------------------------------------------------------------------------
# Proposals queue (operator-only) — Phase 11.2
# ---------------------------------------------------------------------------


@router.get("/proposals")
def list_proposals(claims: ClaimsDep) -> dict:
    """List pending proposals (not yet merged into eval/queries.yaml).

    Operator-only. Used by the /proposals page in the UI + by the
    Phase 11.4 merge-tool CLI for its interactive prompts.
    """
    require_operator(claims)
    pending = load_pending_proposals()
    return {
        "total": len(pending),
        "proposals": [to_jsonable(p) for p in pending],
        "viewer": {"email": claims.email, "is_operator": claims.is_operator},
    }
