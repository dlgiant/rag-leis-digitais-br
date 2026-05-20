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
