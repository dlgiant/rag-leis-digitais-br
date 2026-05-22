"""Phase 10c — tests for rag_leis.conversations repo.

Run with DATABASE_URL_TEST pointing at a Neon dev branch (NOT
production). Schema is migrated once per session.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from rag_leis import conversations as convos
from rag_leis import db

_HAS_DB = bool(os.environ.get("DATABASE_URL_TEST"))

skip_if_no_db = pytest.mark.skipif(
    not _HAS_DB,
    reason="Set DATABASE_URL_TEST (separate Neon branch) to run DB-backed tests",
)

_schema_migrated = False


def _ensure_schema_migrated_once() -> None:
    """Same pattern as tests/test_admin_endpoints.py — migrate once per
    pytest session against DATABASE_URL_TEST."""
    global _schema_migrated
    if _schema_migrated:
        return
    from alembic import command
    from alembic.config import Config
    project_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "migrations"))
    command.upgrade(cfg, "head")
    _schema_migrated = True


@pytest.fixture(autouse=True)
def db_state():
    """Truncate the Phase 10c tables before each test for isolation.

    Order matters: conversation_messages depends on conversations
    depends on users — TRUNCATE … CASCADE handles the FKs.
    """
    if not _HAS_DB:
        yield
        return
    if not db.is_configured():
        db.init_pool(url=os.environ["DATABASE_URL_TEST"])
    _ensure_schema_migrated_once()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE conversation_messages, conversations, users RESTART IDENTITY CASCADE"
        )
    yield


# ---------------------------------------------------------------------------
# upsert_user
# ---------------------------------------------------------------------------


@skip_if_no_db
def test_upsert_user_inserts_then_updates_idempotent():
    """First call inserts; second call with new profile updates fields
    + bumps last_seen_at; consent_at stays from the first insert."""
    convos.upsert_user(
        user_id="user_a", email="a@example.test",
        full_name="Alice Old", first_name="Alice",
    )

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT email, full_name, consent_at, last_seen_at FROM users WHERE id = %s",
            ("user_a",),
        )
        row1 = cur.fetchone()
    assert row1 is not None
    assert row1[0] == "a@example.test"
    assert row1[1] == "Alice Old"
    consent_first = row1[2]
    assert consent_first is not None  # set on insert

    # Re-upsert with a new name.
    convos.upsert_user(
        user_id="user_a", email="a@example.test",
        full_name="Alice New", first_name="Alice",
    )

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT full_name, consent_at FROM users WHERE id = %s",
            ("user_a",),
        )
        row2 = cur.fetchone()
    assert row2 is not None
    assert row2[0] == "Alice New"
    # consent_at is set ONCE on first insert; the upsert doesn't touch it.
    # Equality on TIMESTAMPTZ should hold since we didn't UPDATE the column.
    assert row2[1] == consent_first


@skip_if_no_db
def test_upsert_user_requires_user_id():
    """Empty user_id is a programmer error — fail loudly."""
    with pytest.raises(ValueError):
        convos.upsert_user(user_id="", email="x@example.test")


# ---------------------------------------------------------------------------
# create_conversation + append_message + list_conversations
# ---------------------------------------------------------------------------


@skip_if_no_db
def test_create_conversation_and_append_messages():
    """Happy path: user → conversation → two messages."""
    convos.upsert_user(user_id="user_b", email="b@example.test")
    conv_id = convos.create_conversation(user_id="user_b", title="Test thread")
    assert conv_id  # UUID string

    msg_id_u = convos.append_message(
        conversation_id=conv_id, role="user", content_redacted="o que diz a LGPD?",
    )
    msg_id_a = convos.append_message(
        conversation_id=conv_id, role="assistant",
        content_redacted="A LGPD …",
        answer_json={"citations": ["urn:lex:br:lei:2018:13709"], "refused": False},
    )
    assert msg_id_u and msg_id_a and msg_id_u != msg_id_a

    # Verify both messages present + answer_json round-trips as JSONB
    result = convos.get_conversation(conversation_id=conv_id, user_id="user_b")
    assert result is not None
    conv, msgs = result
    assert conv.id == conv_id
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"
    assert msgs[1].answer_json == {
        "citations": ["urn:lex:br:lei:2018:13709"], "refused": False,
    }


@skip_if_no_db
def test_create_conversation_from_first_query_truncates_title():
    """Long queries get a truncated title; short ones come through as-is."""
    convos.upsert_user(user_id="user_c", email="c@example.test")
    long_q = "a " * 200  # 400 chars
    conv_id = convos.create_conversation_from_first_query(
        user_id="user_c", redacted_query=long_q,
    )
    result = convos.get_conversation(conversation_id=conv_id, user_id="user_c")
    assert result is not None
    assert len(result[0].title) <= convos.TITLE_MAX_LEN
    assert result[0].title.endswith("…")


@skip_if_no_db
def test_list_conversations_orders_by_recent_activity():
    """list_conversations is sorted by last_message_at DESC. We touch
    the older conversation to force it back to the top."""
    convos.upsert_user(user_id="user_d", email="d@example.test")

    older = convos.create_conversation(user_id="user_d", title="older")
    newer = convos.create_conversation(user_id="user_d", title="newer")

    # Right after creation, newer is the top of the list.
    items = convos.list_conversations(user_id="user_d")
    assert [c.id for c in items] == [newer, older]

    # Touch the older conv → it should bubble up.
    convos.touch_conversation(conversation_id=older)
    items_after = convos.list_conversations(user_id="user_d")
    assert items_after[0].id == older


@skip_if_no_db
def test_list_conversations_scopes_by_user():
    """list_conversations must NEVER return another user's threads."""
    convos.upsert_user(user_id="user_e", email="e@example.test")
    convos.upsert_user(user_id="user_f", email="f@example.test")
    convos.create_conversation(user_id="user_e", title="e thread")
    convos.create_conversation(user_id="user_f", title="f thread")

    e_items = convos.list_conversations(user_id="user_e")
    assert len(e_items) == 1 and e_items[0].title == "e thread"

    f_items = convos.list_conversations(user_id="user_f")
    assert len(f_items) == 1 and f_items[0].title == "f thread"


