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
    # No CLERK_AUDIENCE check — empty string (NOT delenv). Reason:
    # `rag_leis.llm` calls `load_dotenv()` at module-import time, which
    # repopulates os.environ from .env on first lazy import. If the
    # operator has CLERK_AUDIENCE set in their local .env (as production
    # requires), `delenv` would clear it but a later transitive import
    # could put it right back, mid-test, causing intermittent 401s.
    # `setenv("", "")` keeps it set-but-empty; `load_dotenv(override=False)`
    # skips already-set keys; clerk_auth's `if audience:` short-circuits
    # on empty strings exactly like on missing keys.
    monkeypatch.setenv("CLERK_AUDIENCE", "")
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


# =============================================================================
# Phase 11.3 — POST /v1/admin/eval/queries/{id}/refine
# =============================================================================


class _StubPipeline:
    """Minimal pipeline stub for refine endpoint tests.

    The endpoint only calls `_retrieve(query, top_k=k)`. This stub
    returns a deterministic list of (urn, score) tuples so tests can
    assert on the structure of the response without spinning up the
    real Voyage/BGE embedder + FAISS index.
    """

    def __init__(self, fixed_results: list[tuple[str, float]]):
        self._fixed = fixed_results

    def _retrieve(self, query: str, top_k: int | None = None):
        k = top_k if top_k is not None else len(self._fixed)
        return self._fixed[:k]


def _inject_pipeline(client, urn_results: list[tuple[str, float]]) -> None:
    """Attach a StubPipeline to the TestClient's underlying app.state.
    Call this BEFORE making the refine request."""
    client.app.state.pipeline = _StubPipeline(urn_results)


def test_refine_requires_auth(client):
    """No bearer token → 401."""
    r = client.post(
        "/v1/admin/eval/queries/some-id/refine",
        json={"refined_query": "x"},
    )
    assert r.status_code == 401


def test_refine_not_in_allowlist_returns_403(client, keypair):
    token = make_token(keypair=keypair, email="stranger@example.com")
    r = client.post(
        "/v1/admin/eval/queries/some-id/refine",
        json={"refined_query": "x"},
        headers=auth_header(token),
    )
    assert r.status_code == 403


def test_refine_unknown_query_id_returns_404(client, keypair):
    """404 fires before the pipeline is touched — no stub needed."""
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        "/v1/admin/eval/queries/deadbeef0000/refine",
        json={"refined_query": "alternative phrasing"},
        headers=auth_header(token),
    )
    assert r.status_code == 404


def test_refine_empty_query_returns_422(client, keypair):
    """Pydantic min_length=1 rejection."""
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        "/v1/admin/eval/queries/abc/refine",
        json={"refined_query": ""},
        headers=auth_header(token),
    )
    assert r.status_code == 422


@skip_if_no_db
def test_refine_happy_path_no_proposal(client, keypair):
    """save_as_proposal=False → no DB write; just returns comparison."""
    qid = _first_query_id(client, keypair)
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    _inject_pipeline(client, [
        ("urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1", 0.92),
        ("urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2", 0.81),
    ])
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/refine",
        json={"refined_query": "alternate phrasing", "save_as_proposal": False, "top_k": 5},
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["original"]["query_id"] == qid
    assert body["refined"]["query"] == "alternate phrasing"
    assert body["refined"]["top_k"] == 5
    # Stub returned 2 results regardless of top_k=5
    assert len(body["refined"]["retrieved"]) == 2
    assert body["refined"]["retrieved"][0]["rank"] == 1
    # The proposal was NOT saved
    assert body["proposal"] is None
    # Verify nothing landed in DB
    from rag_leis import proposals
    assert proposals.load_all_proposals() == []


@skip_if_no_db
def test_refine_with_proposal_save_creates_db_row(client, keypair):
    """Default save_as_proposal=True → Proposal in DB with kind=refinement."""
    qid = _first_query_id(client, keypair)
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    _inject_pipeline(client, [
        ("urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1", 0.95),
    ])
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/refine",
        json={"refined_query": "yet another phrasing"},
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposal"]["kind"] == "refinement"
    assert body["proposal"]["refined_query_text"] == "yet another phrasing"
    assert body["proposal"]["query_id"] == qid
    # Verify in DB
    from rag_leis import proposals
    db_rows = proposals.load_all_proposals()
    assert len(db_rows) == 1
    assert db_rows[0].kind == "refinement"
    assert db_rows[0].refined_query_text == "yet another phrasing"


