"""Phase 8.1 — HTTP harness tests.

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
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag_leis.prose_check import ProseMismatch
from rag_leis.rag import FlaggedVigencia, RAGAnswer
from rag_leis.server import app, get_pipeline


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
    r = client.post("/v1/ask", json={"query": "qual a definição de dado pessoal na LGPD?"})
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
        r = client.post("/v1/ask", json={"query": "qual a alíquota do IR em 2025?"})
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
    r = client.post("/v1/ask", json={})
    assert r.status_code == 422


def test_ask_rejects_empty_query(client_with_stub):
    client, _ = client_with_stub
    r = client.post("/v1/ask", json={"query": ""})
    assert r.status_code == 422


def test_ask_rejects_oversize_query(client_with_stub):
    """Phase 8.1 caps query length at 2000 chars. Production-side abuse
    vector mitigation; tune for Phase 8.2 if needed."""
    client, _ = client_with_stub
    r = client.post("/v1/ask", json={"query": "x" * 2001})
    assert r.status_code == 422


def test_ask_returns_500_when_pipeline_raises():
    stub = StubPipeline(raise_exc=RuntimeError("provider 429"))
    app.dependency_overrides[get_pipeline] = lambda: stub
    app.state.pipeline = stub
    try:
        client = TestClient(app)
        r = client.post("/v1/ask", json={"query": "anything"})
        assert r.status_code == 500
        assert "pipeline error" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        app.state.pipeline = None


def test_ask_returns_503_when_pipeline_not_loaded(client_without_pipeline):
    r = client_without_pipeline.post("/v1/ask", json={"query": "test"})
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
