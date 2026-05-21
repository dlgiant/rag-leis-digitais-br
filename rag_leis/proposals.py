"""Phase 11.2.1 — Postgres-backed proposal storage.

Replaces the Phase 11.2 JSONL append-only file with Postgres
INSERT / SELECT against `rag_leis.db`. The public API
(append_proposal, load_pending_proposals, etc.) stays unchanged
so admin.py and tests don't need updates beyond setting up the
DB connection.

A `Proposal` is one of three kinds:

  - `review`     — a reviewer submitted a verdict (correct / incorrect /
                   needs_followup) on an existing eval row.
  - `new_row`    — the operator proposed a brand-new eval row.
  - `refinement` — Phase 11.3 only.

The merge tool (Phase 11.4) reads from `proposals` and writes
proposal IDs to `merged_proposals` after merging into
`eval/queries.yaml`. `load_pending_proposals()` filters those out
via a NOT EXISTS subquery.

The UI / admin API NEVER write to `eval/queries.yaml` directly —
that's the operator's PR-style git workflow.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from rag_leis.db import get_conn

ProposalKind = Literal[
    "review", "new_row", "refinement", "vigencia", "hierarchy", "pii_miss",
]
Verdict = Literal["correct", "incorrect", "needs_followup"]
VigenciaStatus = Literal[
    "vigente",
    "sub_judice",
    "suspenso",
    "vacatio_legis",
    "eficacia_limitada",
    "revogado_tacito",
    "alterado_por_ec",
    "atualizado_recentemente",
]


@dataclass(frozen=True)
class Proposal:
    """A single proposal record. Fields are explicit so the queue
    page + merge tool can decide what to show without guessing
    intent from a JSON blob."""

    # Identity
    id: str  # uuid4 hex; unique per proposal
    ts: str  # ISO-8601 with timezone offset

    # Authorship
    reviewer_email: str
    is_operator: bool

    # Discriminator
    kind: ProposalKind

    # Target — for `review` + `refinement`, references an existing eval row
    query_id: str | None = None

    # Review-specific
    verdict: Verdict | None = None
    notes: str = ""
    suggested_gold_urns: tuple[str, ...] = field(default_factory=tuple)
    suggested_classified_type: str | None = None

    # New-row-specific
    new_query_text: str | None = None
    new_qtype: str | None = None
    new_core_urns: tuple[str, ...] = field(default_factory=tuple)
    new_supporting_urns: tuple[str, ...] = field(default_factory=tuple)

    # Refinement-specific (Phase 11.3)
    refined_query_text: str | None = None

    # Vigência-specific (Phase 12.0) — populated only when kind='vigencia'
    vigencia_urn: str | None = None
    vigencia_status: VigenciaStatus | None = None
    vigencia_fundamento: str | None = None
    vigencia_desde: str | None = None  # ISO-8601 date, e.g. "2017-09-29"
    vigencia_descricao_curta: str | None = None

    # Hierarchy-specific (Phase 13.0) — populated only when kind='hierarchy'
    hierarchy_query: str | None = None
    hierarchy_flagged_urns: tuple[str, ...] = field(default_factory=tuple)
    hierarchy_top_rank: int | None = None  # 1-5 (CF..infralegal)

    # PII-miss-specific (Phase 14.0) — populated only when kind='pii_miss'
    pii_audit_log_id: int | None = None  # FK to pii_audit_log.id
    pii_missed_types: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_proposal_id() -> str:
    """uuid4 hex — short, unique, no PII."""
    return uuid.uuid4().hex


def utc_now_iso() -> str:
    """ISO-8601 timestamp with UTC offset. Used as the `ts` field
    when constructing a Proposal client-side. The DB column stores
    TIMESTAMPTZ so the time-zone is preserved end-to-end."""
    return datetime.now(UTC).isoformat()


def to_jsonable(p: Proposal) -> dict:
    """Convert a Proposal into a JSON-serializable dict — used by
    the admin API responses + the /proposals page rendering."""
    return {
        "id": p.id,
        "ts": p.ts,
        "reviewer_email": p.reviewer_email,
        "is_operator": p.is_operator,
        "kind": p.kind,
        "query_id": p.query_id,
        "verdict": p.verdict,
        "notes": p.notes,
        "suggested_gold_urns": list(p.suggested_gold_urns),
        "suggested_classified_type": p.suggested_classified_type,
        "new_query_text": p.new_query_text,
        "new_qtype": p.new_qtype,
        "new_core_urns": list(p.new_core_urns),
        "new_supporting_urns": list(p.new_supporting_urns),
        "refined_query_text": p.refined_query_text,
        "vigencia_urn": p.vigencia_urn,
        "vigencia_status": p.vigencia_status,
        "vigencia_fundamento": p.vigencia_fundamento,
        "vigencia_desde": p.vigencia_desde,
        "vigencia_descricao_curta": p.vigencia_descricao_curta,
        "hierarchy_query": p.hierarchy_query,
        "hierarchy_flagged_urns": list(p.hierarchy_flagged_urns),
        "hierarchy_top_rank": p.hierarchy_top_rank,
        "pii_audit_log_id": p.pii_audit_log_id,
        "pii_missed_types": list(p.pii_missed_types),
    }


# ---------------------------------------------------------------------------
# Append (single INSERT)
# ---------------------------------------------------------------------------


_INSERT_SQL = """
INSERT INTO proposals (
    id, ts, reviewer_email, is_operator, kind,
    query_id, verdict, notes, suggested_gold_urns, suggested_classified_type,
    new_query_text, new_qtype, new_core_urns, new_supporting_urns,
    refined_query_text,
    vigencia_urn, vigencia_status, vigencia_fundamento, vigencia_desde,
    vigencia_descricao_curta,
    hierarchy_query, hierarchy_flagged_urns, hierarchy_top_rank,
    pii_audit_log_id, pii_missed_types
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s,
    %s, %s, %s, %s,
    %s,
    %s, %s, %s,
    %s, %s
)
ON CONFLICT (id) DO NOTHING
"""


def append_proposal(p: Proposal) -> None:
    """Insert one Proposal. ON CONFLICT clause makes it idempotent —
    re-running an import script with the same row IDs is a no-op."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            _INSERT_SQL,
            (
                p.id,
                p.ts,
                p.reviewer_email,
                p.is_operator,
                p.kind,
                p.query_id,
                p.verdict,
                p.notes,
                list(p.suggested_gold_urns),
                p.suggested_classified_type,
                p.new_query_text,
                p.new_qtype,
                list(p.new_core_urns),
                list(p.new_supporting_urns),
                p.refined_query_text,
                p.vigencia_urn,
                p.vigencia_status,
                p.vigencia_fundamento,
                p.vigencia_desde,
                p.vigencia_descricao_curta,
                p.hierarchy_query,
                list(p.hierarchy_flagged_urns),
                p.hierarchy_top_rank,
                p.pii_audit_log_id,
                list(p.pii_missed_types),
            ),
        )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


