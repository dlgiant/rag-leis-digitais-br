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

import asyncio
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from dataclasses import dataclass as _dataclass
from pathlib import Path
from typing import Any

import structlog
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from rag_leis import conversations as convos
from rag_leis import db, obs
from rag_leis.clerk_auth import (
    ClerkAuthError,
    ClerkClaims,
    clerk_session_dependency,
    verify_session_token,
)
from rag_leis.rag import DEFAULT_TOP_K, RAGAnswer, RAGPipeline, load_pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"


# ============================================================================
# Pydantic models — mirror RAGAnswer for HTTP response
# ============================================================================


class AskRequest(BaseModel):
    """User-facing request payload.

    Phase 10c: optional `conversation_id` lets the browser thread a
    follow-up question into an existing conversation. v1 doesn't pass
    prior turns into the pipeline as context — each query is still
    answered independently — but the message is appended to the
    requested conversation so the sidebar groups it correctly.
    Missing/null `conversation_id` → backend auto-creates a new
    conversation and returns its id in the response.
    """

    query: str = Field(..., min_length=1, max_length=2000,
                       description="The legal question to answer.")
    conversation_id: str | None = Field(
        default=None,
        description=(
            "Optional existing-conversation UUID to append this turn to. "
            "If null/missing, a new conversation is created and its id "
            "is returned in the response."
        ),
    )


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
    # Phase 10c — conversation this turn was persisted into. Populated
    # only on the JWT auth path (Clerk-authenticated browser callers);
    # None for API-key callers (CI smoke tests, MCP) since they have no
    # users-table row to scope conversations under.
    conversation_id: str | None = None


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
    """Load the pipeline once at startup; reuse for every request.
    Also initializes Phase 8.3 observability (structlog + OTel) — done
    here (not module-import) so the eval CLI doesn't pay the setup
    cost when importing rag_leis.server transitively."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    # Phase 8.3 — configure structured logging + OTel SDK.
    obs.configure(level=os.environ.get("RAG_LOG_LEVEL", "INFO"))

    # Phase 11.2.1 — Postgres connection pool + schema migrations.
    # Only runs if DATABASE_URL is set; absence falls back to the
    # legacy file-based JSONL backends (proposals.py + pii_audit.py
    # dispatch on db.is_configured()).
    from rag_leis import db
    if db.database_url():
        try:
            db.init_pool()
            _run_alembic_upgrade()
        except Exception as e:
            # If DB init fails, bail loudly. Better than starting up
            # in a half-configured state that would silently lose
            # writes by falling back to the gitignored file path.
            import sys
            print(f"ERROR initializing Postgres: {type(e).__name__}: {e}", file=sys.stderr)
            raise

    app.state.pipeline = _build_pipeline_from_env()
    try:
        yield
    finally:
        # No teardown needed for the pipeline — FAISS index + chunks
        # are in-process memory, garbage-collected at process exit.
        app.state.pipeline = None
        # Close the DB pool cleanly so connections drain to Neon.
        import contextlib
        with contextlib.suppress(Exception):
            db.close_pool()


def _run_alembic_upgrade() -> None:
    """Run `alembic upgrade head` programmatically at startup.

    Postgres row-locks `alembic_version` so concurrent startups from
    multiple Fly machines serialize safely — only the first to acquire
    the lock applies migrations; the rest no-op.
    """
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    command.upgrade(cfg, "head")


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
    Both emit `auth.failed` structured log events (Phase 8.3).
    """
    if not x_api_key:
        obs.get_logger().warning("auth.failed", reason="missing-key", api_key_prefix="none")
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
    obs.get_logger().warning(
        "auth.failed", reason="invalid-key", api_key_prefix=x_api_key[:8],
    )
    raise HTTPException(
        status_code=401,
        detail="invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


@_dataclass(frozen=True)
class AskCaller:
    """Identity of an authenticated `/v1/ask` caller. One of:
      - `email` + `user_id` populated → Clerk-authed user (browser via rag.nunes.work).
        `user_id` is the Clerk `sub` claim; profile fields mirror what
        Clerk has so the users-table upsert is one statement, not
        multiple round trips.
      - `api_key_prefix` populated → API-key caller (CI / MCP / curl).
        No persistence happens for this path — there's no users row to
        scope conversations to.

    `.identity` is the telemetry handle for log lines.
    """

    email: str | None = None
    user_id: str | None = None
    image_url: str | None = None
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    api_key_prefix: str | None = None

    @property
    def identity(self) -> str:
        if self.email:
            return self.email
        if self.api_key_prefix:
            return f"key:{self.api_key_prefix}"
        return "unknown"

    @property
    def is_clerk_authed(self) -> bool:
        """True for the Clerk-JWT path (has a user_id we can persist
        under). Phase 10c persistence only fires when this is true."""
        return bool(self.user_id)


def verify_clerk_or_api_key(request: Request) -> AskCaller:
    """FastAPI dep for `/v1/ask` + `/v1/ask/stream`: accept EITHER

      - `Authorization: Bearer <clerk-jwt>` — browser path (rag.nunes.work
        Clerk session, no allowlist gate; any registered user passes)
      - `X-API-Key: <key>` — programmatic path (CI smoke tests, MCP,
        curl scripts), keys read from RAG_API_KEYS

    Bearer takes precedence if both headers present. Returns an
    `AskCaller` with whichever identity validated. 401 if neither.
    """
    # Try Clerk Bearer first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[len("Bearer "):].strip()
        if not token:
            obs.get_logger().warning(
                "auth.failed", reason="empty-bearer", api_key_prefix="none",
            )
            raise HTTPException(status_code=401, detail="empty bearer token")
        try:
            claims = verify_session_token(token)
        except ClerkAuthError as e:
            obs.get_logger().warning(
                "auth.failed", reason=f"bad-bearer:{e}", api_key_prefix="none",
            )
            raise HTTPException(status_code=401, detail=str(e)) from e
        return AskCaller(
            email=claims.email,
            user_id=claims.user_id or None,
            image_url=claims.image_url or None,
            full_name=claims.full_name or None,
            first_name=claims.first_name or None,
            last_name=claims.last_name or None,
        )

    # Fall back to X-API-Key
    x_api_key = request.headers.get("X-API-Key")
    if x_api_key:
        allowed = _allowed_keys()
        for candidate in allowed:
            if secrets.compare_digest(x_api_key, candidate):
                return AskCaller(api_key_prefix=x_api_key[:8])
        obs.get_logger().warning(
            "auth.failed", reason="invalid-key", api_key_prefix=x_api_key[:8],
        )
        raise HTTPException(
            status_code=401, detail="invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    obs.get_logger().warning(
        "auth.failed", reason="missing-credentials", api_key_prefix="none",
    )
    raise HTTPException(
        status_code=401,
        detail="missing credentials (Bearer JWT or X-API-Key)",
        headers={"WWW-Authenticate": 'Bearer realm="rag-leis", ApiKey'},
    )


def _rate_limit_key(request: Request) -> str:
    """slowapi key function: bucket by validated caller identity. For
    Bearer-JWT callers, bucket by the JWT signature suffix (stable per
    session, changes ~every 60s when Clerk auto-refreshes the token —
    that's fine; a per-token quota is functionally per-user-per-minute).
    For X-API-Key callers, bucket by the key. Falls back to "no-key"
    for any unauthenticated request (defense in depth)."""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[len("Bearer "):].strip()
        return f"jwt:{token[-16:]}" if token else "jwt:empty"
    return f"key:{request.headers.get('X-API-Key', 'no-key')}"


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
    # build the rate-limit headers manually in `_build_rate_limit_headers`
    # below; the 429 exception handler + the Phase 8.3
    # RateLimitHeadersMiddleware both call it so 200 + 429 carry
    # consistent X-RateLimit-* headers.
    headers_enabled=False,
)


