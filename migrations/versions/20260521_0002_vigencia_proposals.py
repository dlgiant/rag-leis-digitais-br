"""Phase 12.0 — extend proposals for vigência annotations.

Adds a new `kind="vigencia"` Proposal type so the lawyer can submit
vigência overlay annotations through the review UI (Phase 12.1).
The Phase 11.4 merge tool (extended in 12.3) routes accepted
proposals into `data/vigencia/overlays.yaml` instead of
`eval/queries.yaml`.

Schema additions to `proposals`:

  - vigencia_urn               TEXT  — chunk URN being annotated
  - vigencia_status            TEXT  — one of the eight vigência
                                       categories (CHECK constraint)
  - vigencia_fundamento        TEXT  — STF/STJ process, EC, etc.
  - vigencia_desde             DATE  — affectation/effective date
  - vigencia_descricao_curta   TEXT  — 1-3 sentences shown as warning

Plus: extend the existing kind CHECK constraint to allow 'vigencia'
alongside 'review' / 'new_row' / 'refinement'.

Revision ID: 20260521_0002
Revises: 20260521_0001
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op

revision: str = "20260521_0002"
down_revision: str | None = "20260521_0001"
branch_labels = None
depends_on = None

# The eight statuses that `data/vigencia/overlays.yaml` v0 documents.
# Mirrored here as a CHECK constraint so the DB enforces what the
# YAML schema enforces by convention.
_VIGENCIA_STATUSES = (
    "vigente",                  # default; not normally overlaid
    "sub_judice",               # controvérsia constitucional pendente
    "suspenso",                 # eficácia suspensa por liminar
    "vacatio_legis",            # promulgado mas ainda não em vigor
    "eficacia_limitada",        # depende de regulamentação infralegal
    "revogado_tacito",          # incompatível com norma posterior
    "alterado_por_ec",          # EC modificadora (informativo)
    "atualizado_recentemente",  # lei alteradora recente (informativo)
)


def upgrade() -> None:
    # Drop+re-add the kind CHECK constraint to include 'vigencia'.
    # Postgres doesn't let you ALTER a CHECK constraint in place.
    op.execute(
        "ALTER TABLE proposals "
        "DROP CONSTRAINT IF EXISTS proposals_kind_check"
    )
    op.execute(
        "ALTER TABLE proposals "
        "ADD CONSTRAINT proposals_kind_check "
        "CHECK (kind IN ('review', 'new_row', 'refinement', 'vigencia'))"
    )

    # Add the new columns. All nullable since they only apply when
    # kind='vigencia'; review/new_row/refinement rows keep them NULL.
    op.execute("ALTER TABLE proposals ADD COLUMN vigencia_urn TEXT")
    op.execute("ALTER TABLE proposals ADD COLUMN vigencia_status TEXT")
    op.execute("ALTER TABLE proposals ADD COLUMN vigencia_fundamento TEXT")
    op.execute("ALTER TABLE proposals ADD COLUMN vigencia_desde DATE")
    op.execute("ALTER TABLE proposals ADD COLUMN vigencia_descricao_curta TEXT")

    # CHECK constraint on vigencia_status. Allow NULL (non-vigencia
    # proposals) OR one of the eight known statuses.
    statuses_sql = ", ".join(f"'{s}'" for s in _VIGENCIA_STATUSES)
    op.execute(
        f"""
        ALTER TABLE proposals
        ADD CONSTRAINT proposals_vigencia_status_check
        CHECK (
            vigencia_status IS NULL
            OR vigencia_status IN ({statuses_sql})
        )
        """
    )

    # Index on vigencia_urn so the /proposals queue + the merge tool
    # can quickly find pending annotations for a given chunk.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_vigencia_urn "
        "ON proposals (vigencia_urn) WHERE vigencia_urn IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_proposals_vigencia_urn")
    op.execute(
        "ALTER TABLE proposals "
        "DROP CONSTRAINT IF EXISTS proposals_vigencia_status_check"
    )
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS vigencia_descricao_curta")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS vigencia_desde")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS vigencia_fundamento")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS vigencia_status")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS vigencia_urn")
    op.execute(
        "ALTER TABLE proposals "
        "DROP CONSTRAINT IF EXISTS proposals_kind_check"
    )
    op.execute(
        "ALTER TABLE proposals "
        "ADD CONSTRAINT proposals_kind_check "
        "CHECK (kind IN ('review', 'new_row', 'refinement'))"
    )
