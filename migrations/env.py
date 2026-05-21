"""Phase 11.2.1 — Alembic environment.

Reads DATABASE_URL from the environment so we never commit a
connection string to git. Uses sync engine (psycopg) — matches
the app's sync code style.

Run by:
  * The FastAPI lifespan on app startup (`alembic upgrade head`)
  * The one-shot data-import script
  * Manually: `uv run alembic upgrade head`
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the placeholder URL with the runtime value.
_db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_TEST")
if _db_url is None:
    raise RuntimeError(
        "DATABASE_URL is not set; alembic cannot connect. "
        "Set the env var via `flyctl secrets set` on prod or "
        "via .env locally."
    )
# Rewrite the URL scheme so SQLAlchemy uses psycopg v3 (the modern
# driver we installed) instead of the default `postgresql://` →
# psycopg2 dispatch. Without this, alembic crashes at startup with
# `ModuleNotFoundError: No module named 'psycopg2'`.
if _db_url.startswith("postgresql://"):
    _db_url = "postgresql+psycopg://" + _db_url[len("postgresql://"):]
elif _db_url.startswith("postgres://"):
    # Some providers emit `postgres://` (older scheme); same fix
    _db_url = "postgresql+psycopg://" + _db_url[len("postgres://"):]
config.set_main_option("sqlalchemy.url", _db_url)

# Alembic in this project uses RAW SQL migrations (no ORM models).
# target_metadata stays None — autogenerate is not used; migrations
# are hand-written.
target_metadata = None


def run_migrations_offline() -> None:
    """Render SQL to stdout without connecting (rarely used)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect + run migrations. The normal path."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