def _build_rate_limit_headers(request: Request) -> dict[str, str]:
    """Construct X-RateLimit-* + Retry-After headers from the slowapi
    state stashed on `request.state.view_rate_limit`. Called by both
    the 429 handler and the Phase 8.3 success-path middleware so 200
    + 429 responses carry identical headers.

    Returns empty dict if slowapi hasn't set state (e.g., un-rate-
    limited routes like /health)."""
    headers: dict[str, str] = {}
    view_limit = getattr(request.state, "view_rate_limit", None)
    if view_limit is None:
        return headers
    rate_item, scope = view_limit
    try:
        window_reset, remaining = request.app.state.limiter.limiter.get_window_stats(
            rate_item, *scope
        )
        reset_in = max(0, int(window_reset - time.time()))
        headers["X-RateLimit-Limit"] = str(rate_item.amount)
        headers["X-RateLimit-Remaining"] = str(remaining)
        headers["X-RateLimit-Reset"] = str(int(window_reset))
        headers["Retry-After"] = str(reset_in)
    except Exception:
        # Defensive: storage edge cases. Empty headers is acceptable.
        pass
    return headers


# ============================================================================
# Phase 8.3 — Observability middleware
# ============================================================================


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Generates a request_id, binds it to structlog contextvars, emits
    `request.received` on entry + `request.completed` on exit, and
    stamps `X-Request-ID` on the response.

    Health probes are logged at DEBUG only (per Phase 8.3 plan) to
    avoid flooding production logs with 30s/replica probe noise."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:8]
        request.state.request_id = request_id
        log = obs.get_logger()
        is_health = request.url.path == "/health"
        # Bind context for the rest of the request — all structlog
        # calls inside the handler chain (including from rag.py if it
        # eventually logs) carry these fields automatically.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            service="rag-leis-digitais-br",
        )
        api_key = request.headers.get("X-API-Key", "") or ""
        api_key_prefix = api_key[:8] if api_key else "none"
        t0 = time.monotonic()
        if not is_health:
            log.info(
                "request.received",
                method=request.method,
                path=request.url.path,
                client_ip=request.client.host if request.client else None,
                api_key_prefix=api_key_prefix,
            )
        try:
            response: Response = await call_next(request)
        except Exception as e:
            log.error(
                "request.error",
                error_type=type(e).__name__,
                error_message=str(e),
                exc_info=True,
            )
            raise
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        latency_ms = (time.monotonic() - t0) * 1000.0
        log_level = log.debug if is_health else log.info
        log_level(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=round(latency_ms, 1),
            request_id=request_id,
        )
        return response


