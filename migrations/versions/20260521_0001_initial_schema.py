"""Phase 11.2.1 — initial schema.

Creates the five tables that move from JSONL files to Postgres:

  - proposals          — lawyer-submitted review proposals
  - merged_proposals   — track which proposal IDs were merged into eval/queries.yaml
  - pii_audit_log      — Phase 4.2 PII redaction audit (currently silent-ephemeral on Fly)
  - users              — Phase 10c schema-only (no code consumes yet)
  - conversations      — Phase 10c schema-only
  - conversation_messages — Phase 10c schema-only

The Phase 10c tables ship empty but with their schemas defined so we
don't have to touch the DB twice when Phase 10c arrives.

Revision ID: 20260521_0001
Revises:
Create Date: 2026-05-21

"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260521_0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =====================================================================
    # proposals — Phase 11.2 lawyer/reviewer submissions
    # =====================================================================
    op.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id              TEXT PRIMARY KEY,             -- uuid4 hex
            ts              TIMESTAMPTZ NOT NULL,         -- when proposed
            reviewer_email  TEXT NOT NULL,                -- author identity (allowlisted)
            is_operator     BOOLEAN NOT NULL DEFAULT FALSE,

            kind            TEXT NOT NULL                 -- 'review' | 'new_row' | 'refinement'
                            CHECK (kind IN ('review', 'new_row', 'refinement')),

            -- Target — for `review` + `refinement`, references an existing eval row id.
            query_id        TEXT,

            -- Review-specific (NULL for new_row / refinement kinds)
            verdict         TEXT                          -- 'correct' | 'incorrect' | 'needs_followup'
                            CHECK (verdict IS NULL OR verdict IN ('correct', 'incorrect', 'needs_followup')),
            notes           TEXT NOT NULL DEFAULT '',
            suggested_gold_urns          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            suggested_classified_type    TEXT,

            -- new_row-specific (NULL for review / refinement)
            new_query_text       TEXT,
            new_qtype            TEXT,
            new_core_urns        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            new_supporting_urns  TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],

            -- refinement-specific (Phase 11.3)
            refined_query_text   TEXT
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_proposals_ts ON proposals (ts DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_proposals_query_id ON proposals (query_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_proposals_kind ON proposals (kind);")

    # =====================================================================
    # merged_proposals — tracks which proposal IDs got merged into eval/queries.yaml
    # =====================================================================
    op.execute("""
        CREATE TABLE IF NOT EXISTS merged_proposals (
            proposal_id   TEXT PRIMARY KEY,
            merged_ts     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            merged_by     TEXT NOT NULL,
            -- Optional commit SHA the merge landed in (post-merge)
            commit_sha    TEXT
        );
    """)

    # =====================================================================
    # pii_audit_log — Phase 4.2 PII redaction audit
    # =====================================================================
    op.execute("""
        CREATE TABLE IF NOT EXISTS pii_audit_log (
            id              BIGSERIAL PRIMARY KEY,
            ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            schema_version  SMALLINT NOT NULL DEFAULT 1,

            -- Hash of the ORIGINAL query (PII included); used to identify
            -- duplicate submissions without storing the original.
            original_hash   TEXT NOT NULL,

            -- The REDACTED query text (PII patterns replaced with placeholders).
            redacted_text   TEXT NOT NULL,

            -- Which PII types were detected. Array form so we can query
            -- "show me all queries that had a CPF" via `'CPF' = ANY(pii_types_found)`.
            pii_types_found TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],

            n_matches       INTEGER NOT NULL DEFAULT 0,

            -- Free-form metadata (for future schema additions without
            -- migration. Use sparingly.)
            metadata        JSONB
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_pii_audit_ts ON pii_audit_log (ts DESC);")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pii_audit_types
        ON pii_audit_log USING GIN (pii_types_found);
    """)

    # =====================================================================
    # users — Phase 10c schema-only (no code consumes yet)
    # =====================================================================
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                  TEXT PRIMARY KEY,             -- Clerk user_id (sub claim)
            email               TEXT NOT NULL UNIQUE,
            email_verified      BOOLEAN NOT NULL DEFAULT FALSE,
            full_name           TEXT,
            first_name          TEXT,
            last_name           TEXT,
            image_url           TEXT,
            -- Whether this user is the project operator (set via env at sign-in)
            is_operator         BOOLEAN NOT NULL DEFAULT FALSE,
            -- LGPD: lawful basis declaration at signup (Phase 9 lawyer review will
            -- shape what this enum looks like exactly).
            lawful_basis        TEXT,
            consent_at          TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at        TIMESTAMPTZ
        );
    """)

    # =====================================================================
    # conversations — Phase 10c schema-only (per-user chat history)
    # =====================================================================
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_user_ts
        ON conversations (user_id, last_message_at DESC);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id     UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            role                TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),

            -- Redacted text (Phase 4.2 PII pipeline runs before storage)
            content_redacted    TEXT NOT NULL,

            -- For assistant messages: structured answer body (citations, refusal_reason,
            -- cost, classified_type, etc.). NULL for user / system messages.
            answer_json         JSONB,

            -- Cross-reference to the pii_audit_log row for the redaction event
            pii_audit_id        BIGINT REFERENCES pii_audit_log(id) ON DELETE SET NULL
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversation_messages_conv_ts
        ON conversation_messages (conversation_id, ts);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_messages;")
    op.execute("DROP TABLE IF EXISTS conversations;")
    op.execute("DROP TABLE IF EXISTS users;")
    op.execute("DROP TABLE IF EXISTS pii_audit_log;")
    op.execute("DROP TABLE IF EXISTS merged_proposals;")
    op.execute("DROP TABLE IF EXISTS proposals;")
