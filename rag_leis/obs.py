"""Phase 8.3 — Structured observability module.

Centralizes the structlog + OpenTelemetry setup so the rest of the
codebase can import lightweight helpers without each module knowing
the SDK details.

Three things this exports:

1. `configure(level)` — call once at process startup (the server's
   lifespan calls it). Sets up structlog for JSON-to-stdout logging
   and OTel SDK with a no-op (in-memory) exporter. Idempotent —
   safe to call multiple times; subsequent calls are no-ops.

2. `get_logger(name)` — structlog logger getter. Eval CLI code that
   doesn't call `configure()` gets stdlib-style behavior; server
   code gets JSON output once configured.

3. `span(name, **attrs)` — context manager wrapping OTel
   `start_as_current_span` with attribute setting. No-op when OTel
   isn't configured (eval CLI path) so adding spans inside `rag.py`
   doesn't break the CLI surface.

The "no-op when not configured" property is the load-bearing design
choice: it means `rag.py` can be instrumented with spans without the
eval CLI paying any cost (no SDK init, no per-call overhead beyond
a single contextvar lookup).
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_configured: bool = False
_in_memory_exporter: InMemorySpanExporter | None = None


def _is_configured() -> bool:
    return _configured


def configure(level: str = "INFO", in_memory_spans: bool = True) -> None:
    """Set up structlog (JSON to stdout) + OTel SDK (no-op exporter).

    Args:
        level: stdlib logging level for the stdlib handler that
            structlog wraps. Default INFO.
        in_memory_spans: when True (default), uses an InMemorySpanExporter
            so tests can introspect spans. Production use should keep
            this on for v1 (no real exporter wired yet); Phase 8.5
            deploy work will swap in a real exporter (Honeycomb /
            Grafana Tempo / etc.).

    Idempotent. Safe to call from multiple entry points.
    """
    global _configured, _in_memory_exporter
    # ---- structlog ----
    # Always re-configure structlog (it's safe to call configure() repeatedly,
    # and tests may have monkeypatched it with custom factories). The
    # OTel TracerProvider, on the other hand, is single-shot per process —
    # handled below.
    # Processors chain:
    #   1. merge_contextvars: pull request_id / trace_id off contextvars
    #      into the event dict (set by middleware)
    #   2. add_log_level
    #   3. TimeStamper: ISO-8601 timestamp
    #   4. StackInfoRenderer + format_exc_info: render tracebacks
    #   5. JSONRenderer: final JSON-to-stdout serialization
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ---- OpenTelemetry ----
    # `set_tracer_provider` is single-shot per process; subsequent
    # calls warn + no-op. Set it ONLY once across calls. Tests clear
    # the exporter's captured spans between cases via reset_for_tests.
    if not _configured:
        provider = TracerProvider()
        if in_memory_spans:
            _in_memory_exporter = InMemorySpanExporter()
            provider.add_span_processor(SimpleSpanProcessor(_in_memory_exporter))
        trace.set_tracer_provider(provider)
        _configured = True
    elif _in_memory_exporter is not None:
        # Re-config call after initial setup — just clear the exporter
        # so the caller (a test) sees fresh span state.
        _in_memory_exporter.clear()


def reset_for_tests() -> None:
    """Clear captured spans between tests. Does NOT reset the
    TracerProvider — OTel's `set_tracer_provider` is single-shot per
    process, and trying to swap it produces a warning + no effect.
    The in-memory exporter persists across tests; we just clear its
    state. structlog state is reset so configure() can rebuild the
    chain with test-specific factories."""
    if _in_memory_exporter is not None:
        _in_memory_exporter.clear()
    # structlog state IS swappable — reset so re-configure() works
    structlog.reset_defaults()


def get_logger(name: str = "rag_leis") -> Any:
    """Return a structlog logger. Falls back to a plain logger if
    configure() hasn't been called (eval CLI path)."""
    return structlog.get_logger(name)


def get_in_memory_exporter() -> InMemorySpanExporter | None:
    """Expose the in-memory exporter for tests. Returns None when
    configure() wasn't called or wasn't asked to use in-memory."""
    return _in_memory_exporter


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    """Context manager: starts an OTel span if configured, otherwise
    a no-op. Attributes set on the span via **attrs.

    Usage in `rag.py`:

        with obs.span("pipeline.retrieve", top_k=10) as s:
            results = self._retrieve(query, k)
            s.set_attribute("n_results", len(results))

    The `s` value is a real OTel span when configured; a `_NullSpan`
    otherwise (set_attribute is a no-op). This means `rag.py` can be
    instrumented without the eval CLI paying any cost.
    """
    if not _configured:
        yield _NullSpan()
        return
    tracer = trace.get_tracer("rag_leis")
    with tracer.start_as_current_span(name) as otel_span:
        for k, v in attrs.items():
            if v is not None:
                otel_span.set_attribute(k, v)
        yield otel_span


class _NullSpan:
    """No-op span returned when OTel isn't configured. Mirrors the
    OTel span API surface that `rag.py` calls (set_attribute)."""

    def set_attribute(self, key: str, value: Any) -> None:
        return

    def set_attributes(self, attrs: dict[str, Any]) -> None:
        return

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        return
