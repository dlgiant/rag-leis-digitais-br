"""Phase 10c — end-to-end tests for the conversation endpoints +
persistence behavior on /v1/ask.

These tests require DATABASE_URL_TEST (Neon dev branch) — the JWT
path of /v1/ask now writes to Postgres. Without a DB the persistence
silently no-ops; tests that assert "row exists" are marked
@skip_if_no_db.

Verifies:
  * GET /v1/conversations returns only the caller's threads
  * GET /v1/conversations/{id} 404s on owner mismatch (no leak)
  * /v1/ask with JWT persists user + assistant rows
  * /v1/ask with X-API-Key path does NOT persist (no users row)
  * /v1/ask honors a caller-supplied conversation_id when owned;
    silently rotates to a new one when foreign (history-hijack guard)
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from rag_leis import conversations as convos
from rag_leis import db, obs
from rag_leis.rag import RAGAnswer
from rag_leis.server import app, get_pipeline, limiter

_HAS_DB = bool(os.environ.get("DATABASE_URL_TEST"))

skip_if_no_db = pytest.mark.skipif(
    not _HAS_DB,
    reason="Set DATABASE_URL_TEST (separate Neon branch) to run DB-backed tests",
)


_schema_migrated = False


def _ensure_schema_migrated_once() -> None:
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


# ---------------------------------------------------------------------------
# Pipeline stub — returns a fixed answer; carries pii_redacted_query so the
# persistence path has something to write into content_redacted.
# ---------------------------------------------------------------------------


class _StubPipeline:
    def __init__(self, answer: RAGAnswer):
        self._answer = answer

    def answer(self, query: str, on_event=None) -> RAGAnswer:
        # Mirror the production behavior: the pipeline IS the source of
        # truth for the redacted query text. Our stub trivially echoes
        # the query (no PII in test queries).
        return RAGAnswer(
            answer=self._answer.answer,
            citations=list(self._answer.citations),
            unverified_claims=[],
            rejected_citations=[],
            refused=False,
            refusal_reason=None,
            raw_retrieval=[],
            flagged_vigencia=[],
            classified_type="definicao",
            classified_top_k=8,
            pii_types_redacted=[],
            pii_redacted_query=query,  # echo — no PII in tests
            hierarchy_warning=None,
            prose_citation_mismatches=[],
            prose_check_retried=False,
            sources_consulted_at={},
            cost_estimate_usd=0.0,
            tokens_used={"input_tokens": 0, "output_tokens": 0},
            llm_calls=0,
            latency_ms=10.0,
            rejected_irrelevant_citations=[],
        )


def _sample_answer(text: str = "resposta do stub") -> RAGAnswer:
    return RAGAnswer(
        answer=text,
        citations=["urn:lex:br:lei:2018:13709"],
        unverified_claims=[],
        rejected_citations=[],
        refused=False,
        refusal_reason=None,
        raw_retrieval=[],
        flagged_vigencia=[],
        classified_type="definicao",
        classified_top_k=8,
        pii_types_redacted=[],
        hierarchy_warning=None,
        prose_citation_mismatches=[],
        prose_check_retried=False,
        sources_consulted_at={},
        cost_estimate_usd=0.0,
        tokens_used={"input_tokens": 0, "output_tokens": 0},
        llm_calls=0,
        latency_ms=10.0,
        rejected_irrelevant_citations=[],
    )


# ---------------------------------------------------------------------------
# JWT keypair (module-scope: keygen is ~50ms)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return {"private": priv, "public": pub}


VALID_KEY = "rag_test_valid_key_phase10c"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch, keypair):
    monkeypatch.setenv("CLERK_JWT_KEY", keypair["public"])
    # Phase 17.3 — delenv works cleanly now that load_dotenv was
    # moved out of module-import in rag_leis.llm + .maritaca.
    monkeypatch.delenv("CLERK_AUDIENCE", raising=False)
    monkeypatch.setenv("RAG_API_KEYS", VALID_KEY)
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "1000")
    limiter.reset()
    obs.reset_for_tests()
    obs.configure(level="DEBUG", in_memory_spans=True)
    yield
    obs.reset_for_tests()


@pytest.fixture(autouse=True)
def db_state():
    """Truncate the Phase 10c tables before each test for isolation."""
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


@pytest.fixture
def client():
    stub = _StubPipeline(_sample_answer())
    app.dependency_overrides[get_pipeline] = lambda: stub
    app.state.pipeline = stub
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def make_token(
    *,
    keypair,
    sub: str = "user_test",
    email: str = "x@example.test",
    image_url: str = "",
    full_name: str = "",
    exp_in_seconds: int = 300,
) -> str:
    """Sign a Clerk-like session JWT. Phase 10c: includes profile fields
    (image_url, full_name) so the upsert has something to write."""
    now = int(time.time())
    payload: dict = {
        "iat": now,
        "exp": now + exp_in_seconds,
        "sub": sub,
        "email": email,
    }
    if image_url:
        payload["image_url"] = image_url
    if full_name:
        payload["full_name"] = full_name
    return jwt.encode(payload, keypair["private"], algorithm="RS256")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# /v1/ask persistence — JWT path writes; API-key path doesn't
# ---------------------------------------------------------------------------


@skip_if_no_db
def test_ask_with_jwt_persists_user_and_two_messages(client, keypair):
    """The happy path: JWT-authed /v1/ask creates a users row + a
    conversation + a user msg + an assistant msg, and returns the
    new conversation_id in the response."""
    token = make_token(
        keypair=keypair, sub="user_persisted", email="persist@example.test",
        full_name="Test Persist",
    )
    r = client.post(
        "/v1/ask",
        json={"query": "o que é dado pessoal na LGPD?"},
        headers=bearer(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    conv_id = body["conversation_id"]
    assert conv_id  # backend created and returned a new conversation

    # users row exists
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT email, full_name FROM users WHERE id = %s", ("user_persisted",))
        urow = cur.fetchone()
    assert urow is not None
    assert urow[0] == "persist@example.test"
    assert urow[1] == "Test Persist"

    # conversation + 2 messages persisted
    result = convos.get_conversation(
        conversation_id=conv_id, user_id="user_persisted",
    )
    assert result is not None
    conv, msgs = result
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[0].content_redacted == "o que é dado pessoal na LGPD?"
    assert msgs[1].role == "assistant"
    # The assistant message stores the full AskResponse JSON
    assert msgs[1].answer_json is not None
    assert msgs[1].answer_json["citations"] == ["urn:lex:br:lei:2018:13709"]


@skip_if_no_db
def test_ask_with_api_key_does_not_persist(client):
    """API-key callers (CI smoke tests, MCP) shouldn't create users rows
    or conversation history — they have no user identity to scope under."""
    r = client.post(
        "/v1/ask",
        json={"query": "anything"},
        headers={"X-API-Key": VALID_KEY},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conversation_id"] is None

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM conversations")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM conversation_messages")
        assert cur.fetchone()[0] == 0


@skip_if_no_db
def test_ask_appends_to_existing_owned_conversation(client, keypair):
    """A second /v1/ask with the same conversation_id (owned by caller)
    appends two more messages to the same thread instead of starting a new one."""
    token = make_token(keypair=keypair, sub="user_continuer", email="cont@example.test")
    r1 = client.post(
        "/v1/ask", json={"query": "primeira pergunta"}, headers=bearer(token),
    )
    conv_id = r1.json()["conversation_id"]
    assert conv_id

    r2 = client.post(
        "/v1/ask",
        json={"query": "segunda pergunta", "conversation_id": conv_id},
        headers=bearer(token),
    )
    assert r2.status_code == 200
    assert r2.json()["conversation_id"] == conv_id

    result = convos.get_conversation(
        conversation_id=conv_id, user_id="user_continuer",
    )
    assert result is not None
    _, msgs = result
    assert len(msgs) == 4  # 2 user + 2 assistant
    user_msgs = [m for m in msgs if m.role == "user"]
    assert [m.content_redacted for m in user_msgs] == [
        "primeira pergunta", "segunda pergunta",
    ]


@skip_if_no_db
def test_ask_rotates_when_caller_supplies_foreign_conversation_id(client, keypair):
    """If the caller passes a conversation_id owned by someone else,
    the backend silently creates a new conversation for the caller —
    NEVER bleeds the message into the other user's history."""
    # Set up: user_owner creates a conversation
    owner_token = make_token(keypair=keypair, sub="user_owner", email="own@example.test")
    r_owner = client.post(
        "/v1/ask", json={"query": "pergunta do dono"}, headers=bearer(owner_token),
    )
    owner_conv = r_owner.json()["conversation_id"]
    assert owner_conv

    # user_attacker tries to append to user_owner's conversation
    attacker_token = make_token(
        keypair=keypair, sub="user_attacker", email="atk@example.test",
    )
    r_atk = client.post(
        "/v1/ask",
        json={"query": "tentativa de hijack", "conversation_id": owner_conv},
        headers=bearer(attacker_token),
    )
    assert r_atk.status_code == 200
    atk_conv = r_atk.json()["conversation_id"]
    assert atk_conv  # got a conversation_id
    assert atk_conv != owner_conv  # but it's a DIFFERENT one (rotated)

    # The owner's conversation still has its original 2 messages — not 3.
    owner_result = convos.get_conversation(
        conversation_id=owner_conv, user_id="user_owner",
    )
    assert owner_result is not None
    assert len(owner_result[1]) == 2  # unchanged

    # The attacker's new conversation has the hijack attempt.
    atk_result = convos.get_conversation(
        conversation_id=atk_conv, user_id="user_attacker",
    )
    assert atk_result is not None
    assert atk_result[1][0].content_redacted == "tentativa de hijack"