# ---------------------------------------------------------------------------
# get_conversation — owner-scoping is the security boundary
# ---------------------------------------------------------------------------


@skip_if_no_db
def test_get_conversation_returns_none_for_wrong_owner():
    """The security guarantee: get_conversation with mismatched user_id
    returns None (HTTP layer translates to 404). No "exists-but-forbidden"
    leak."""
    convos.upsert_user(user_id="user_g", email="g@example.test")
    convos.upsert_user(user_id="user_h", email="h@example.test")
    conv_id = convos.create_conversation(user_id="user_g", title="g's thread")

    # Owner can read it.
    assert convos.get_conversation(conversation_id=conv_id, user_id="user_g") is not None
    # Stranger cannot.
    assert convos.get_conversation(conversation_id=conv_id, user_id="user_h") is None


@skip_if_no_db
def test_get_conversation_returns_none_for_unknown_id():
    """get_conversation on a non-existent id is the same return-shape
    as on an owner-mismatch — both collapse to 404."""
    convos.upsert_user(user_id="user_i", email="i@example.test")
    assert (
        convos.get_conversation(
            conversation_id="00000000-0000-0000-0000-000000000000",
            user_id="user_i",
        )
        is None
    )


# ---------------------------------------------------------------------------
# conversation_belongs_to — the access guard before appending
# ---------------------------------------------------------------------------


@skip_if_no_db
def test_conversation_belongs_to_owner_only():
    """The /v1/ask path calls conversation_belongs_to before appending
    to a caller-supplied conversation_id — guard against history hijacks."""
    convos.upsert_user(user_id="user_j", email="j@example.test")
    convos.upsert_user(user_id="user_k", email="k@example.test")
    conv_id = convos.create_conversation(user_id="user_j", title="j")

    assert convos.conversation_belongs_to(
        conversation_id=conv_id, user_id="user_j",
    )
    assert not convos.conversation_belongs_to(
        conversation_id=conv_id, user_id="user_k",
    )
    # Empty inputs are always False — defensive.
    assert not convos.conversation_belongs_to(conversation_id="", user_id="user_j")
    assert not convos.conversation_belongs_to(conversation_id=conv_id, user_id="")
