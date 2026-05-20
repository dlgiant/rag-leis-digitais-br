# Phase 8.5.1 — Fly.io deployment image.
#
# Minimal Python 3.12 + uv. Production stack only: voyage embedder +
# server extra (FastAPI/uvicorn/slowapi/structlog/OTel). Eval-time
# deps (datasets, FlagEmbedding) NOT installed.
#
# IMPORTANT: production runs WITHOUT the Phase 7.9 LLM cache.
# RAG_LLM_CACHE_DIR is intentionally unset. Cache is eval-only —
# see memory `feedback-use-llm-cache-for-eval` for the rationale.

FROM python:3.12-slim

WORKDIR /app

# uv via pip (no curl|sh needed inside the build)
RUN pip install --no-cache-dir uv

# Dep install layer — cached on uv.lock + pyproject.toml
COPY pyproject.toml uv.lock ./
RUN uv sync --extra voyage --extra server --no-dev --frozen

# Source layer — changes most often, kept last
COPY rag_leis/ ./rag_leis/
COPY data/chunks/ ./data/chunks/
COPY data/index/ ./data/index/
# Vigência overlay file: used by load_chunks at startup.
COPY data/vigencia/ ./data/vigencia/

# Production-mode env. Runtime secrets (MARITACA_API_KEY,
# ANTHROPIC_API_KEY, VOYAGE_API_KEY, RAG_API_KEYS) come from
# `flyctl secrets set`, NOT baked into the image.
ENV PYTHONUNBUFFERED=1 \
    RAG_LLM_PROVIDER=maritaca \
    RAG_RATE_LIMIT_PER_MINUTE=60 \
    RAG_LOG_LEVEL=INFO

EXPOSE 8000

# uv-run lets uvicorn find the installed deps without us managing PATH.
CMD ["uv", "run", "uvicorn", "rag_leis.server:app", "--host", "0.0.0.0", "--port", "8000"]