# ---------------------------------------------------------------------------
# GET /v1/conversations — list endpoint
# ---------------------------------------------------------------------------


@skip_if_no_db
def test_list_conversations_returns_only_callers_threads(client, keypair):
    """Two users each create a conversation. Each calling GET /v1/conversations
    sees only their own."""
    t_alice = make_token(keypair=keypair, sub="user_alice", email="alice@example.test")
    t_bob = make_token(keypair=keypair, sub="user_bob", email="bob@example.test")
    client.post("/v1/ask", json={"query": "alice q"}, headers=bearer(t_alice))
    client.post("/v1/ask", json={"query": "bob q"}, headers=bearer(t_bob))

    r_alice = client.get("/v1/conversations", headers=bearer(t_alice))
    assert r_alice.status_code == 200
    alice_items = r_alice.json()["conversations"]
    assert len(alice_items) == 1
    assert alice_items[0]["title"] == "alice q"
    assert alice_items[0]["message_count"] == 2

    r_bob = client.get("/v1/conversations", headers=bearer(t_bob))
    assert r_bob.status_code == 200
    bob_items = r_bob.json()["conversations"]
    assert len(bob_items) == 1
    assert bob_items[0]["title"] == "bob q"


def test_list_conversations_requires_auth(client):
    r = client.get("/v1/conversations")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/conversations/{id} — load endpoint
