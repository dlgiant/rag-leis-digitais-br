"""Phase 14.0 — extend proposals for PII-miss flags.

A `kind='pii_miss'` proposal records a case where the lawyer
reviewed a pii_audit_log entry and identified PII categories the
redactor missed (e.g. OAB numbers, processo SEI codes, eleitoral
IDs — categories not covered by the current 6 regex patterns in
`rag_leis/pii.py`).

Closes 🟡 #6 from `study/lawyer-review-checklist.md`.

Schema additions:

  - pii_audit_log_id      BIGINT — FK to the pii_audit_log row
                                    being flagged
  - pii_missed_types      TEXT[] — categories the lawyer says were
                                    missed (e.g. ["oab", "processo_sei"])

Plus: extend the kind CHECK to allow 'pii_miss' alongside the five
existing kinds.

Revision ID: 20260521_0004
Revises: 20260521_0003
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op

revision: str = "20260521_0004"
down_revision: str | None = "20260521_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE proposals "
        "DROP CONSTRAINT IF EXISTS proposals_kind_check"
    )
    op.execute(
        "ALTER TABLE proposals "
        "ADD CONSTRAINT proposals_kind_check "
        "CHECK (kind IN ('review', 'new_row', 'refinement', "
        "                 'vigencia', 'hierarchy', 'pii_miss'))"
    )

    op.execute(
        "ALTER TABLE proposals ADD COLUMN pii_audit_log_id BIGINT "
        "REFERENCES pii_audit_log(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE proposals ADD COLUMN pii_missed_types TEXT[] "
        "NOT NULL DEFAULT ARRAY[]::TEXT[]"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_pii_audit_log_id "
        "ON proposals (pii_audit_log_id) WHERE pii_audit_log_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_proposals_pii_audit_log_id")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS pii_missed_types")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS pii_audit_log_id")
    op.execute(
        "ALTER TABLE proposals "
        "DROP CONSTRAINT IF EXISTS proposals_kind_check"
    )
    op.execute(
        "ALTER TABLE proposals "
        "ADD CONSTRAINT proposals_kind_check "
        "CHECK (kind IN ('review', 'new_row', 'refinement', "
        "                 'vigencia', 'hierarchy'))"
    )