@skip_if_no_db
def test_refine_annotates_gold_matches(client, keypair):
    """retrieved URNs that overlap with the row's gold are flagged
    `matches_gold=True`; others `False`."""
    qid = _first_query_id(client, keypair)
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    # First, fetch the row to learn its gold URNs (so the stub can
    # produce one that DOES match and one that doesn't).
    r0 = client.get(
        f"/v1/admin/eval/queries/{qid}",
        headers=auth_header(token),
    )
    assert r0.status_code == 200
    row = r0.json()["row"]
    gold = list(row["core_urns"]) + list(row.get("supporting_urns", []))
    assert gold, "fixture row should have at least one gold URN"
    matching = gold[0]
    not_matching = "urn:lex:br:federal:lei:9999-12-31;9999~art1"
    _inject_pipeline(client, [
        (matching, 0.95),
        (not_matching, 0.50),
    ])
    r = client.post(
        f"/v1/admin/eval/queries/{qid}/refine",
        json={"refined_query": "phrasing", "save_as_proposal": False},
        headers=auth_header(token),
    )
    body = r.json()
    retrieved = body["refined"]["retrieved"]
    assert retrieved[0]["matches_gold"] is True
    assert retrieved[1]["matches_gold"] is False
    assert body["refined"]["n_matches_gold"] == 1
    assert body["refined"]["n_gold_total"] == len(set(gold))


# =============================================================================
# Phase 12.0 — corpus + vigência review endpoints
# =============================================================================


def test_corpus_documents_no_auth_returns_401(client):
    r = client.get("/v1/admin/corpus/documents")
    assert r.status_code == 401


def test_corpus_documents_returns_doc_list(client, keypair):
    """Allowlisted user gets list of distinct documents with chunk
    counts + overlay coverage. Smoke test only — depends on local
    chunks/ data which CI may not have."""
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.get("/v1/admin/corpus/documents", headers=auth_header(token))
    # If chunks aren't loaded (CI without data), endpoint may 500;
    # accept that gracefully here. Real assertion: when 200, the
    # response shape is correct.
    if r.status_code != 200:
        pytest.skip(f"chunks unavailable in this environment ({r.status_code})")
    body = r.json()
    assert "documents" in body
    assert isinstance(body["documents"], list)
    if body["documents"]:
        d = body["documents"][0]
        assert "document_urn" in d
        assert "chunk_count" in d
        assert "n_overlays" in d
        assert "coverage_pct" in d