class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    """Phase 8.2 follow-up — inject X-RateLimit-* headers on every
    /v1/ask response (200 + 429). The 429 path also gets them via the
    exception handler; this middleware covers 200."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path == "/v1/ask":
            for k, v in _build_rate_limit_headers(request).items():
                response.headers[k] = v
        return response


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

# Phase 8.3 — observability middleware ordering matters:
#   1. RequestContextMiddleware (outermost): generates request_id,
#      stamps X-Request-ID, emits request.received/completed logs
#   2. RateLimitHeadersMiddleware: injects X-RateLimit-* on 200
# Both middlewares only matter on the response path; ordering is
# "outer wraps inner". The OTel FastAPI instrumentor adds an even
# outer layer that captures the request boundary as an OTel span.
app.add_middleware(RateLimitHeadersMiddleware)
app.add_middleware(RequestContextMiddleware)
FastAPIInstrumentor.instrument_app(app)

# Phase 11.0 — mount admin router. Gated by Clerk JWT verification +
# email allowlist (see rag_leis/clerk_auth.py). Endpoints are
# read-only in 11.0; write paths land in 11.2+.
# Import here (not at top) so the FastAPIInstrumentor doesn't trace
# the admin router's request lifecycle separately from the main app —
# include_router wires the routes into the already-instrumented app.
from rag_leis.admin import router as admin_router  # noqa: E402

app.include_router(admin_router)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Convert slowapi's RateLimitExceeded into a 429 with structured
    detail + Retry-After + X-RateLimit-* headers. Emits a
    `rate_limit.exceeded` structured log event (Phase 8.3).

    We build the headers manually instead of calling slowapi's
    `_inject_headers` because that requires `headers_enabled=True` on
    the Limiter, which breaks the FastAPI response_model pattern on
    200 responses. Manual construction sidesteps that interaction.
    """
    headers = _build_rate_limit_headers(request)
    api_key_prefix = (request.headers.get("X-API-Key") or "")[:8] or "none"
    obs.get_logger().warning(
        "rate_limit.exceeded",
        api_key_prefix=api_key_prefix,
        cap=str(exc.detail),
        retry_after_seconds=int(headers.get("Retry-After", "60")),
    )
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
# Phase 10c — conversation persistence helper
# ============================================================================