# ---------------------------------------------------------------------------


@skip_if_no_db
def test_get_conversation_returns_messages_for_owner(client, keypair):
    t = make_token(keypair=keypair, sub="user_get", email="get@example.test")
    r1 = client.post("/v1/ask", json={"query": "primeira"}, headers=bearer(t))
    conv_id = r1.json()["conversation_id"]

    r = client.get(f"/v1/conversations/{conv_id}", headers=bearer(t))
    assert r.status_code == 200
    body = r.json()
    assert body["conversation"]["id"] == conv_id
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"


@skip_if_no_db
def test_get_conversation_returns_404_for_foreign_owner(client, keypair):
    """The cross-user fishing test — an attacker probing a known conv_id
    must get 404, not 200 (no leak that the conversation exists)."""
    t_owner = make_token(keypair=keypair, sub="user_o", email="o@example.test")
    t_other = make_token(keypair=keypair, sub="user_x", email="x@example.test")
    r1 = client.post("/v1/ask", json={"query": "secreto"}, headers=bearer(t_owner))
    conv_id = r1.json()["conversation_id"]

    r = client.get(f"/v1/conversations/{conv_id}", headers=bearer(t_other))
    assert r.status_code == 404


@skip_if_no_db
def test_get_conversation_returns_404_for_unknown_id(client, keypair):
    t = client.get(
        "/v1/conversations/00000000-0000-0000-0000-000000000000",
        headers=bearer(make_token(keypair=keypair, sub="user_z", email="z@example.test")),
    )
    assert t.status_code == 404


def test_get_conversation_requires_auth(client):
    r = client.get("/v1/conversations/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 401
