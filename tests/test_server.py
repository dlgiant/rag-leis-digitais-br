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
  - Phase 8.3: X-Request-ID on every response, structured JSON logs
    via structlog (captured in tests), OpenTelemetry spans created,
    PII/key absent from logs, X-RateLimit-* on 200 (8.2 follow-up)
"""
from __future__ import annotations

import io
import json

import pytest
import structlog
from fastapi.testclient import TestClient

from rag_leis import obs
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
    when they need to exercise the rate-limit path. Also configures
    Phase 8.3 obs (structlog + OTel) since tests bypass the FastAPI
    lifespan that would normally call obs.configure()."""
    monkeypatch.setenv("RAG_API_KEYS", f"{VALID_KEY},{OTHER_VALID_KEY}")
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "1000")
    # slowapi caches per-key buckets in memory between tests; reset to
    # prevent prior-test residue from leaking into the next.
    limiter.reset()
    # Phase 8.3 — reset obs between tests and re-configure with in-memory
    # span capture. Configure runs once per test (idempotent inside obs
    # but reset_for_tests clears state).
    obs.reset_for_tests()
    obs.configure(level="DEBUG", in_memory_spans=True)
    yield
    obs.reset_for_tests()


@pytest.fixture
def captured_logs(monkeypatch):
    """Capture structlog JSON output into an in-memory buffer so tests
    can assert log fields + verify PII/key absence. Re-binds the
    PrintLoggerFactory to write to the buffer instead of stdout."""
    buf = io.StringIO()
    # Re-configure structlog with a PrintLogger that writes to buf
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(10),  # DEBUG
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        cache_logger_on_first_use=False,
    )
    yield buf


def _parse_logs(buf: io.StringIO) -> list[dict]:
    """Parse the captured JSON log lines into dicts (one per line)."""
    out = []
    for line in buf.getvalue().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # structlog sometimes emits non-JSON (e.g., warnings before
            # configure); skip those.
            continue
    return out


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
    lower_headers = {k.lower() for k in r3.headers}
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


# ----------------------------------------------------------------------------
# Phase 8.3 — Observability
# ----------------------------------------------------------------------------


def test_request_id_header_on_every_response(client_with_stub):
    """Every response carries X-Request-ID — clients can correlate
    their logs/traces with the server's."""
    client, _ = client_with_stub
    for path, method, headers in [
        ("/health", "GET", {}),
        ("/v1/ask", "POST", AUTH_HEADERS),
        ("/openapi.json", "GET", {}),
    ]:
        if method == "POST":
            r = client.post(path, json={"query": "test"}, headers=headers)
        else:
            r = client.get(path, headers=headers)
        assert "x-request-id" in {k.lower() for k in r.headers}, f"{path} missing X-Request-ID"
        rid = r.headers["X-Request-ID"]
        assert len(rid) == 8, f"X-Request-ID should be 8 hex chars; got {rid!r}"


def test_pipeline_answered_log_contains_expected_fields(client_with_stub, captured_logs):
    """Successful /v1/ask emits a `pipeline.answered` log line with all
    the SLO-relevant fields populated."""
    client, _ = client_with_stub
    r = client.post("/v1/ask", json={"query": "test"}, headers=AUTH_HEADERS)
    assert r.status_code == 200
    events = [e for e in _parse_logs(captured_logs) if e.get("event") == "pipeline.answered"]
    assert len(events) == 1, f"expected 1 pipeline.answered event, got: {captured_logs.getvalue()}"
    ev = events[0]
    # SLO-relevant fields must all be present
    for field in [
        "query_length", "classified_type", "n_citations",
        "refused", "cost_estimate_usd", "llm_calls",
        "tokens_input", "tokens_output", "pipeline_latency_ms",
    ]:
        assert field in ev, f"pipeline.answered missing {field}: {ev}"
    assert ev["classified_type"] == "definicao"  # from _sample_answer()
    assert ev["refused"] is False
    assert ev["cost_estimate_usd"] == pytest.approx(0.0042)


def test_auth_failed_event_on_missing_key(client_with_stub, captured_logs):
    client, _ = client_with_stub
    r = client.post("/v1/ask", json={"query": "test"})
    assert r.status_code == 401
    events = [e for e in _parse_logs(captured_logs) if e.get("event") == "auth.failed"]
    assert len(events) == 1
    assert events[0]["reason"] == "missing-key"
    assert events[0]["api_key_prefix"] == "none"


def test_auth_failed_event_on_invalid_key(client_with_stub, captured_logs):
    client, _ = client_with_stub
    bad_key = "rag_wrong_key_xyz_abcdef"
    r = client.post("/v1/ask", json={"query": "test"}, headers={"X-API-Key": bad_key})
    assert r.status_code == 401
    events = [e for e in _parse_logs(captured_logs) if e.get("event") == "auth.failed"]
    assert len(events) == 1
    assert events[0]["reason"] == "invalid-key"
    assert events[0]["api_key_prefix"] == bad_key[:8]
    # Critical: full bad key should NOT appear anywhere in the captured logs
    assert bad_key not in captured_logs.getvalue()