_SELECT_COLUMNS = """
    id, ts, reviewer_email, is_operator, kind,
    query_id, verdict, notes, suggested_gold_urns, suggested_classified_type,
    new_query_text, new_qtype, new_core_urns, new_supporting_urns,
    refined_query_text,
    vigencia_urn, vigencia_status, vigencia_fundamento, vigencia_desde,
    vigencia_descricao_curta,
    hierarchy_query, hierarchy_flagged_urns, hierarchy_top_rank,
    pii_audit_log_id, pii_missed_types
"""


def _row_to_proposal(row: tuple) -> Proposal:
    """Convert a fetched row into a Proposal dataclass."""
    (
        pid, ts, reviewer_email, is_operator, kind,
        query_id, verdict, notes, suggested_gold_urns, suggested_classified_type,
        new_query_text, new_qtype, new_core_urns, new_supporting_urns,
        refined_query_text,
        vigencia_urn, vigencia_status, vigencia_fundamento, vigencia_desde,
        vigencia_descricao_curta,
        hierarchy_query, hierarchy_flagged_urns, hierarchy_top_rank,
        pii_audit_log_id, pii_missed_types,
    ) = row
    # ts is a datetime from psycopg; serialize to ISO for API consistency
    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    return Proposal(
        id=pid,
        ts=ts_str,
        reviewer_email=reviewer_email,
        is_operator=bool(is_operator),
        kind=kind,
        query_id=query_id,
        verdict=verdict,
        notes=notes or "",
        suggested_gold_urns=tuple(suggested_gold_urns or ()),
        suggested_classified_type=suggested_classified_type,
        new_query_text=new_query_text,
        new_qtype=new_qtype,
        new_core_urns=tuple(new_core_urns or ()),
        new_supporting_urns=tuple(new_supporting_urns or ()),
        refined_query_text=refined_query_text,
        vigencia_urn=vigencia_urn,
        vigencia_status=vigencia_status,
        vigencia_fundamento=vigencia_fundamento,
        # Postgres DATE returns a `date` object; serialize to ISO string
        # for API consistency (the dataclass expects str | None).
        vigencia_desde=(
            vigencia_desde.isoformat()
            if hasattr(vigencia_desde, "isoformat") else vigencia_desde
        ),
        vigencia_descricao_curta=vigencia_descricao_curta,
        hierarchy_query=hierarchy_query,
        hierarchy_flagged_urns=tuple(hierarchy_flagged_urns or ()),
        hierarchy_top_rank=hierarchy_top_rank,
        pii_audit_log_id=pii_audit_log_id,
        pii_missed_types=tuple(pii_missed_types or ()),
    )


def load_all_proposals() -> list[Proposal]:
    """Every proposal in chronological order (oldest first).

    Used by tests + by the merge tool when it wants the full
    history (including already-merged proposals)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_SELECT_COLUMNS} FROM proposals ORDER BY ts ASC, id ASC"
        )
        rows = cur.fetchall()
    return [_row_to_proposal(r) for r in rows]


def load_pending_proposals() -> list[Proposal]:
    """Proposals NOT yet in `merged_proposals` — the operator's
    inbox. Ordered oldest first so the merge tool processes them in
    submission order."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
                SELECT {_SELECT_COLUMNS}
                FROM proposals p
                WHERE NOT EXISTS (
                    SELECT 1 FROM merged_proposals m WHERE m.proposal_id = p.id
                )
                ORDER BY p.ts ASC, p.id ASC
                """
        )
        rows = cur.fetchall()
    return [_row_to_proposal(r) for r in rows]


# ---------------------------------------------------------------------------
# Merge-marking (used by Phase 11.4's merge tool)
# ---------------------------------------------------------------------------


def mark_merged(proposal_id: str, *, merged_by: str, commit_sha: str | None = None) -> None:
    """Record that a proposal was merged into eval/queries.yaml.

    Subsequent calls to `load_pending_proposals()` will skip it.
    ON CONFLICT clause makes re-marking the same ID a no-op.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                INSERT INTO merged_proposals (proposal_id, merged_by, commit_sha)
                VALUES (%s, %s, %s)
                ON CONFLICT (proposal_id) DO NOTHING
                """,
            (proposal_id, merged_by, commit_sha),
        )
