"""Phase 10c — per-user conversation history (Postgres-backed).

Schema: see migrations/versions/20260521_0001_initial_schema.py
  - users                   (Clerk user_id PK + email + profile + LGPD basis)
  - conversations           (UUID PK, user_id FK, title, last_message_at)
  - conversation_messages   (UUID PK, conversation_id FK, role, content_redacted,
                             answer_json, pii_audit_id)

Design choices:

  * **JIT user upsert.** Rather than upserting on every /v1/ask auth-dep
    call (wasteful), we upsert the user lazily right before we need the
    users.id as the FK on conversations. The same call also touches
    last_seen_at so we have basic activity telemetry without webhooks.
  * **Owner-scoped reads.** Every read function takes the caller's
    user_id and the SQL filters by it. There is NO admin/operator
    bypass — conversation history is per-user only. A future "operator
    audit" feature would be a separate function with an explicit
    operator-only HTTP gate.
  * **Title from first message.** Title is auto-set to the truncated
    first redacted user message when the conversation is created. An
    LLM-summary upgrade (Phase 10c.2) would replace this with a
    semantic summary; for v1, truncation is enough to distinguish rows
    in the sidebar.
  * **pii_audit_id = NULL in v1.** The conversation_messages schema has
    an optional FK to pii_audit_log. v1 leaves it NULL; the redacted
    text is stored directly in content_redacted, and the cross-reference
    to the audit row is a Phase 14.1 follow-up.
  * **JSONB for answer_json.** Storing the full AskResponse JSON keeps
    historical answers viewable as they were rendered (citations,
    refusal_reason, etc.) — schema additions on AskResponse won't break
    old rows.

The legitimate-interest lawful_basis default lines up with the sign-in
page footer copy (Phase 14.6). When Phase 9 (lawyer review) refines
the LGPD posture, that default may change to "consent" + a checkbox
gate; the column already exists.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from rag_leis.db import get_conn

# Auto-title cap. 60 chars fits comfortably on a 260px-wide sidebar
# entry without truncation; longer queries get a tail ellipsis. The
# title is just a label — full content lives in conversation_messages.
TITLE_MAX_LEN = 60

# Default lawful basis on lazy upsert. Matches the sign-in footer copy
# declaring legitimate interest for audit + future product features.
DEFAULT_LAWFUL_BASIS = "legitimate_interest"

Role = Literal["user", "assistant", "system"]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Conversation:
    """Sidebar-row shape — what GET /v1/conversations returns. Doesn't
    include the messages; that's a separate fetch via get_conversation."""

    id: str  # UUID hex (with dashes — psycopg returns canonical form)
    user_id: str
    title: str
    created_at: str  # ISO-8601 with timezone offset
    last_message_at: str
    message_count: int = 0


@dataclass(frozen=True)
class Message:
    """One row of conversation_messages.

    For role='user', `answer_json` is None and `content_redacted` holds
    the post-redaction query text.
    For role='assistant', `content_redacted` is the answer text and
    `answer_json` is the full AskResponse dump (citations, refusal_reason,
    cost, etc.) — useful for re-rendering historic answers without
    re-running the pipeline.
    """

    id: str
    conversation_id: str
    ts: str
    role: Role
    content_redacted: str
    answer_json: dict | None = field(default=None)
    pii_audit_id: int | None = field(default=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(value: Any) -> str:
    """Postgres TIMESTAMPTZ → ISO-8601 string. Handles psycopg's datetime
    objects and the string fallback for any future driver swap."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _title_from_query(query: str) -> str:
    """Truncate the (redacted) first user message to TITLE_MAX_LEN. The
    ellipsis is a real Unicode character (U+2026) so it counts as one
    glyph in CSS layout calcs."""
    q = query.strip().replace("\n", " ")
    if len(q) <= TITLE_MAX_LEN:
        return q
    return q[: TITLE_MAX_LEN - 1].rstrip() + "…"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Users (Phase 10c lazy upsert)
# ---------------------------------------------------------------------------


def upsert_user(
    *,
    user_id: str,
    email: str,
    image_url: str = "",
    full_name: str = "",
    first_name: str = "",
    last_name: str = "",
    is_operator: bool = False,
    lawful_basis: str = DEFAULT_LAWFUL_BASIS,
) -> None:
    """Insert or refresh a users row.

    Idempotent: a returning user UPDATEs last_seen_at + profile fields
    (Clerk profile may have changed — name updates, avatar refresh).
    `consent_at` is set ONCE on first insert so we have a stable record
    of when the lawful_basis was first asserted.
    """
    if not user_id:
        raise ValueError("user_id is required for upsert_user")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (
                id, email, full_name, first_name, last_name, image_url,
                is_operator, lawful_basis, consent_at, last_seen_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, NOW(), NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                email        = EXCLUDED.email,
                full_name    = EXCLUDED.full_name,
                first_name   = EXCLUDED.first_name,
                last_name    = EXCLUDED.last_name,
                image_url    = EXCLUDED.image_url,
                is_operator  = EXCLUDED.is_operator,
                last_seen_at = NOW()
            """,
            (
                user_id, email, full_name or None, first_name or None,
                last_name or None, image_url or None, is_operator,
                lawful_basis,
            ),
        )


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