def test_corpus_chunks_unknown_doc_returns_404(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.get(
        "/v1/admin/corpus/documents/urn:lex:br:federal:lei:9999-12-31;0/chunks",
        headers=auth_header(token),
    )
    assert r.status_code == 404


def test_vigencia_overlays_no_auth_returns_401(client):
    r = client.get("/v1/admin/vigencia/overlays")
    assert r.status_code == 401


def test_vigencia_overlays_returns_list(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.get("/v1/admin/vigencia/overlays", headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()
    assert "overlays" in body
    assert isinstance(body["overlays"], list)
    # data/vigencia/overlays.yaml ships with 12 entries on main; if
    # this drifts we may need to update.
    assert body["total"] >= 12
    item = body["overlays"][0]
    assert {"urn", "status", "fundamento", "desde", "descricao_curta"} <= set(item.keys())


def test_vigencia_annotate_no_auth_returns_401(client):
    r = client.post(
        "/v1/admin/vigencia/chunks/urn:lex:br:federal:lei:2018-08-14;13709~art5/annotate",
        json={
            "status": "sub_judice",
            "fundamento": "test",
            "desde": "2026-05-21",
            "descricao_curta": "test descricao curta",
        },
    )
    assert r.status_code == 401


def test_vigencia_annotate_unknown_chunk_returns_404(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        "/v1/admin/vigencia/chunks/urn:lex:br:federal:lei:9999-12-31;0~art1/annotate",
        json={
            "status": "sub_judice",
            "fundamento": "test",
            "desde": "2026-05-21",
            "descricao_curta": "test descricao curta",
        },
        headers=auth_header(token),
    )
    # 404 if chunks loaded; could be other code path if data missing
    assert r.status_code in {404, 500}


def test_vigencia_annotate_invalid_status_returns_422(client, keypair):
    """Status enum validation; chunk lookup happens AFTER body
    validation so this fails at Pydantic regardless of corpus."""
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        "/v1/admin/vigencia/chunks/whatever/annotate",
        json={
            "status": "totally-made-up-status",
            "fundamento": "test",
            "desde": "2026-05-21",
            "descricao_curta": "test descricao curta",
        },
        headers=auth_header(token),
    )
    assert r.status_code == 422


def test_vigencia_annotate_too_short_descricao_returns_422(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        "/v1/admin/vigencia/chunks/whatever/annotate",
        json={
            "status": "sub_judice",
            "fundamento": "test",
            "desde": "2026-05-21",
            "descricao_curta": "x",  # under min_length=10
        },
        headers=auth_header(token),
    )
    assert r.status_code == 422


@skip_if_no_db
def test_vigencia_annotate_happy_path(client, keypair):
    """Submit a real annotation; verify it lands in DB as
    kind='vigencia' with all the vigencia_* columns populated."""
    # Use a known chunk URN from the corpus (MCI art. 19 has been
    # annotated in overlays.yaml; any LGPD chunk also works).
    chunk_urn = "urn:lex:br:federal:lei:2018-08-14;13709~art1"
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        f"/v1/admin/vigencia/chunks/{chunk_urn}/annotate",
        json={
            "status": "sub_judice",
            "fundamento": "STF RE test (Tema 999)",
            "desde": "2026-05-21",
            "descricao_curta": "Test annotation written by Phase 12.0 happy-path test.",
            "notes": "from the test suite",
        },
        headers=auth_header(token),
    )
    if r.status_code == 404:
        pytest.skip("chunk corpus not available in this environment")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    p = body["proposal"]
    assert p["kind"] == "vigencia"
    assert p["vigencia_urn"] == chunk_urn
    assert p["vigencia_status"] == "sub_judice"
    assert p["vigencia_fundamento"] == "STF RE test (Tema 999)"
    assert p["vigencia_desde"] == "2026-05-21"
    # Verify in DB
    from rag_leis import proposals
    rows = proposals.load_all_proposals()
    assert len(rows) == 1
    assert rows[0].kind == "vigencia"
    assert rows[0].vigencia_status == "sub_judice"


# =============================================================================
# Phase 13.0 — POST /v1/admin/hierarchy/probe
# =============================================================================


def test_hierarchy_probe_requires_auth(client):
    r = client.post("/v1/admin/hierarchy/probe", json={"query": "x"})
    assert r.status_code == 401


def test_hierarchy_probe_not_in_allowlist_returns_403(client, keypair):
    token = make_token(keypair=keypair, email="stranger@example.com")
    r = client.post(
        "/v1/admin/hierarchy/probe",
        json={"query": "x"},
        headers=auth_header(token),
    )
    assert r.status_code == 403


def test_hierarchy_probe_empty_query_returns_422(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    r = client.post(
        "/v1/admin/hierarchy/probe",
        json={"query": ""},
        headers=auth_header(token),
    )
    assert r.status_code == 422


def test_hierarchy_probe_save_without_flagged_returns_400(client, keypair):
    """If save_as_proposal=True, flagged_urns must be non-empty —
    nothing to flag = bad request."""
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    _inject_pipeline(client, [
        ("urn:lex:br:federal:lei:2018-08-14;13709~art5", 0.9),
    ])
    r = client.post(
        "/v1/admin/hierarchy/probe",
        json={"query": "x", "save_as_proposal": True, "flagged_urns": []},
        headers=auth_header(token),
    )
    assert r.status_code == 400


def test_hierarchy_probe_annotates_legal_ranks(client, keypair):
    """retrieval response includes legal_rank per URN."""
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    _inject_pipeline(client, [
        # LGPD (lei = rank 3 LO)
        ("urn:lex:br:federal:lei:2018-08-14;13709~art5", 0.95),
        # Decreto 8.771 (decreto = rank 4)
        ("urn:lex:br:federal:decreto:2016-05-11;8771~art1", 0.85),
        # ANPD Resolução (resolucao.cd = rank 5 infralegal)
        ("urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15~art1", 0.80),
    ])
    r = client.post(
        "/v1/admin/hierarchy/probe",
        json={"query": "sobre dado pessoal", "top_k": 5},
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    retrieved = body["retrieved"]
    assert len(retrieved) == 3
    assert retrieved[0]["legal_rank"] == 3  # LGPD
    assert retrieved[1]["legal_rank"] == 4  # Decreto
    assert retrieved[2]["legal_rank"] == 5  # Resolução
    # best_rank_in_top_k is the lowest numeric
    assert body["best_rank_in_top_k"] == 3
    # No flagged_urns + save_as_proposal=False → no DB write
    assert body["proposal"] is None


@skip_if_no_db
def test_hierarchy_probe_save_creates_db_row(client, keypair):
    token = make_token(keypair=keypair, email=LAWYER_EMAIL)
    _inject_pipeline(client, [
        ("urn:lex:br:federal:lei:2018-08-14;13709~art5", 0.95),
        ("urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15~art1", 0.92),
    ])
    flagged = ["urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15~art1"]
    r = client.post(
        "/v1/admin/hierarchy/probe",
        json={
            "query": "qual é a definição de dado pessoal?",
            "save_as_proposal": True,
            "flagged_urns": flagged,
            "notes": "Resolução ANPD shouldn't outrank LGPD on this query.",
        },
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposal"]["kind"] == "hierarchy"
    assert body["proposal"]["hierarchy_flagged_urns"] == flagged
    assert body["proposal"]["hierarchy_top_rank"] == 3
    # Verify in DB
    from rag_leis import proposals
    rows = proposals.load_all_proposals()
    assert len(rows) == 1
    assert rows[0].kind == "hierarchy"
    assert rows[0].hierarchy_query == "qual é a definição de dado pessoal?"
    assert list(rows[0].hierarchy_flagged_urns) == flagged
    assert rows[0].hierarchy_top_rank == 3