def _persist_turn(
    *,
    caller: AskCaller,
    payload: AskRequest,
    response: AskResponse,
    redacted_query: str,
) -> str | None:
    """Persist one Q+A turn into the conversation history tables.

    Returns the conversation_id the turn was stored under, or None if
    persistence was skipped (API-key caller, DB unavailable, or any
    repo-level failure — the answer was already returned successfully
    to the caller; persistence is best-effort).

    Skips silently when:
      - caller is on the API-key path (no users row to scope under)
      - the DB pool is unconfigured (eval CLI / tests without DATABASE_URL_TEST)

    On a repo-level exception we log + degrade. The handler returns the
    answer regardless; a downstream operator can replay from logs if a
    persisted turn turns out to be load-bearing.
    """
    if not caller.is_clerk_authed:
        return None
    if not db.is_configured():
        return None

    log = obs.get_logger()
    try:
        convos.upsert_user(
            user_id=caller.user_id or "",
            email=caller.email or "",
            image_url=caller.image_url or "",
            full_name=caller.full_name or "",
            first_name=caller.first_name or "",
            last_name=caller.last_name or "",
        )

        # If no conversation_id supplied → create one with the first
        # user message as the auto-title. Existing-conversation
        # appends just reuse the id (no title rewrite — first message
        # is the canonical label). If the caller supplied an id but
        # it doesn't belong to them, fall through to creating a new
        # one — never bleed turns into another user's history.
        conv_id = payload.conversation_id
        if conv_id and not convos.conversation_belongs_to(
            conversation_id=conv_id, user_id=caller.user_id or "",
        ):
            log.warning(
                "conversation.ownership_mismatch",
                caller=caller.identity,
                requested_conversation_id=conv_id,
            )
            conv_id = None
        if not conv_id:
            conv_id = convos.create_conversation_from_first_query(
                user_id=caller.user_id or "",
                redacted_query=redacted_query,
            )

        # Persist the user message — redacted text only, never raw query.
        convos.append_message(
            conversation_id=conv_id,
            role="user",
            content_redacted=redacted_query,
        )
        # Persist the assistant message — answer text in content_redacted
        # for full-text-search friendliness, full AskResponse JSON in
        # answer_json so historical renders show citations + refusals.
        convos.append_message(
            conversation_id=conv_id,
            role="assistant",
            content_redacted=response.answer,
            answer_json=response.model_dump(mode="json"),
        )
        convos.touch_conversation(conversation_id=conv_id)
        return conv_id
    except Exception as e:
        # Best-effort persistence — never break the user's answer for a
        # DB hiccup. Log loudly so the operator can investigate.
        log.error(
            "conversation.persist_failed",
            error_type=type(e).__name__,
            error_message=str(e),
            caller=caller.identity,
            requested_conversation_id=payload.conversation_id,
        )
        return None


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
    request: Request,
    payload: AskRequest,
    caller: AskCaller = Depends(verify_clerk_or_api_key),  # noqa: B008 — FastAPI Depends() in defaults IS the framework pattern
    pipeline: RAGPipeline = Depends(get_pipeline),  # noqa: B008 — FastAPI Depends() in defaults IS the framework pattern
) -> AskResponse:
    """Answer a single query against the pipeline. Byte-for-byte
    equivalent to `pipeline.answer(payload.query)` modulo JSON
    serialization of tuples/dataclasses into the AskResponse shape.

    Phase 8.2: gated by X-API-Key auth + per-key rate limit (default
    60 req/min/key; configurable via RAG_RATE_LIMIT_PER_MINUTE).
    Phase 8.3: every call emits a `pipeline.answered` structured log
    line with classified_type, top_1_cosine, cost_estimate_usd, etc.
    Raw query text + answer text are NEVER logged (PII surface).
    """
    log = obs.get_logger()
    try:
        ans = pipeline.answer(payload.query)
    except Exception as e:
        # Pipeline-level failures (provider rate limit, embedder OOM, etc.)
        # surface as 500 with a generic message. Detail is type-only
        # to avoid leaking inner exception text (might embed query bits).
        log.error(
            "pipeline.error",
            error_type=type(e).__name__,
            query_length=len(payload.query),
        )
        raise HTTPException(
            status_code=500,
            detail=f"pipeline error: {type(e).__name__}",
        ) from e
    # Stamp the structured log with the interesting answer fields.
    # No query text, no answer text — log lines may go to aggregators
    # that don't have the same PII handling as the pii_audit_log path.
    log.info(
        "pipeline.answered",
        caller=caller.identity,
        query_length=len(payload.query),
        classified_type=ans.classified_type,
        top_1_cosine=ans.raw_retrieval[0][1] if ans.raw_retrieval else None,
        n_citations=len(ans.citations),
        n_rejected_irrelevant=len(ans.rejected_irrelevant_citations),
        refused=ans.refused,
        refusal_reason=ans.refusal_reason,
        cost_estimate_usd=ans.cost_estimate_usd,
        llm_calls=ans.llm_calls,
        tokens_input=(ans.tokens_used or {}).get("input_tokens", 0),
        tokens_output=(ans.tokens_used or {}).get("output_tokens", 0),
        pipeline_latency_ms=ans.latency_ms,
    )
    response = _rag_answer_to_response(ans)
    # Phase 10c — persist user msg + assistant msg if JWT-authed and DB
    # is configured. The redacted query is the post-PII text used inside
    # the pipeline (surfaced via RAGAnswer.pii_redacted_query so we don't
    # re-run the redactor here just to capture the same string).
    conv_id = _persist_turn(
        caller=caller,
        payload=payload,
        response=response,
        redacted_query=ans.pii_redacted_query or payload.query,
    )
    response.conversation_id = conv_id
    return response


