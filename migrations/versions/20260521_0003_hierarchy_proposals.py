"""Phase 13.0 — extend proposals for hierarchy-masking flags.

A `kind='hierarchy'` proposal records a case where the lawyer
observed that retrieval returned chunks from a lower-rank legal
source (e.g. ANPD Resolução) when a higher-rank source (e.g. LGPD
itself) would have been more appropriate to cite — addressing 🔴
blocker #2 in `study/lawyer-review-checklist.md`.

Schema additions:

  - hierarchy_query           TEXT    — the query that exposed the case
  - hierarchy_flagged_urns    TEXT[]  — URNs the lawyer flagged as
                                         either missing-from-top or
                                         wrongly-outranking
  - hierarchy_top_rank        INTEGER — best (lowest numeric) rank
                                         observed in the top-k at
                                         submit time (1=CF, 5=infralegal)

Plus: extend the kind CHECK to allow 'hierarchy' alongside the four
existing kinds.

Revision ID: 20260521_0003
Revises: 20260521_0002
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op

revision: str = "20260521_0003"
down_revision: str | None = "20260521_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Re-add the kind CHECK constraint including 'hierarchy'.
    op.execute(
        "ALTER TABLE proposals "
        "DROP CONSTRAINT IF EXISTS proposals_kind_check"
    )
    op.execute(
        "ALTER TABLE proposals "
        "ADD CONSTRAINT proposals_kind_check "
        "CHECK (kind IN ('review', 'new_row', 'refinement', 'vigencia', 'hierarchy'))"
    )

    # New columns, all nullable (only populated when kind='hierarchy').
    op.execute("ALTER TABLE proposals ADD COLUMN hierarchy_query TEXT")
    op.execute(
        "ALTER TABLE proposals ADD COLUMN hierarchy_flagged_urns TEXT[] "
        "NOT NULL DEFAULT ARRAY[]::TEXT[]"
    )
    op.execute("ALTER TABLE proposals ADD COLUMN hierarchy_top_rank INTEGER")

    # CHECK on the rank value: 1-5 matches the constants in
    # rag_leis/legal_rank.py (CONSTITUCIONAL=1 .. INFRALEGAL=5).
    op.execute(
        "ALTER TABLE proposals "
        "ADD CONSTRAINT proposals_hierarchy_top_rank_check "
        "CHECK (hierarchy_top_rank IS NULL OR hierarchy_top_rank BETWEEN 1 AND 5)"
    )

    # Partial index for the operator's review queue.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_hierarchy_query "
        "ON proposals (kind) WHERE kind = 'hierarchy'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_proposals_hierarchy_query")
    op.execute(
        "ALTER TABLE proposals "
        "DROP CONSTRAINT IF EXISTS proposals_hierarchy_top_rank_check"
    )
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS hierarchy_top_rank")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS hierarchy_flagged_urns")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS hierarchy_query")
    op.execute(
        "ALTER TABLE proposals "
        "DROP CONSTRAINT IF EXISTS proposals_kind_check"
    )
    op.execute(
        "ALTER TABLE proposals "
        "ADD CONSTRAINT proposals_kind_check "
        "CHECK (kind IN ('review', 'new_row', 'refinement', 'vigencia'))"
    )