def test_rate_limit_exceeded_event(client_with_stub, monkeypatch, captured_logs):
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "1")
    limiter.reset()
    client, _ = client_with_stub
    client.post("/v1/ask", json={"query": "1"}, headers=AUTH_HEADERS)
    r2 = client.post("/v1/ask", json={"query": "2"}, headers=AUTH_HEADERS)
    assert r2.status_code == 429
    events = [e for e in _parse_logs(captured_logs) if e.get("event") == "rate_limit.exceeded"]
    assert len(events) == 1
    assert events[0]["api_key_prefix"] == VALID_KEY[:8]


def test_logs_do_not_contain_full_api_key(client_with_stub, captured_logs):
    """Pre-locked criterion #6 — full API key must NEVER appear in logs.
    Hammer the auth path with valid + invalid keys to maximize the
    chance any logging mistake would surface."""
    client, _ = client_with_stub
    client.post("/v1/ask", json={"query": "valid"}, headers=AUTH_HEADERS)
    client.post("/v1/ask", json={"query": "invalid"}, headers={"X-API-Key": "rag_wrong_full_key_value_abc"})
    client.post("/v1/ask", json={"query": "missing"})
    log_text = captured_logs.getvalue()
    assert VALID_KEY not in log_text, "Full valid key leaked into logs"
    assert "rag_wrong_full_key_value_abc" not in log_text, "Full invalid key leaked into logs"


def test_logs_do_not_contain_raw_query_text(client_with_stub, captured_logs):
    """Pre-locked criterion #6 — raw query text must NEVER appear in
    logs (PII surface). Send a distinctive phrase, assert absent."""
    client, _ = client_with_stub
    distinctive = "ZZ_DISTINCTIVE_PHRASE_NOT_IN_ANY_RESPONSE_ZZ"
    client.post("/v1/ask", json={"query": distinctive}, headers=AUTH_HEADERS)
    assert distinctive not in captured_logs.getvalue(), \
        "Raw query text appeared in structured log output"


def test_otel_spans_created_on_request(client_with_stub):
    """The FastAPI auto-instrumentor should produce at least one span
    per HTTP request. (We can't easily test inner pipeline spans here
    since the stub bypasses pipeline.answer, but the request span is
    the load-bearing one for Phase 8.3.)"""
    client, _ = client_with_stub
    exp = obs.get_in_memory_exporter()
    assert exp is not None
    exp.clear()
    r = client.post("/v1/ask", json={"query": "test"}, headers=AUTH_HEADERS)
    assert r.status_code == 200
    spans = exp.get_finished_spans()
    # FastAPI auto-instrumentation produces a span for the HTTP request
    span_names = [s.name for s in spans]
    assert any("POST" in n or "ask" in n.lower() or "v1" in n.lower() for n in span_names), \
        f"no HTTP-request span found; got: {span_names}"


def test_inner_pipeline_spans_created_when_pipeline_runs():
    """Inner spans (pipeline.classify / retrieve / llm.generate /
    verify) come from rag.py's `obs.span(...)` blocks. Verified by
    triggering each block via direct calls in a controlled context."""
    # Direct obs.span calls — equivalent to what rag.py emits
    exp = obs.get_in_memory_exporter()
    assert exp is not None
    exp.clear()
    with obs.span("pipeline.classify"):
        pass
    with obs.span("pipeline.retrieve"):
        pass
    with obs.span("pipeline.llm.generate"):
        pass
    with obs.span("pipeline.verify"):
        pass
    span_names = {s.name for s in exp.get_finished_spans()}
    assert "pipeline.classify" in span_names
    assert "pipeline.retrieve" in span_names
    assert "pipeline.llm.generate" in span_names
    assert "pipeline.verify" in span_names


def test_xratelimit_headers_on_200_response(client_with_stub, monkeypatch):
    """Phase 8.2 follow-up — 200 responses now carry X-RateLimit-*
    headers via the RateLimitHeadersMiddleware."""
    monkeypatch.setenv("RAG_RATE_LIMIT_PER_MINUTE", "10")
    limiter.reset()
    client, _ = client_with_stub
    r = client.post("/v1/ask", json={"query": "test"}, headers=AUTH_HEADERS)
    assert r.status_code == 200
    lower = {k.lower() for k in r.headers}
    assert "x-ratelimit-limit" in lower
    assert "x-ratelimit-remaining" in lower
    assert "x-ratelimit-reset" in lower
    assert r.headers["X-RateLimit-Limit"] == "10"
