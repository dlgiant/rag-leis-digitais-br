"""Phase 11.2.1 — Postgres connection layer (Neon, BR region).

Single ConnectionPool managed by the FastAPI lifespan. `get_conn()`
returns a context-managed connection borrowed from the pool; all
queries should go through that helper so connections always return
to the pool on exit.

Env vars:
    DATABASE_URL   — Postgres connection string (postgresql://...).
                      Neon connection strings already include
                      ?sslmode=require. If absent, db.py functions
                      raise — the app's lifespan checks first.
    DATABASE_URL_TEST — optional test-only override (used by
                        pytest fixtures to point at a Neon dev
                        branch separate from production data).

Design notes:
  * `psycopg` v3 (not the older `psycopg2`). v3 has native async
    support but we use the sync path — the existing rag_leis code
    is sync, FastAPI happily wraps sync handlers in a thread pool.
  * Connection pool sized small (min 1, max 10) — Phase 11 traffic
    is ≤2 named users; Phase 10c will need re-tuning.
  * `autocommit=False` is the psycopg default; explicit transactions
    via `conn.transaction()` are preferred for multi-statement work.
    Single-statement appends auto-commit on context-manager exit.
"""
from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg_pool import ConnectionPool

# Module-global pool (initialized by `init_pool()` from the FastAPI
# lifespan on app startup). Tests can call `init_pool()` themselves
# with DATABASE_URL_TEST.
_pool: ConnectionPool | None = None


class DatabaseNotConfigured(RuntimeError):
    """Raised when code tries to use the DB but no DATABASE_URL is set.
    The admin endpoints catch this and return a graceful 503 rather
    than a 500 trace."""


def database_url() -> str | None:
    """Return the active DATABASE_URL or None if unset.

    Honors DATABASE_URL_TEST if running under pytest (auto-detected
    via PYTEST_CURRENT_TEST env var that pytest sets per-test).
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        test_url = os.environ.get("DATABASE_URL_TEST")
        if test_url:
            return test_url
    return os.environ.get("DATABASE_URL")


def init_pool(*, url: str | None = None, min_size: int = 1, max_size: int = 10) -> None:
    """Initialize the module-global ConnectionPool.

    Idempotent — calling twice with the same URL is a no-op. Calling
    with a DIFFERENT URL closes the old pool first (useful for tests
    that swap connection strings).
    """
    global _pool
    target = url or database_url()
    if target is None:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not set; cannot initialize Postgres pool"
        )
    if _pool is not None:
        # Avoid leaking pools across test/runtime boundary
        with contextlib.suppress(Exception):
            _pool.close()
        _pool = None
    _pool = ConnectionPool(
        target,
        min_size=min_size,
        max_size=max_size,
        # Open on first .getconn(); skips the initial connection at
        # construction time which would block app startup if the DB
        # is briefly unreachable.
        open=False,
    )
    _pool.open()


def close_pool() -> None:
    """Tear down the pool. Called by FastAPI lifespan on shutdown."""
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None


def is_configured() -> bool:
    """True if the pool is alive and serving connections."""
    return _pool is not None


@contextmanager
def get_conn() -> Iterator[Connection]:
    """Borrow a connection from the pool. Releases on exit.

    Raises DatabaseNotConfigured if the pool isn't initialized —
    callers should either ensure init_pool() ran or handle the
    error gracefully.

    Usage:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO ... VALUES (%s)", (value,))
            conn.commit()  # only needed for multi-statement TXNs
    """
    if _pool is None:
        raise DatabaseNotConfigured(
            "Postgres pool not initialized; call init_pool() first "
            "(or set DATABASE_URL and restart the app)"
        )
    with _pool.connection() as conn:
        yield conn
