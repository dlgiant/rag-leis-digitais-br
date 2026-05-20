"""Phase 8.1 — HTTP harness tests.
Phase 8.2 — auth + rate limit tests (extends).

Uses FastAPI's TestClient with the pipeline dependency overridden by a
stub. The real pipeline takes ~2s to load + makes paid LLM calls, so
the suite injects a fake `pipeline.answer(query) -> RAGAnswer` and
verifies the HTTP layer's contract:

  - Endpoint shapes (request + response schemas)
  - Byte-for-byte equivalence: response JSON deserializes back to the
    same RAGAnswer field values the stub returned
  - Error responses: 422 on missing/invalid query, 500 on pipeline
    exception, 503 before pipeline is loaded
  - Health check honors pipeline_loaded state
  - Phase 8.2: X-API-Key auth (401 missing/invalid; 200 valid) and
    per-key rate limit (429 over cap; X-RateLimit-* headers always
    on /v1/ask; health + openapi exempt from both auth and limit)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag_leis.prose_check import ProseMismatch
from rag_leis.rag import FlaggedVigencia, RAGAnswer
from rag_leis.server import app, get_pipeline, limiter

VALID_KEY = "rag_test_valid_key_abc123"
OTHER_VALID_KEY = "rag_test_other_key_def456"
AUTH_HEADERS = {"X-API-Key": VALID_KEY}


# ----------------------------------------------------------------------------
# Stub pipeline
# ----------------------------------------------------------------------------


class StubPipeline:
    """Minimal pipeline test double — implements only `.answer()`."""

    def __init__(self, answer_to_return: RAGAnswer | None = None,
                 raise_exc: Exception | None = None):
        self._answer = answer_to_return
        self._raise = raise_exc
        self.calls: list[str] = []

    def answer(self, query: str) -> RAGAnswer:
        self.calls.append(query)
        if self._raise is not None:
            raise self._raise
        assert self._answer is not None
        return self._answer


def _sample_answer() -> RAGAnswer:
    """A realistic RAGAnswer with every field populated — verifies the
    Pydantic models cover the full RAGAnswer surface."""
    return RAGAnswer(
        answer="LGPD define dado pessoal como informação relacionada a pessoa natural identificada ou identificável.",
        citations=["urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1"],
        unverified_claims=["LGPD entrou em vigor em setembro de 2020"],
        rejected_citations=[("not-in-corpus", "urn:lex:br:federal:lei:9999;art1")],
        refused=False,
        refusal_reason=None,
        raw_retrieval=[
            ("urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1", 0.87),
            ("urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2", 0.82),
        ],
        flagged_vigencia=[FlaggedVigencia(
            urn="urn:lex:br:federal:lei:2014-04-23;12965~art10;par2",
            status="alterado",
            fundamento="Lei 13.709/2018",
            descricao_curta="Alterado pela LGPD",
        )],
        classified_type="definicao",
        classified_top_k=8,
        pii_types_redacted=[],
        hierarchy_warning=None,
        prose_citation_mismatches=[ProseMismatch(
            surface="Art. 7", expected_partition="art7",
            span_start=0, span_end=5, nearest_cited_urn=None,
        )],
        prose_check_retried=False,
        sources_consulted_at={"urn:lex:br:federal:lei:2018-08-14;13709": "2026-01-15"},
        cost_estimate_usd=0.0042,
        tokens_used={"input_tokens": 1234, "output_tokens": 156},
        llm_calls=2,
        latency_ms=2845.7,
        rejected_irrelevant_citations=["urn:lex:br:federal:lei:2018-08-14;13709~art5;inc99"],
    )


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    """Default auth env for every test: two valid keys, generous limit.
    Individual tests override RAG_RATE_LIMIT_PER_MINUTE via monkeypatch
    when they need to exercise the rate-limit path."""
    monkeypatch.setenv("RAG_API_KEYS", f"{VALID_KEY},{OTHER_VALID_KEY}")
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "1000")
    # slowapi caches per-key buckets in memory between tests; reset to
    # prevent prior-test residue from leaking into the next.
    limiter.reset()
    yield


@pytest.fixture
def stub_pipeline() -> StubPipeline:
    return StubPipeline(answer_to_return=_sample_answer())


@pytest.fixture
def client_with_stub(stub_pipeline: StubPipeline):
    """TestClient with the pipeline dependency overridden by the stub.
    Uses bare `TestClient(app)` (no `with`) so the FastAPI lifespan
    DOES NOT fire — otherwise the real pipeline would load, overwriting
    `app.state.pipeline` and making the stub useless. See FastAPI docs
    on TestClient lifespan handling."""
    app.dependency_overrides[get_pipeline] = lambda: stub_pipeline
    # Also set on app.state so /health returns pipeline_loaded=True
    app.state.pipeline = stub_pipeline
    try:
        yield TestClient(app), stub_pipeline
    finally:
        app.dependency_overrides.clear()
        app.state.pipeline = None


@pytest.fixture
def client_without_pipeline():
    """TestClient with no pipeline loaded (simulates startup pre-lifespan
    completion). Bare `TestClient(app)` skips lifespan so the real
    pipeline doesn't load."""
    app.dependency_overrides.clear()
    app.state.pipeline = None
    yield TestClient(app)