# ============================================================================
# Phase 10.0 — Streaming endpoint (SSE)
# ============================================================================
#
# Same auth + rate-limit gates as /v1/ask. Emits Server-Sent Events for
# each pipeline stage boundary so the UI can show progressive state
# instead of staring at 13s of dead air. Final event ("complete")
# contains the full AskResponse payload — UI doesn't need to track
# intermediate state to render the final answer.
#
# Current limitation (Phase 10.0 v1): the generate stage emits
# "started" then "finished" with ~9s of latency in between (a single
# Maritaca call). Token-by-token streaming of the answer text is a
# Phase 10.0.1 follow-up; the architecture supports it (just add finer
# events between started/finished).


def _sse_format(event_dict: dict[str, Any]) -> bytes:
    """Format a dict as a single SSE 'message' frame.

    SSE wire format: each message is `data: <json>\\n\\n`. We use a
    single `data:` line per event; clients use `event_dict["event"]`
    or `event_dict["name"]` to dispatch.
    """
    return f"data: {json.dumps(event_dict)}\n\n".encode()


@app.post("/v1/ask/stream")
@limiter.limit(_rate_limit_cap)
async def ask_stream(
    request: Request,
    payload: AskRequest,
    caller: AskCaller = Depends(verify_clerk_or_api_key),  # noqa: B008 — FastAPI Depends() in defaults IS the framework pattern
    pipeline: RAGPipeline = Depends(get_pipeline),  # noqa: B008
):
    """Streaming variant of /v1/ask.

    Returns text/event-stream. Sends `{"event": "stage", ...}` events
    at each pipeline boundary, then `{"event": "complete", "answer":
    AskResponse}` when done. Final event includes the same payload
    `/v1/ask` would return — clients only need to parse "complete"
    to render the answer.

    Phase 10.0 stage events are NOT token-by-token within `generate`;
    that's a planned Phase 10.0.1 follow-up. v1 ships the endpoint
    shape correct so the UI work can start.
    """
    log = obs.get_logger()
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()  # marks pipeline thread completion

    def on_event(e: dict[str, Any]) -> None:
        """Called synchronously from pipeline thread. Bridges to the
        asyncio event loop's queue via call_soon_threadsafe."""
        loop.call_soon_threadsafe(queue.put_nowait, e)

    def run_pipeline() -> tuple[RAGAnswer | None, Exception | None]:
        try:
            ans = pipeline.answer(payload.query, on_event=on_event)
            return ans, None
        except Exception as exc:
            return None, exc
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    # Kick off the pipeline in an executor thread; we'll yield events
    # from the queue as they arrive, then a final "complete" event
    # with the full RAGAnswer.
    pipeline_future = loop.run_in_executor(None, run_pipeline)

    async def event_generator():
        try:
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    break
                yield _sse_format(item)
            # Pipeline thread is done — pull its result + emit final event
            ans, exc = await pipeline_future
            if exc is not None:
                log.error(
                    "pipeline.error", error_type=type(exc).__name__,
                    query_length=len(payload.query),
                )
                yield _sse_format({"event": "error",
                                   "detail": f"pipeline error: {type(exc).__name__}"})
                return
            assert ans is not None
            # Log just like /v1/ask does (Phase 8.3 schema)
            log.info(
                "pipeline.answered",
                caller=caller.identity,
                query_length=len(payload.query),
                classified_type=ans.classified_type,
                top_1_cosine=ans.raw_retrieval[0][1] if ans.raw_retrieval else None,
                n_citations=len(ans.citations),
                n_rejected_irrelevant=len(ans.rejected_irrelevant_citations),
                refused=ans.refused,
                refusal_reason=ans.refusal_reason,
                cost_estimate_usd=ans.cost_estimate_usd,
                llm_calls=ans.llm_calls,
                tokens_input=(ans.tokens_used or {}).get("input_tokens", 0),
                tokens_output=(ans.tokens_used or {}).get("output_tokens", 0),
                pipeline_latency_ms=ans.latency_ms,
                streaming=True,
            )
            response = _rag_answer_to_response(ans)
            # Phase 10c — persist same as /v1/ask. The conversation_id
            # is returned in the "complete" SSE event so the browser
            # can update its URL + sidebar without a separate fetch.
            conv_id = _persist_turn(
                caller=caller,
                payload=payload,
                response=response,
                redacted_query=ans.pii_redacted_query or payload.query,
            )
            response.conversation_id = conv_id
            yield _sse_format({"event": "complete",
                               "answer": response.model_dump(mode="json"),
                               "conversation_id": conv_id})
        except asyncio.CancelledError:
            # Client disconnected; let the pipeline thread finish in
            # the background (no good way to cancel it mid-LLM-call).
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if behind one
        },
    )


