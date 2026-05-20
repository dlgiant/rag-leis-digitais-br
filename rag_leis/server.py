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
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

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
# Phase 8.2 — Auth + rate limiting
# ============================================================================


def _allowed_keys() -> set[str]:
    """Read the allowed-API-keys set from RAG_API_KEYS (comma-separated).
    Empty/unset = no keys allowed. The fail-closed default is intentional —
    accidental empty-env-var must NOT silently open the endpoint."""
    raw = os.environ.get("RAG_API_KEYS", "").strip()
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


def verify_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """FastAPI dependency: check `X-API-Key` header against the
    RAG_API_KEYS env var set. Returns the validated key (used as the
    rate-limit bucket identifier). Constant-time compare via
    `secrets.compare_digest` to avoid timing oracles.

    Failure modes:
      - missing header → 401 with WWW-Authenticate: ApiKey
      - key not in allowed set → 401 (same WWW-Authenticate)
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    allowed = _allowed_keys()
    # Iterate to make every comparison constant-time. set lookups would be
    # fast but timing-sensitive on the first-character mismatch.
    for candidate in allowed:
        if secrets.compare_digest(x_api_key, candidate):
            return x_api_key
    raise HTTPException(
        status_code=401,
        detail="invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def _rate_limit_key(request: Request) -> str:
    """slowapi key function: bucket by validated API key. The auth
    dependency runs BEFORE this, so a missing/invalid key would have
    already 401'd. Falls back to the literal "no-key" string for
    defense in depth (any unauth'd request that reaches slowapi gets
    a shared bucket and trips fast)."""
    return request.headers.get("X-API-Key", "no-key")


def _rate_limit_cap() -> str:
    """Format the rate-limit string slowapi expects. Configurable via
    RAG_RATE_LIMIT_PER_MINUTE (default: 60). Set to 0 to disable
    (slowapi treats absence of the decorator as "no limit"; we
    short-circuit by setting a very high value and documenting the
    disable path)."""
    cap = int(os.environ.get("RAG_RATE_LIMIT_PER_MINUTE", "60"))
    if cap <= 0:
        # Effectively unlimited — useful for load tests and dev.
        # 1M/minute is well above any production traffic ceiling.
        return "1000000/minute"
    return f"{cap}/minute"


limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=[],
    # NOTE: slowapi's headers_enabled=True breaks with FastAPI's
    # response_model pattern — the decorator's async wrapper tries to
    # inject headers into a not-yet-built response and raises. We
    # build the rate-limit headers manually in the 429 handler below
    # (Retry-After + X-RateLimit-Limit/-Remaining/-Reset). 200
    # responses don't carry these headers in Phase 8.2 — tracked as a
    # Phase 8.3 follow-up when we add structured response middleware.
    headers_enabled=False,
)


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
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)  # noqa: F841 — handler registered by decorator
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Convert slowapi's RateLimitExceeded into a 429 with structured
    detail + Retry-After + X-RateLimit-* headers.

    We build the headers manually instead of calling slowapi's
    `_inject_headers` because that requires `headers_enabled=True` on
    the Limiter, which in turn breaks the FastAPI response_model
    pattern on 200 responses (slowapi tries to inject into a not-yet-
    built Pydantic response). Manual construction sidesteps that
    interaction.
    """
    headers: dict[str, str] = {}
    view_limit = getattr(request.state, "view_rate_limit", None)
    if view_limit is not None:
        rate_item, scope = view_limit
        try:
            window_reset, remaining = request.app.state.limiter.limiter.get_window_stats(
                rate_item, *scope
            )
            import time as _t
            reset_in = max(0, int(window_reset - _t.time()))
            headers["X-RateLimit-Limit"] = str(rate_item.amount)
            headers["X-RateLimit-Remaining"] = str(remaining)
            headers["X-RateLimit-Reset"] = str(int(window_reset))
            headers["Retry-After"] = str(reset_in)
        except Exception:
            # Defensive: window_stats can raise on storage edge cases.
            # Fall back to Retry-After only (per the RFC 6585 contract;
            # 429 SHOULD include Retry-After but isn't strictly required).
            headers["Retry-After"] = "60"
    return JSONResponse(
        status_code=429,
        content={"detail": f"rate limit exceeded: {exc.detail}"},
        headers=headers,
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
@limiter.limit(_rate_limit_cap)
async def ask(
    request: Request,  # noqa: ARG001 — required by @limiter.limit to find the rate-limit key
    payload: AskRequest,
    api_key: str = Depends(verify_api_key),  # noqa: ARG001 — Depends runs for side effect (401 if invalid)
    pipeline: RAGPipeline = Depends(get_pipeline),
) -> AskResponse:
    """Answer a single query against the pipeline. Byte-for-byte
    equivalent to `pipeline.answer(payload.query)` modulo JSON
    serialization of tuples/dataclasses into the AskResponse shape.

    Phase 8.2: gated by X-API-Key auth + per-key rate limit (default
    60 req/min/key; configurable via RAG_RATE_LIMIT_PER_MINUTE).
    """
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