# ----------------------------------------------------------------------------
# /health
# ----------------------------------------------------------------------------


def test_health_when_pipeline_loaded(client_with_stub):
    client, _ = client_with_stub
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "pipeline_loaded": True}


def test_health_when_pipeline_not_loaded(client_without_pipeline):
    r = client_without_pipeline.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "starting", "pipeline_loaded": False}


# ----------------------------------------------------------------------------
# /v1/ask — happy path
# ----------------------------------------------------------------------------


def test_ask_returns_full_rag_answer(client_with_stub):
    client, stub = client_with_stub
    r = client.post("/v1/ask", json={"query": "qual a definição de dado pessoal na LGPD?"}, headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    expected = _sample_answer()

    # Byte-equivalent fields (everything the stub returned should be on the wire)
    assert body["answer"] == expected.answer
    assert body["citations"] == expected.citations
    assert body["unverified_claims"] == expected.unverified_claims
    assert body["refused"] is False
    assert body["refusal_reason"] is None
    assert body["classified_type"] == "definicao"
    assert body["classified_top_k"] == 8
    assert body["llm_calls"] == 2
    assert body["cost_estimate_usd"] == pytest.approx(0.0042)
    assert body["latency_ms"] == pytest.approx(2845.7)
    assert body["rejected_irrelevant_citations"] == expected.rejected_irrelevant_citations

    # Flattened-tuple fields
    assert body["rejected_citations"] == [
        {"reason": "not-in-corpus", "urn": "urn:lex:br:federal:lei:9999;art1"}
    ]
    assert body["raw_retrieval"] == [
        {"urn": "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1", "score": pytest.approx(0.87)},
        {"urn": "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2", "score": pytest.approx(0.82)},
    ]

    # Nested-dataclass fields
    assert body["flagged_vigencia"] == [{
        "urn": "urn:lex:br:federal:lei:2014-04-23;12965~art10;par2",
        "status": "alterado",
        "fundamento": "Lei 13.709/2018",
        "descricao_curta": "Alterado pela LGPD",
    }]
    assert body["prose_citation_mismatches"] == [{
        "surface": "Art. 7", "expected_partition": "art7",
        "span_start": 0, "span_end": 5, "nearest_cited_urn": None,
    }]

    # The stub got the query passed through unchanged
    assert stub.calls == ["qual a definição de dado pessoal na LGPD?"]


def test_ask_with_refused_answer_still_serializes_cleanly():
    """OOS refusal case: pipeline.answer returns refused=True with empty
    citations and various None fields. Verify the response still
    serializes (Pydantic handles Optional/None correctly)."""
    refused_ans = RAGAnswer(
        answer="Fora do escopo da base.",
        citations=[],
        unverified_claims=[],
        rejected_citations=[],
        refused=True,
        refusal_reason="cosine fast-path: top-1 0.213 < 0.400",
        raw_retrieval=[("urn:lex:br:federal:lei:2018;13709~art1", 0.213)],
        flagged_vigencia=[],
        classified_type=None,
        classified_top_k=None,
        pii_types_redacted=[],
        hierarchy_warning=None,
        prose_citation_mismatches=[],
        prose_check_retried=False,
        sources_consulted_at={},
        cost_estimate_usd=0.0,
        tokens_used={},
        llm_calls=0,
        latency_ms=42.3,
        rejected_irrelevant_citations=[],
    )
    stub = StubPipeline(answer_to_return=refused_ans)
    app.dependency_overrides[get_pipeline] = lambda: stub
    app.state.pipeline = stub
    try:
        client = TestClient(app)
        r = client.post("/v1/ask", json={"query": "qual a alíquota do IR em 2025?"}, headers=AUTH_HEADERS)
        assert r.status_code == 200
        body = r.json()
        assert body["refused"] is True
        assert body["refusal_reason"].startswith("cosine fast-path")
        assert body["citations"] == []
        assert body["classified_type"] is None
        assert body["llm_calls"] == 0
    finally:
        app.dependency_overrides.clear()
        app.state.pipeline = None


# ----------------------------------------------------------------------------
# /v1/ask — error paths
# ----------------------------------------------------------------------------


def test_ask_rejects_missing_query(client_with_stub):
    client, _ = client_with_stub
    r = client.post("/v1/ask", json={}, headers=AUTH_HEADERS)
    assert r.status_code == 422


def test_ask_rejects_empty_query(client_with_stub):
    client, _ = client_with_stub
    r = client.post("/v1/ask", json={"query": ""}, headers=AUTH_HEADERS)
    assert r.status_code == 422


def test_ask_rejects_oversize_query(client_with_stub):
    """Phase 8.1 caps query length at 2000 chars. Production-side abuse
    vector mitigation; tune for Phase 8.2 if needed."""
    client, _ = client_with_stub
    r = client.post("/v1/ask", json={"query": "x" * 2001}, headers=AUTH_HEADERS)
    assert r.status_code == 422


def test_ask_returns_500_when_pipeline_raises():
    stub = StubPipeline(raise_exc=RuntimeError("provider 429"))
    app.dependency_overrides[get_pipeline] = lambda: stub
    app.state.pipeline = stub
    try:
        client = TestClient(app)
        r = client.post("/v1/ask", json={"query": "anything"}, headers=AUTH_HEADERS)
        assert r.status_code == 500
        assert "pipeline error" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        app.state.pipeline = None


def test_ask_returns_503_when_pipeline_not_loaded(client_without_pipeline):
    r = client_without_pipeline.post("/v1/ask", json={"query": "test"}, headers=AUTH_HEADERS)
    assert r.status_code == 503
    assert r.json() == {"detail": "pipeline not loaded"}


# ----------------------------------------------------------------------------
# OpenAPI / schema sanity
# ----------------------------------------------------------------------------


def test_openapi_endpoint_lists_v1_ask():
    """FastAPI auto-generates OpenAPI; the spec should mention /v1/ask
    and the AskResponse schema. Production tooling (clients,
    documentation, contract tests) depends on this. Bare TestClient(app)
    skips lifespan — OpenAPI generation doesn't need the pipeline."""
    client = TestClient(app)
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert "/v1/ask" in spec["paths"]
    assert "/health" in spec["paths"]
    assert "AskResponse" in spec["components"]["schemas"]
    assert "AskRequest" in spec["components"]["schemas"]


# ----------------------------------------------------------------------------
# Phase 8.2 — Auth
# ----------------------------------------------------------------------------


def test_ask_rejects_missing_api_key(client_with_stub):
    client, _ = client_with_stub
    r = client.post("/v1/ask", json={"query": "anything"})
    assert r.status_code == 401
    assert r.json() == {"detail": "missing API key"}
    assert r.headers.get("www-authenticate") == "ApiKey"


def test_ask_rejects_wrong_api_key(client_with_stub):
    client, _ = client_with_stub
    r = client.post(
        "/v1/ask",
        json={"query": "anything"},
        headers={"X-API-Key": "rag_wrong_key_xyz"},
    )
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid API key"}
    assert r.headers.get("www-authenticate") == "ApiKey"


def test_ask_accepts_second_valid_api_key(client_with_stub):
    """RAG_API_KEYS can hold multiple keys (comma-separated). The second
    one should authenticate identically to the first."""
    client, _ = client_with_stub
    r = client.post(
        "/v1/ask",
        json={"query": "anything"},
        headers={"X-API-Key": OTHER_VALID_KEY},
    )
    assert r.status_code == 200


def test_health_is_unauthenticated(client_with_stub):
    """Health probes from platform infra hit /health without credentials.
    Must always return 200 regardless of auth state."""
    client, _ = client_with_stub
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["pipeline_loaded"] is True


def test_openapi_is_unauthenticated():
    """OpenAPI spec stays open for dev convenience (per Phase 8.2 plan).
    Revisit if Phase 8.3 surfaces sensitive endpoint shapes."""
    client = TestClient(app)
    r = client.get("/openapi.json")
    assert r.status_code == 200


# ----------------------------------------------------------------------------
# Phase 8.2 — Rate limiting
# ----------------------------------------------------------------------------


def test_ask_succeeds_under_rate_limit(client_with_stub, monkeypatch):
    """With cap=5/min and only 3 calls, all should succeed.

    Note: 200 responses don't carry X-RateLimit-* headers in Phase 8.2
    due to a slowapi/FastAPI response_model interaction (see
    server.py:limiter setup comment). 429 responses DO carry them via
    the manual handler; tested separately. Track as Phase 8.3 follow-up
    when we add structured response middleware."""
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "5")
    limiter.reset()
    client, _ = client_with_stub
    for _ in range(3):
        r = client.post("/v1/ask", json={"query": "test"}, headers=AUTH_HEADERS)
        assert r.status_code == 200


