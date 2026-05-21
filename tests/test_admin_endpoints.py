"""Phase 11.0 — Tests for the `/v1/admin/*` read-only endpoints.

JWT verification is exercised with a real RS256 signature: tests
generate an ephemeral RSA keypair per session, set the public key
as `CLERK_JWT_KEY`, and sign test tokens with the private key.
This exercises the full `jwt.decode` path (no mocking of pyjwt).

Covers:
  - 401 when no Authorization header
  - 401 when token signature is bad
  - 401 when token is expired
  - 403 when email is not in RAG_ADMIN_ALLOWLIST
  - 200 happy path: list / get / chunk
  - 404 on unknown query_id and unknown URN
  - is_operator: True when email matches RAG_OPERATOR_EMAIL,
    False otherwise
"""
from __future__ import annotations

import os as _os
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from rag_leis import eval_loader

# Lazy-import the app inside fixtures so env vars are set before
# FastAPI's startup hook runs.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def keypair():
    """Generate an ephemeral RS256 keypair for signing test JWTs."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_private = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pem_public = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return {"private": pem_private, "public": pem_public}


OPERATOR_EMAIL = "operator@example.test"
LAWYER_EMAIL = "lawyer@example.test"
INTRUDER_EMAIL = "intruder@example.test"


@pytest.fixture(autouse=True)
def env_config(monkeypatch, keypair):
    """Configure env vars for every test: pubkey, allowlist, operator."""
    monkeypatch.setenv("CLERK_JWT_KEY", keypair["public"])
    monkeypatch.setenv(
        "RAG_ADMIN_ALLOWLIST",
        f"{OPERATOR_EMAIL},{LAWYER_EMAIL}",
    )
    monkeypatch.setenv("RAG_OPERATOR_EMAIL", OPERATOR_EMAIL)
    # No CLERK_AUDIENCE set → audience check skipped (matches dev-mode).
    monkeypatch.delenv("CLERK_AUDIENCE", raising=False)
    # Reset the chunks cache so each test gets a fresh load.
    eval_loader.reset_caches()


# Phase 11.2.1 — DB fixture. Tests that hit /v1/admin/* endpoints
# need a real Postgres because proposals.py now writes via SQL.
# If DATABASE_URL_TEST isn't set, skip those tests with a clear
# message — the auth-only tests (no DB writes) still run.
_HAS_DB = bool(_os.environ.get("DATABASE_URL_TEST"))

skip_if_no_db = pytest.mark.skipif(
    not _HAS_DB,
    reason="Set DATABASE_URL_TEST (separate Neon branch) to run DB-backed tests",
)


@pytest.fixture(autouse=True)
def db_state():
    """Per-test DB isolation: ensure schema is migrated, then truncate
    proposals + merged_proposals + pii_audit_log before each test.

    Skips silently if DATABASE_URL_TEST isn't set — tests that need DB
    are individually marked with @skip_if_no_db.
    """
    if not _HAS_DB:
        yield
        return

    from rag_leis import db
    if not db.is_configured():
        db.init_pool(url=_os.environ["DATABASE_URL_TEST"])

    _ensure_schema_migrated_once()

    # Truncate every DB-managed Phase 11.2.1 table for isolation
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE proposals, merged_proposals, pii_audit_log RESTART IDENTITY"
        )

    yield


_schema_migrated = False


def _ensure_schema_migrated_once() -> None:
    """Run `alembic upgrade head` exactly once per pytest session
    against DATABASE_URL_TEST."""
    global _schema_migrated
    if _schema_migrated:
        return
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    project_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "migrations"))
    command.upgrade(cfg, "head")
    _schema_migrated = True


@pytest.fixture
def client():
    """TestClient against the FastAPI app. Imported lazily so env vars
    set by other fixtures land before lifespan startup."""
    from rag_leis.server import app
    return TestClient(app)


def make_token(
    *,
    keypair,
    email: str | None,
    exp_in_seconds: int = 300,
) -> str:
    """Sign a test JWT with the given email + expiration offset."""
    now = int(time.time())
    payload: dict = {
        "iat": now,
        "exp": now + exp_in_seconds,
        "sub": "user_test",
    }
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, keypair["private"], algorithm="RS256")


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


def test_no_auth_header_returns_401(client):
    r = client.get("/v1/admin/eval/queries")
    assert r.status_code == 401
    assert "bearer" in r.json()["detail"].lower()


def test_empty_bearer_returns_401(client):
    r = client.get("/v1/admin/eval/queries", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


def test_bad_signature_returns_401(client, keypair):
    """Sign with a DIFFERENT keypair than the verifier uses."""
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    bad_token = jwt.encode(
        {"iat": int(time.time()), "exp": int(time.time()) + 60, "email": LAWYER_EMAIL},
        other_pem,
        algorithm="RS256",
    )
    r = client.get("/v1/admin/eval/queries", headers=auth_header(bad_token))
    assert r.status_code == 401


def test_expired_token_returns_401(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL, exp_in_seconds=-60)
    r = client.get("/v1/admin/eval/queries", headers=auth_header(token))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_missing_email_claim_returns_401(client, keypair):
    token = make_token(keypair=keypair, email=None)
    r = client.get("/v1/admin/eval/queries", headers=auth_header(token))
    assert r.status_code == 401
    assert "email" in r.json()["detail"].lower()


def test_email_not_in_allowlist_returns_403(client, keypair):
    token = make_token(keypair=keypair, email=INTRUDER_EMAIL)
    r = client.get("/v1/admin/eval/queries", headers=auth_header(token))
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Happy path — GET /v1/admin/eval/queries
# ---------------------------------------------------------------------------


def test_list_queries_returns_paginated_rows(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.get("/v1/admin/eval/queries?limit=5&offset=0", headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 100  # we have 104+ rows
    assert body["limit"] == 5
    assert body["offset"] == 0
    assert len(body["rows"]) == 5
    # Each row has the expected shape
    r0 = body["rows"][0]
    for key in ["id", "query", "qtype", "core_urns", "supporting_urns", "notes"]:
        assert key in r0
    # IDs are stable hex strings of length 12
    assert len(r0["id"]) == 12
    assert all(c in "0123456789abcdef" for c in r0["id"])


def test_list_queries_filters_by_qtype(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.get("/v1/admin/eval/queries?qtype=definicao", headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()
    assert body["qtype_filter"] == "definicao"
    assert all(row["qtype"] == "definicao" for row in body["rows"])


def test_list_queries_echoes_viewer_identity(client, keypair):
    operator_token = make_token(keypair=keypair, email=OPERATOR_EMAIL)
    lawyer_token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r_op = client.get("/v1/admin/eval/queries?limit=1", headers=auth_header(operator_token))
    r_law = client.get("/v1/admin/eval/queries?limit=1", headers=auth_header(lawyer_token))
    assert r_op.json()["viewer"] == {"email": OPERATOR_EMAIL, "is_operator": True}
    assert r_law.json()["viewer"] == {"email": LAWYER_EMAIL, "is_operator": False}


# ---------------------------------------------------------------------------
# Happy path — GET /v1/admin/eval/queries/{id}
# ---------------------------------------------------------------------------


def test_get_query_by_id_returns_expanded_chunks(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    # Find a real row first
    r = client.get("/v1/admin/eval/queries?limit=1", headers=auth_header(token))
    first_id = r.json()["rows"][0]["id"]
    # Now fetch it
    r2 = client.get(f"/v1/admin/eval/queries/{first_id}", headers=auth_header(token))
    assert r2.status_code == 200
    body = r2.json()
    assert body["id"] == first_id
    assert "gold_chunks" in body
    # Each chunk has the expected shape
    if body["gold_chunks"]:
        c0 = body["gold_chunks"][0]
        for key in ["urn", "document_urn", "label", "nav", "caput", "text", "kind"]:
            assert key in c0


def test_get_query_unknown_id_returns_404(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.get("/v1/admin/eval/queries/deadbeef0000", headers=auth_header(token))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Happy path — GET /v1/admin/chunks/{urn}
# ---------------------------------------------------------------------------


def test_get_chunk_by_urn(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    # Use a known-good URN — LGPD art 5 inc 1
    urn = "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1"
    r = client.get(f"/v1/admin/chunks/{urn}", headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()
    assert body["urn"] == urn
    assert body["kind"] == "inciso"
    assert "dado pessoal" in body["text"].lower()


def test_get_chunk_unknown_urn_returns_404(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    urn = "urn:lex:br:federal:lei:2099-01-01;99999~art1"
    r = client.get(f"/v1/admin/chunks/{urn}", headers=auth_header(token))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Operator flag
# ---------------------------------------------------------------------------


def test_is_operator_true_for_operator_email(client, keypair):
    token = make_token(keypair=keypair, email=OPERATOR_EMAIL)
    r = client.get("/v1/admin/eval/queries?limit=1", headers=auth_header(token))
    assert r.status_code == 200
    assert r.json()["viewer"]["is_operator"] is True


def test_is_operator_false_for_lawyer_email(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.get("/v1/admin/eval/queries?limit=1", headers=auth_header(token))
    assert r.status_code == 200
    assert r.json()["viewer"]["is_operator"] is False


# ---------------------------------------------------------------------------
# Phase 11.2 — review submission (write path)
# ---------------------------------------------------------------------------


def _first_query_id(client, keypair) -> str:
    """Helper: get a real query_id to use in review tests."""
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.get("/v1/admin/eval/queries?limit=1", headers=auth_header(token))
    return r.json()["rows"][0]["id"]


@skip_if_no_db
def test_submit_review_happy_path(client, keypair):
    """Lawyer submits a verdict; proposal landed in Postgres."""
    qid = _first_query_id(client, keypair)
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/review",
        json={
            "verdict": "correct",
            "notes": "Confirmed against LGPD art. 5, I.",
        },
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    p = body["proposal"]
    assert p["kind"] == "review"
    assert p["verdict"] == "correct"
    assert p["query_id"] == qid
    assert p["reviewer_email"] == LAWYER_EMAIL
    assert p["is_operator"] is False
    assert p["notes"] == "Confirmed against LGPD art. 5, I."
    # Verify it landed in Postgres
    from rag_leis import proposals
    db_rows = proposals.load_all_proposals()
    assert len(db_rows) == 1
    assert db_rows[0].id == p["id"]
    assert db_rows[0].verdict == "correct"


@skip_if_no_db
def test_submit_review_with_suggested_urns(client, keypair):
    """Suggested URNs are persisted in the proposal."""
    qid = _first_query_id(client, keypair)
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/review",
        json={
            "verdict": "incorrect",
            "notes": "Gold URN is wrong; LGPD art 5;inc1 should be art 5;inc2.",
            "suggested_gold_urns": [
                "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2",
            ],
            "suggested_classified_type": "definicao",
        },
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    p = r.json()["proposal"]
    assert p["suggested_gold_urns"] == [
        "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2",
    ]
    assert p["suggested_classified_type"] == "definicao"
    assert p["verdict"] == "incorrect"


@skip_if_no_db
def test_submit_review_unknown_query_id_returns_404(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        "/v1/admin/eval/queries/deadbeef0000/review",
        json={"verdict": "correct", "notes": "test"},
        headers=auth_header(token),
    )
    assert r.status_code == 404


@skip_if_no_db
def test_submit_review_invalid_verdict_returns_422(client, keypair):
    qid = _first_query_id(client, keypair)
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/review",
        json={"verdict": "not_a_real_verdict", "notes": "test"},
        headers=auth_header(token),
    )
    assert r.status_code == 422  # Pydantic Literal validation


@skip_if_no_db
def test_submit_review_requires_auth(client, keypair):
    qid = _first_query_id(client, keypair)
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/review",
        json={"verdict": "correct", "notes": ""},
    )
    assert r.status_code == 401


@skip_if_no_db
def test_submit_review_not_in_allowlist_returns_403(client, keypair):
    qid = _first_query_id(client, keypair)
    token = make_token(keypair=keypair, email=INTRUDER_EMAIL)
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/review",
        json={"verdict": "correct", "notes": ""},
        headers=auth_header(token),
    )
    assert r.status_code == 403


@skip_if_no_db
def test_submit_review_marks_operator_correctly(client, keypair):
    """Operator submits a review → is_operator: true in the proposal."""
    qid = _first_query_id(client, keypair)
    token = make_token(keypair=keypair, email=OPERATOR_EMAIL)
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/review",
        json={"verdict": "correct", "notes": "operator confirming"},
        headers=auth_header(token),
    )
    assert r.status_code == 200
    assert r.json()["proposal"]["is_operator"] is True


# ---------------------------------------------------------------------------
# Phase 11.2 — proposals queue (operator-only)
# ---------------------------------------------------------------------------


@skip_if_no_db
def test_list_proposals_operator_only(client, keypair):
    """Lawyer cannot list proposals (operator-only endpoint)."""
    lawyer_token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.get("/v1/admin/proposals", headers=auth_header(lawyer_token))
    assert r.status_code == 403


@skip_if_no_db
def test_list_proposals_empty(client, keypair):
    """Fresh test fixture → no proposals yet."""
    operator_token = make_token(keypair=keypair, email=OPERATOR_EMAIL)
    r = client.get("/v1/admin/proposals", headers=auth_header(operator_token))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["proposals"] == []


@skip_if_no_db
def test_list_proposals_after_submissions(client, keypair):
    """Submit two reviews → both appear in /proposals listing."""
    qid = _first_query_id(client, keypair)
    lawyer_token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    operator_token = make_token(keypair=keypair, email=OPERATOR_EMAIL)
    # Submit two reviews
    for verdict, notes in [("correct", "first"), ("incorrect", "second")]:
        r = client.post(
            f"/v1/admin/eval/queries/{qid}/review",
            json={"verdict": verdict, "notes": notes},
            headers=auth_header(lawyer_token),
        )
        assert r.status_code == 200, r.text
    # Operator lists
    r = client.get("/v1/admin/proposals", headers=auth_header(operator_token))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {p["notes"] for p in body["proposals"]} == {"first", "second"}
    assert all(p["query_id"] == qid for p in body["proposals"])
    assert all(p["kind"] == "review" for p in body["proposals"])


@skip_if_no_db
def test_list_proposals_filters_merged(client, keypair):
    """Proposals whose IDs are in merged_proposals don't show up as pending."""
    qid = _first_query_id(client, keypair)
    lawyer_token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    operator_token = make_token(keypair=keypair, email=OPERATOR_EMAIL)
    # Submit a proposal
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/review",
        json={"verdict": "correct", "notes": "to be merged"},
        headers=auth_header(lawyer_token),
    )
    proposal_id = r.json()["proposal"]["id"]
    # Pre-merge listing shows it
    r = client.get("/v1/admin/proposals", headers=auth_header(operator_token))
    assert r.json()["total"] == 1
    # Mark as merged via the proposals helper (Phase 11.4's merge tool
    # uses this same call site).
    from rag_leis import proposals
    proposals.mark_merged(proposal_id, merged_by=OPERATOR_EMAIL)
    # Post-merge listing skips it
    r = client.get("/v1/admin/proposals", headers=auth_header(operator_token))
    assert r.json()["total"] == 0