def create_conversation(*, user_id: str, title: str) -> str:
    """Insert a new conversation row. Returns the UUID as a string.

    The caller is responsible for having upsert_user'd first — the FK
    on conversations.user_id will fail otherwise. /v1/ask does both in
    sequence before appending messages.
    """
    new_id = str(uuid.uuid4())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conversations (id, user_id, title, created_at, last_message_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            """,
            (new_id, user_id, title),
        )
    return new_id


def create_conversation_from_first_query(*, user_id: str, redacted_query: str) -> str:
    """Convenience wrapper: title <- truncated redacted query."""
    return create_conversation(
        user_id=user_id,
        title=_title_from_query(redacted_query) or "(sem título)",
    )


def touch_conversation(*, conversation_id: str) -> None:
    """Bump last_message_at to NOW(). Called after each append_message
    so the sidebar sort key (last_message_at DESC) tracks activity."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE conversations SET last_message_at = NOW() WHERE id = %s",
            (conversation_id,),
        )


def conversation_belongs_to(*, conversation_id: str, user_id: str) -> bool:
    """True iff the conversation exists AND is owned by the given user.

    Used as the access guard before appending to a caller-supplied
    conversation_id — otherwise a malicious client could pass another
    user's id and bleed turns into someone else's history. Cheap point
    lookup (PK index on conversations.id).
    """
    if not conversation_id or not user_id:
        return False
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        )
        return cur.fetchone() is not None


def list_conversations(*, user_id: str, limit: int = 50) -> list[Conversation]:
    """Return the user's conversations ordered most-recent-first.

    The message_count comes from a correlated subquery — small enough
    that it doesn't warrant a materialized counter column. If sidebar
    perf ever becomes a concern, denormalize into conversations.n_messages
    + maintain via trigger.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                c.id, c.user_id, c.title, c.created_at, c.last_message_at,
                COALESCE((
                    SELECT COUNT(*) FROM conversation_messages m
                    WHERE m.conversation_id = c.id
                ), 0) AS message_count
            FROM conversations c
            WHERE c.user_id = %s
            ORDER BY c.last_message_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
    return [
        Conversation(
            id=str(r[0]),
            user_id=r[1],
            title=r[2] or "(sem título)",
            created_at=_iso(r[3]),
            last_message_at=_iso(r[4]),
            message_count=int(r[5] or 0),
        )
        for r in rows
    ]


def get_conversation(
    *, conversation_id: str, user_id: str
) -> tuple[Conversation, list[Message]] | None:
    """Load a conversation + its messages, scoped to the calling user.

    Returns None if the conversation doesn't exist OR if it does exist
    but is owned by a different user. Same return shape for both cases
    so the HTTP layer can collapse to a 404 without distinguishing
    (which would leak "this conversation exists, you just can't see it").
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, title, created_at, last_message_at
            FROM conversations
            WHERE id = %s AND user_id = %s
            """,
            (conversation_id, user_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        conv = Conversation(
            id=str(row[0]),
            user_id=row[1],
            title=row[2] or "(sem título)",
            created_at=_iso(row[3]),
            last_message_at=_iso(row[4]),
        )

        cur.execute(
            """
            SELECT id, conversation_id, ts, role, content_redacted,
                   answer_json, pii_audit_id
            FROM conversation_messages
            WHERE conversation_id = %s
            ORDER BY ts ASC, id ASC
            """,
            (conversation_id,),
        )
        msg_rows = cur.fetchall()

    messages = [
        Message(
            id=str(mr[0]),
            conversation_id=str(mr[1]),
            ts=_iso(mr[2]),
            role=mr[3],
            content_redacted=mr[4],
            # psycopg JSONB → dict directly; defensive cast for safety
            answer_json=mr[5] if isinstance(mr[5], dict) else (
                json.loads(mr[5]) if mr[5] is not None else None
            ),
            pii_audit_id=mr[6],
        )
        for mr in msg_rows
    ]
    return conv, messages


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def append_message(
    *,
    conversation_id: str,
    role: Role,
    content_redacted: str,
    answer_json: dict | None = None,
    pii_audit_id: int | None = None,
) -> str:
    """Insert one conversation_messages row. Returns the new UUID.

    The Phase 14.1 follow-up will populate pii_audit_id; v1 leaves it
    None.
    """
    new_id = str(uuid.uuid4())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conversation_messages (
                id, conversation_id, ts, role,
                content_redacted, answer_json, pii_audit_id
            ) VALUES (
                %s, %s, NOW(), %s,
                %s, %s, %s
            )
            """,
            (
                new_id,
                conversation_id,
                role,
                content_redacted,
                Jsonb(answer_json) if answer_json is not None else None,
                pii_audit_id,
            ),
        )
    return new_id


# ---------------------------------------------------------------------------
# JSON-friendly serialization for the HTTP layer
# ---------------------------------------------------------------------------


def conversation_to_dict(c: Conversation) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "created_at": c.created_at,
        "last_message_at": c.last_message_at,
        "message_count": c.message_count,
    }


def message_to_dict(m: Message) -> dict:
    return {
        "id": m.id,
        "ts": m.ts,
        "role": m.role,
        "content_redacted": m.content_redacted,
        "answer_json": m.answer_json,
    }