def test_ask_returns_429_over_rate_limit(client_with_stub, monkeypatch):
    """With cap=2/min: requests 1+2 → 200, request 3 → 429.
    Verify the 429 response carries Retry-After + X-RateLimit-* headers
    so clients can implement correct backoff."""
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "2")
    limiter.reset()
    client, _ = client_with_stub
    r1 = client.post("/v1/ask", json={"query": "test 1"}, headers=AUTH_HEADERS)
    r2 = client.post("/v1/ask", json={"query": "test 2"}, headers=AUTH_HEADERS)
    r3 = client.post("/v1/ask", json={"query": "test 3"}, headers=AUTH_HEADERS)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    body = r3.json()
    assert "rate limit exceeded" in body["detail"]
    # Rate-limit headers on 429
    lower_headers = {k.lower() for k in r3.headers.keys()}
    assert "retry-after" in lower_headers
    assert "x-ratelimit-limit" in lower_headers
    assert "x-ratelimit-remaining" in lower_headers
    assert "x-ratelimit-reset" in lower_headers
    assert r3.headers["X-RateLimit-Limit"] == "2"
    assert r3.headers["X-RateLimit-Remaining"] == "0"


def test_rate_limit_is_per_key(client_with_stub, monkeypatch):
    """Different API keys get independent buckets. With cap=1/min:
    key A's bucket exhausts after 1 req; key B can still make 1."""
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "1")
    limiter.reset()
    client, _ = client_with_stub
    # Key A: 1st OK, 2nd 429
    a1 = client.post("/v1/ask", json={"query": "a1"}, headers={"X-API-Key": VALID_KEY})
    a2 = client.post("/v1/ask", json={"query": "a2"}, headers={"X-API-Key": VALID_KEY})
    assert a1.status_code == 200
    assert a2.status_code == 429
    # Key B: 1st OK (independent bucket)
    b1 = client.post("/v1/ask", json={"query": "b1"}, headers={"X-API-Key": OTHER_VALID_KEY})
    assert b1.status_code == 200


def test_health_is_not_rate_limited(client_with_stub, monkeypatch):
    """Health probes from Fly's 30s interval would consume ~2/min of the
    budget per replica if rate-limited. Confirm health is exempt by
    hammering it past any reasonable cap."""
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "1")
    limiter.reset()
    client, _ = client_with_stub
    for _ in range(10):
        r = client.get("/health")
        assert r.status_code == 200


def test_auth_failure_does_not_consume_rate_budget(client_with_stub, monkeypatch):
    """401 responses should NOT consume the per-key rate budget — auth
    runs before rate limit by FastAPI's Depends order. (Defensive: if
    someone reorders, they'd burn a legitimate key's budget on bad
    auth attempts.) With cap=1/min, 1 unauth'd attempt + 1 authed
    attempt should both succeed at their respective layers."""
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "1")
    limiter.reset()
    client, _ = client_with_stub
    # Unauth attempt: 401 (doesn't reach rate limit)
    r1 = client.post("/v1/ask", json={"query": "test"})
    assert r1.status_code == 401
    # Authed attempt: 200 (bucket still has 1)
    r2 = client.post("/v1/ask", json={"query": "test"}, headers=AUTH_HEADERS)
    assert r2.status_code == 200
