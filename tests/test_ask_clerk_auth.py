"""Phase 14.6 — Tests for Clerk-JWT auth path on /v1/ask + /v1/ask/stream.

The dependency `verify_clerk_or_api_key` accepts either:
  - `Authorization: Bearer <clerk-jwt>` — Clerk session token, no allowlist
  - `X-API-Key: <key>` — existing API-key path

This file covers the Bearer-JWT path + the combined behavior. The pure
API-key path stays covered by tests/test_server.py.

Real RS256 keypair generated per session; ephemeral CLERK_JWT_KEY env is
set to the public PEM. Tokens are signed with the matching private key
so the full jwt.decode signature path runs (no mocking).
"""
from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from rag_leis import obs
from rag_leis.rag import RAGAnswer
from rag_leis.server import app, get_pipeline, limiter


class _StubPipeline:
    """Minimal pipeline test double — only `.answer(query, on_event=...)` is called."""

    def __init__(self, answer: RAGAnswer):
        self._answer = answer

    def answer(self, query: str, on_event=None) -> RAGAnswer:
        return self._answer


def _sample_answer() -> RAGAnswer:
    return RAGAnswer(
        answer="ok",
        citations=[],
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


@pytest.fixture(scope="module")
def keypair():
    """Generate an ephemeral RS256 keypair for signing test JWTs.

    Module scope: keypair is expensive (~50ms for the bigint math).
    All tests in this file share the same key + corresponding env var.
    """
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


VALID_KEY = "rag_test_valid_key_xyz789"
ANY_EMAIL = "alguem@example.test"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch, keypair):
    """Set both auth surfaces' env vars for every test.

    - Clerk: CLERK_JWT_KEY is the test pubkey; CLERK_AUDIENCE empty
      (matches the production posture where session tokens don't carry
      a strict aud on the user-UI path).
    - API key: one valid key for the X-API-Key path tests.
    """
    monkeypatch.setenv("CLERK_JWT_KEY", keypair["public"])
    # Phase 17.3 — delenv works cleanly now that load_dotenv was
    # moved out of module-import in rag_leis.llm + .maritaca.
    monkeypatch.delenv("CLERK_AUDIENCE", raising=False)
    monkeypatch.setenv("RAG_API_KEYS", VALID_KEY)
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "1000")
    limiter.reset()
    obs.reset_for_tests()
    # Match tests/test_server.py's obs setup so neither file's autouse
    # fixture pollutes obs's global state for the other when pytest
    # interleaves runs.
    obs.configure(level="DEBUG", in_memory_spans=True)
    yield
    obs.reset_for_tests()


@pytest.fixture
def client():
    """TestClient + stub pipeline. No lifespan — keeps env knobs honored."""
    stub = _StubPipeline(_sample_answer())
    app.dependency_overrides[get_pipeline] = lambda: stub
    app.state.pipeline = stub
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def make_token(
    *, keypair, email: str | None = ANY_EMAIL, exp_in_seconds: int = 300,
) -> str:
    """Sign a Clerk-like JWT with the test private key."""
    now = int(time.time())
    payload: dict = {"iat": now, "exp": now + exp_in_seconds, "sub": "user_test"}
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, keypair["private"], algorithm="RS256")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Dual-auth behavior — both methods accepted; neither = 401
# ---------------------------------------------------------------------------


def test_ask_with_valid_clerk_bearer(client, keypair):
    """Any Clerk-authed user (no allowlist) → 200."""
    token = make_token(keypair=keypair, email=ANY_EMAIL)
    r = client.post("/v1/ask", json={"query": "what is LGPD?"}, headers=bearer(token))
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "ok"


def test_ask_with_valid_api_key_still_works(client):
    """API-key path is preserved (CI smoke tests + MCP rely on it)."""
    r = client.post(
        "/v1/ask",
        json={"query": "what is LGPD?"},
        headers={"X-API-Key": VALID_KEY},
    )
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "ok"


def test_ask_no_credentials_returns_401(client):
    r = client.post("/v1/ask", json={"query": "x"})
    assert r.status_code == 401
    body = r.json()
    assert "missing credentials" in body["detail"].lower()
    # WWW-Authenticate advertises both schemes
    auth = r.headers.get("www-authenticate", "")
    assert "Bearer" in auth and "ApiKey" in auth


def test_ask_bearer_takes_precedence_when_both_headers_present(client, keypair):
    """If a request carries BOTH a valid Bearer AND a valid X-API-Key,
    Bearer wins (it's the browser path). API-key is the fallback."""
    token = make_token(keypair=keypair, email=ANY_EMAIL)
    r = client.post(
        "/v1/ask",
        json={"query": "x"},
        headers={**bearer(token), "X-API-Key": VALID_KEY},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Bearer-JWT failure modes
# ---------------------------------------------------------------------------


def test_ask_bad_bearer_signature_returns_401(client, keypair):
    """Sign with a DIFFERENT keypair than the server verifies against."""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_priv = other.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    bad = jwt.encode(
        {"iat": int(time.time()), "exp": int(time.time()) + 60, "email": ANY_EMAIL},
        other_priv, algorithm="RS256",
    )
    r = client.post("/v1/ask", json={"query": "x"}, headers=bearer(bad))
    assert r.status_code == 401


def test_ask_expired_bearer_returns_401(client, keypair):
    token = make_token(keypair=keypair, email=ANY_EMAIL, exp_in_seconds=-60)
    r = client.post("/v1/ask", json={"query": "x"}, headers=bearer(token))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_ask_bearer_missing_email_claim_returns_401(client, keypair):
    """Token signed correctly but with no email claim → fails."""
    token = make_token(keypair=keypair, email=None)
    r = client.post("/v1/ask", json={"query": "x"}, headers=bearer(token))
    assert r.status_code == 401
    assert "email" in r.json()["detail"].lower()


def test_ask_empty_bearer_returns_401(client):
    r = client.post("/v1/ask", json={"query": "x"}, headers={"Authorization": "Bearer "})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Allowlist independence — non-admin user can still use /v1/ask
# ---------------------------------------------------------------------------


def test_ask_works_for_email_not_in_admin_allowlist(client, keypair, monkeypatch):
    """The whole point of verify_session_token: any registered email is
    accepted, even if RAG_ADMIN_ALLOWLIST is set to a different value."""
    monkeypatch.setenv("RAG_ADMIN_ALLOWLIST", "only-the-operator@example.com")
    token = make_token(keypair=keypair, email="random-public-user@example.test")
    r = client.post("/v1/ask", json={"query": "x"}, headers=bearer(token))
    assert r.status_code == 200
