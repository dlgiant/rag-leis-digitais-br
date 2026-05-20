"""Phase 8.1 — HTTP harness.

Minimal FastAPI server wrapping the RAGPipeline. One endpoint serving
the same `pipeline.answer()` path the CLI uses, plus a health check
for readiness probes.

Out of scope for 8.1 (deferred to 8.2+):
    - Auth (API key, JWT) — Phase 8.2
    - Rate limiting — Phase 8.2
    - Structured JSON logging — Phase 8.3
    - OpenTelemetry tracing — Phase 8.3
    - Streaming responses — deferred (Phase 9 UI consideration)

Pipeline lifecycle: load once at startup via FastAPI's lifespan. The
pipeline instance lives on `app.state.pipeline` and is injected into
the endpoint via the `get_pipeline` dependency — tests override that
dependency to skip the (slow) load.

Run:
    uv run uvicorn rag_leis.server:app --host 0.0.0.0 --port 8000

Override defaults via env vars:
    RAG_EMBEDDER (default: voyage-3-large)
    RAG_TEXT_MODE (default: title+label+nav+caput+text)
    RAG_TOP_K (default: 10)
    RAG_OOS_THRESHOLD (default: 0.4)
    RAG_LLM_PROVIDER (default: maritaca)
    RAG_LLM_CACHE_DIR (default: unset — no caching)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from rag_leis.rag import DEFAULT_TOP_K, RAGAnswer, RAGPipeline, load_pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"


# ============================================================================
# Pydantic models — mirror RAGAnswer for HTTP response
# ============================================================================


class AskRequest(BaseModel):
    """User-facing request payload."""

    query: str = Field(..., min_length=1, max_length=2000,
                       description="The legal question to answer.")


class RejectedCitationModel(BaseModel):
    reason: str
    urn: str


class FlaggedVigenciaModel(BaseModel):
    urn: str
    status: str
    fundamento: str
    descricao_curta: str


class ProseMismatchModel(BaseModel):
    surface: str
    expected_partition: str
    span_start: int
    span_end: int
    nearest_cited_urn: str | None = None


class RawRetrievalEntry(BaseModel):
    urn: str
    score: float


class AskResponse(BaseModel):
    """Response payload — mirrors RAGAnswer field-for-field. Tuples and
    nested dataclasses are flattened into Pydantic-friendly shapes."""

    answer: str
    citations: list[str]
    unverified_claims: list[str]
    rejected_citations: list[RejectedCitationModel]
    refused: bool
    refusal_reason: str | None
    raw_retrieval: list[RawRetrievalEntry]
    flagged_vigencia: list[FlaggedVigenciaModel]
    classified_type: str | None
    classified_top_k: int | None
    pii_types_redacted: list[str]
    hierarchy_warning: str | None
    prose_citation_mismatches: list[ProseMismatchModel]
    prose_check_retried: bool
    sources_consulted_at: dict[str, str]
    cost_estimate_usd: float
    tokens_used: dict[str, int]
    llm_calls: int
    latency_ms: float
    rejected_irrelevant_citations: list[str]


class HealthResponse(BaseModel):
    status: str
    pipeline_loaded: bool


# ============================================================================
# RAGAnswer → AskResponse conversion
# ============================================================================


def _rag_answer_to_response(ans: RAGAnswer) -> AskResponse:
    """Flatten RAGAnswer (dataclass + tuples + nested dataclasses) into
    the Pydantic response shape. Done explicitly so future RAGAnswer
    additions surface as type errors here, not silent field drops."""
    return AskResponse(
        answer=ans.answer,
        citations=list(ans.citations),
        unverified_claims=list(ans.unverified_claims),
        rejected_citations=[
            RejectedCitationModel(reason=rsn, urn=u)
            for rsn, u in ans.rejected_citations
        ],
        refused=ans.refused,
        refusal_reason=ans.refusal_reason,
        raw_retrieval=[
            RawRetrievalEntry(urn=u, score=s) for u, s in ans.raw_retrieval
        ],
        flagged_vigencia=[FlaggedVigenciaModel(**asdict(fv)) for fv in ans.flagged_vigencia],
        classified_type=ans.classified_type,
        classified_top_k=ans.classified_top_k,
        pii_types_redacted=list(ans.pii_types_redacted),
        hierarchy_warning=ans.hierarchy_warning,
        prose_citation_mismatches=[
            ProseMismatchModel(**asdict(m)) for m in ans.prose_citation_mismatches
        ],
        prose_check_retried=ans.prose_check_retried,
        sources_consulted_at=dict(ans.sources_consulted_at),
        cost_estimate_usd=ans.cost_estimate_usd,
        tokens_used=dict(ans.tokens_used),
        llm_calls=ans.llm_calls,
        latency_ms=ans.latency_ms,
        rejected_irrelevant_citations=list(ans.rejected_irrelevant_citations),
    )


# ============================================================================
# Pipeline lifespan — load once at startup, share across requests
# ============================================================================


def _build_pipeline_from_env() -> RAGPipeline:
    """Construct the pipeline from environment variables. Same defaults
    as the eval CLI so HTTP behavior matches CLI behavior byte-for-byte
    given identical inputs."""
    embedder = os.environ.get("RAG_EMBEDDER", "voyage-3-large")
    text_mode = os.environ.get("RAG_TEXT_MODE", "title+label+nav+caput+text")
    top_k = int(os.environ.get("RAG_TOP_K", DEFAULT_TOP_K))
    oos_threshold = float(os.environ.get("RAG_OOS_THRESHOLD", 0.4))
    llm_provider = os.environ.get("RAG_LLM_PROVIDER", "maritaca")
    llm_cache_dir_raw = os.environ.get("RAG_LLM_CACHE_DIR")
    llm_cache_dir = Path(llm_cache_dir_raw) if llm_cache_dir_raw else None
    return load_pipeline(
        chunks_dir=CHUNKS_DIR, index_dir=INDEX_DIR,
        embedder_name=embedder, text_mode=text_mode,
        llm_provider=llm_provider, llm_model=None,
        top_k=top_k, oos_threshold=oos_threshold,
        llm_cache_dir=llm_cache_dir,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the pipeline once at startup; reuse for every request."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    app.state.pipeline = _build_pipeline_from_env()
    try:
        yield
    finally:
        # No teardown needed — FAISS index + chunks are in-process memory,
        # garbage-collected at process exit.
        app.state.pipeline = None


# ============================================================================
# App + dependency injection
# ============================================================================


app = FastAPI(
    title="rag-leis-digitais-br",
    description=(
        "RAG over Brazilian digital laws (LGPD, MCI, Lei do Software, …). "
        "See https://github.com/dlgiant/rag-leis-digitais-br for context."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


def get_pipeline(request: Request) -> RAGPipeline:
    """FastAPI dependency: surface the pipeline instance to handlers.
    Tests override this dependency to inject a mock without paying the
    startup cost."""
    pipeline: RAGPipeline | None = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        # 503 instead of 500: load failed or app is mid-startup
        raise HTTPException(status_code=503, detail="pipeline not loaded")
    return pipeline


# ============================================================================
# Endpoints
# ============================================================================


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Readiness probe. Returns pipeline_loaded=True once the pipeline
    instance is on app.state. Used by Fly.io / Railway / Render health
    checks and Phase 8.4 load test orchestration."""
    pipeline = getattr(request.app.state, "pipeline", None)
    return HealthResponse(
        status="ok" if pipeline is not None else "starting",
        pipeline_loaded=pipeline is not None,
    )


@app.post("/v1/ask", response_model=AskResponse)
async def ask(
    payload: AskRequest,
    pipeline: RAGPipeline = Depends(get_pipeline),
) -> AskResponse:
    """Answer a single query against the pipeline. Byte-for-byte
    equivalent to `pipeline.answer(payload.query)` modulo JSON
    serialization of tuples/dataclasses into the AskResponse shape."""
    try:
        ans = pipeline.answer(payload.query)
    except Exception as e:
        # Pipeline-level failures (provider rate limit, embedder OOM, etc.)
        # surface as 500 with a generic message — Phase 8.3 will add
        # structured logging with the request_id for diagnosis.
        raise HTTPException(
            status_code=500,
            detail=f"pipeline error: {type(e).__name__}",
        ) from e
    return _rag_answer_to_response(ans)