# ============================================================================
# Phase 10c — conversation history endpoints
# ============================================================================
#
# Both endpoints are gated by `clerk_session_dependency` (any registered
# Clerk user) — NOT the admin allowlist. Reads are scoped to the calling
# user's user_id at the SQL level; there is no operator/admin bypass for
# viewing other users' history. (LGPD: data subject access is by
# definition self-only.)


@app.get("/v1/conversations")
@limiter.limit(_rate_limit_cap)
async def list_conversations_endpoint(
    request: Request,
    claims: ClerkClaims = Depends(clerk_session_dependency),  # noqa: B008
):
    """List the calling user's conversations, most-recent-first.

    Returns up to 50 rows. The sidebar in the UI renders this directly;
    pagination is a Phase 10c.1 follow-up if/when histories grow long.
    """
    if not db.is_configured():
        # Eval CLI / tests without DATABASE_URL_TEST. Return empty
        # rather than 503 so the UI degrades gracefully — the chat
        # form still works without history.
        return {"conversations": []}
    if not claims.user_id:
        # Defensive: clerk_session_dependency validates the JWT but
        # doesn't require user_id (the `sub` claim) to be present.
        # In practice every Clerk session token has it; if it's
        # missing we return empty rather than crash.
        return {"conversations": []}
    items = convos.list_conversations(user_id=claims.user_id, limit=50)
    return {
        "conversations": [convos.conversation_to_dict(c) for c in items],
    }


@app.get("/v1/conversations/{conversation_id}")
@limiter.limit(_rate_limit_cap)
async def get_conversation_endpoint(
    conversation_id: str,
    request: Request,
    claims: ClerkClaims = Depends(clerk_session_dependency),  # noqa: B008
):
    """Load one conversation + its messages, scoped to the calling user.

    404 if the conversation doesn't exist OR if it does exist but is
    owned by a different user — we don't distinguish so the response
    doesn't leak "conversation X exists, you just can't see it" to a
    fishing attempt.
    """
    if not db.is_configured() or not claims.user_id:
        raise HTTPException(status_code=404, detail="conversation not found")
    result = convos.get_conversation(
        conversation_id=conversation_id, user_id=claims.user_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    conv, messages = result
    return {
        "conversation": convos.conversation_to_dict(conv),
        "messages": [convos.message_to_dict(m) for m in messages],
    }
