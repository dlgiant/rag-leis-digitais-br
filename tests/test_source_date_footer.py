"""Tests for Phase 5.5 — source-as-of-date footer rendering.

Pure-logic + integration with mocked pipeline. Validates:
  - IndexChunk.fetched_at populated by load_chunks (from JSONL mtime)
  - _render_sources_footer produces the practitioner-facing format
  - Pipeline appends footer to answer.text only when in-scope citations exist
  - Footer uses doc title (from corpus.py) + DD/MM/YYYY format
  - Order is stable (sorted by URN)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from rag_leis.eval_harness import IndexChunk, load_chunks
from rag_leis.rag import (
    RAGPipeline,
    _doc_label,
    _format_date_pt_br,
    _render_sources_footer,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------
# Pure-logic helpers
# ----------------------------------------------------------------------------


def test_format_date_pt_br():
    assert _format_date_pt_br("2026-05-15") == "15/05/2026"
    assert _format_date_pt_br("2024-01-01") == "01/01/2024"


def test_format_date_pt_br_passes_through_malformed():
    """Don't crash on weird input — pass through; downstream sees it as-is."""
    assert _format_date_pt_br("not-a-date") == "not-a-date"
    assert _format_date_pt_br("") == ""


def test_doc_label_known_urn():
    """Known TIER_1 URN returns its title."""
    label = _doc_label("urn:lex:br:federal:lei:2018-08-14;13709")
    assert "LGPD" in label or "13.709" in label


def test_doc_label_unknown_urn_falls_back_gracefully():
    """Unknown URN: synthesize a label from the URN parts."""
    label = _doc_label("urn:lex:br:federal:lei:2099-01-01;9999")
    assert "9999" in label or "lei" in label.lower()


# ----------------------------------------------------------------------------
# Footer rendering
# ----------------------------------------------------------------------------


def test_render_footer_single_doc():
    sources = {"urn:lex:br:federal:lei:2018-08-14;13709": "2026-05-14"}
    out = _render_sources_footer(sources)
    assert out.startswith("—\nFontes consultadas em: ")
    assert "14/05/2026" in out
    assert out.endswith(".")


def test_render_footer_multiple_docs_sorted():
    """Sorted by URN for stable output across runs (UI diff-friendly)."""
    sources = {
        "urn:lex:br:federal:lei:2014-04-23;12965": "2026-05-15",  # MCI
        "urn:lex:br:federal:constituicao:1988-10-05;1988": "2026-05-14",  # CF
    }
    out = _render_sources_footer(sources)
    # CF URN sorts before MCI URN alphabetically (constituicao < lei)
    cf_pos = out.find("Constituição")
    mci_pos = out.find("Marco Civil")
    if cf_pos != -1 and mci_pos != -1:
        assert cf_pos < mci_pos


def test_render_footer_includes_dd_mm_yyyy():
    sources = {"urn:lex:br:federal:constituicao:1988-10-05;1988": "2024-11-30"}
    out = _render_sources_footer(sources)
    assert "30/11/2024" in out


# ----------------------------------------------------------------------------
# Real load_chunks integration — fetched_at populated
# ----------------------------------------------------------------------------


def test_load_chunks_populates_fetched_at():
    """End-to-end: load_chunks reads the registry (Phase 16.1) or falls
    back to JSONL mtime → IndexChunk.fetched_at non-empty."""
    chunks = load_chunks(PROJECT_ROOT / "data" / "chunks")
    assert chunks
    # Pick any chunk; fetched_at should be ISO date format
    sample = chunks[0]
    assert sample.fetched_at != ""
    parts = sample.fetched_at.split("-")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
    # Year should look reasonable (not 1970 epoch fallback or future)
    year = int(parts[0])
    assert 2024 <= year <= 2030, f"unexpected fetched_at year {year}"


# ----------------------------------------------------------------------------
# Phase 16.1 — fetched_at registry overrides JSONL mtime
# ----------------------------------------------------------------------------


def _write_minimal_chunk(jsonl_path: Path, urn: str, document_urn: str) -> None:
    """Write a single chunk to jsonl. Schema is the minimal set load_chunks
    needs — keeps the test fixture independent of parser evolution."""
    import json as _json
    obj = {
        "urn": urn,
        "document_urn": document_urn,
        "text": "Texto de teste para o chunk — precisa passar do min_text_chars.",
        "nav": {"artigo": "Art. 1"},
        "label": "Art. 1",
        "parent_partition": None,
        "is_revoked": False,
        "notes": [],
    }
    jsonl_path.write_text(_json.dumps(obj) + "\n", encoding="utf-8")


def test_load_chunks_prefers_registry_over_mtime(tmp_path: Path):
    """Phase 16.1 — when data/metadata/fetched_at.json exists, its dates
    win over JSONL mtime. This is the load-bearing invariant: Docker COPY
    resets mtime to build date but preserves the registry's content."""
    chunks_dir = tmp_path / "data" / "chunks" / "tier-1"
    chunks_dir.mkdir(parents=True)
    jsonl = chunks_dir / "br_federal_lei_test.jsonl"
    doc_urn = "urn:lex:br:federal:lei:2020-01-01;9999"
    _write_minimal_chunk(jsonl, doc_urn + "~art1", doc_urn)
    # mtime says today (or whenever tmp_path was created); registry says
    # a year in the past. Registry must win.
    metadata_dir = tmp_path / "data" / "metadata"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "fetched_at.json").write_text(
        '{"' + doc_urn + '": "2025-03-15"}', encoding="utf-8"
    )

    chunks = load_chunks(tmp_path / "data" / "chunks")
    assert len(chunks) == 1
    assert chunks[0].fetched_at == "2025-03-15", (
        f"registry should win over mtime; got {chunks[0].fetched_at}"
    )


def test_load_chunks_falls_back_to_mtime_when_registry_absent(tmp_path: Path):
    """Phase 16.1 — fresh checkouts or docs not yet covered by the
    registry must fall back to mtime so existing behavior is preserved."""
    import datetime as _dt
    chunks_dir = tmp_path / "data" / "chunks" / "tier-1"
    chunks_dir.mkdir(parents=True)
    jsonl = chunks_dir / "br_federal_lei_test.jsonl"
    doc_urn = "urn:lex:br:federal:lei:2020-01-01;9999"
    _write_minimal_chunk(jsonl, doc_urn + "~art1", doc_urn)
    # No registry file written.

    chunks = load_chunks(tmp_path / "data" / "chunks")
    assert len(chunks) == 1
    # mtime fallback → today's date (the file was just written)
    expected = _dt.date.fromtimestamp(jsonl.stat().st_mtime).isoformat()
    assert chunks[0].fetched_at == expected


def test_load_chunks_registry_partial_coverage_falls_back_per_doc(tmp_path: Path):
    """Phase 16.1 — when the registry covers some docs but not others,
    covered docs use the registry date; uncovered docs fall back to mtime.
    This protects against a partial fetch run leaving the registry stale
    for some documents."""
    import datetime as _dt
    chunks_dir = tmp_path / "data" / "chunks" / "tier-1"
    chunks_dir.mkdir(parents=True)
    doc_a = "urn:lex:br:federal:lei:2020-01-01;1111"
    doc_b = "urn:lex:br:federal:lei:2020-01-01;2222"
    jsonl_a = chunks_dir / "a.jsonl"
    jsonl_b = chunks_dir / "b.jsonl"
    _write_minimal_chunk(jsonl_a, doc_a + "~art1", doc_a)
    _write_minimal_chunk(jsonl_b, doc_b + "~art1", doc_b)
    metadata_dir = tmp_path / "data" / "metadata"
    metadata_dir.mkdir(parents=True)
    # Only doc_a in the registry.
    (metadata_dir / "fetched_at.json").write_text(
        '{"' + doc_a + '": "2025-03-15"}', encoding="utf-8"
    )

    chunks = load_chunks(tmp_path / "data" / "chunks")
    by_doc = {c.urn.split("~")[0]: c for c in chunks}
    assert by_doc[doc_a].fetched_at == "2025-03-15"
    # doc_b falls back to its jsonl mtime
    expected_b = _dt.date.fromtimestamp(jsonl_b.stat().st_mtime).isoformat()
    assert by_doc[doc_b].fetched_at == expected_b


# ----------------------------------------------------------------------------
# Pipeline integration — footer appended to answer
# ----------------------------------------------------------------------------


def _make_chunk(urn: str, fetched: str = "2026-05-15") -> IndexChunk:
    return IndexChunk(
        urn=urn,
        text=f"texto {urn[-10:]}",
        nav_text="",
        caput_text="",
        citation="",
        vigencia=None,
        fetched_at=fetched,
    )


def _make_pipeline(chunks: list[IndexChunk]) -> RAGPipeline:
    embedder = MagicMock()
    embedder.name = "mock"
    embedder.embed_query.return_value = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    llm = MagicMock()
    llm.name = "mock-llm"
    llm.provider = "mock"
    llm.complete_structured.return_value = {
        "answer": "Resposta padrão sobre LGPD.",
        "citations": [chunks[0].urn],
        "unverified_claims": [],
    }
    return RAGPipeline(
        embedder=embedder,
        urns=[c.urn for c in chunks],
        doc_vecs=np.array([[1.0, 0.0, 0.0, 0.0]] * len(chunks), dtype=np.float32),
        chunks_by_urn={c.urn: c for c in chunks},
        llm=llm,
        top_k=10,
        oos_threshold=0.0,
        adaptive_top_k=False,
        redact_pii=False,
        pii_audit_log=None,
        prose_check_retry=False,
    )


def test_pipeline_appends_footer_when_cited():
    chunk = _make_chunk("urn:lex:br:federal:lei:2018-08-14;13709~art7", fetched="2026-05-15")
    pipe = _make_pipeline([chunk])
    ans = pipe.answer("o que é LGPD?")
    assert "Fontes consultadas em" in ans.answer
    assert "15/05/2026" in ans.answer
    assert ans.sources_consulted_at == {
        "urn:lex:br:federal:lei:2018-08-14;13709": "2026-05-15",
    }


def test_pipeline_no_footer_when_no_citations():
    """Mock LLM returns empty citations → no footer."""
    chunk = _make_chunk("urn:lex:br:federal:lei:2018-08-14;13709~art7")
    pipe = _make_pipeline([chunk])
    pipe.llm.complete_structured.return_value = {
        "answer": "Não posso responder.",
        "citations": [],
        "unverified_claims": [],
    }
    ans = pipe.answer("Pergunta")
    assert "Fontes consultadas em" not in ans.answer
    assert ans.sources_consulted_at == {}


def test_pipeline_no_footer_when_self_refused():
    """Self-refusal answer doesn't get a footer (would be misleading)."""
    chunk = _make_chunk("urn:lex:br:federal:lei:2018-08-14;13709~art7")
    pipe = _make_pipeline([chunk])
    pipe.llm.complete_structured.return_value = {
        "answer": "Não há informação suficiente nas fontes fornecidas.",
        "citations": [chunk.urn],
        "unverified_claims": [],
    }
    ans = pipe.answer("Pergunta")
    assert "Fontes consultadas em" not in ans.answer


def test_pipeline_footer_collapses_multiple_chunks_per_doc():
    """3 cited chunks from same doc → 1 entry in sources_consulted_at."""
    chunks = [
        _make_chunk("urn:lex:br:federal:lei:2018-08-14;13709~art7", fetched="2026-05-15"),
        _make_chunk("urn:lex:br:federal:lei:2018-08-14;13709~art8", fetched="2026-05-15"),
        _make_chunk("urn:lex:br:federal:lei:2018-08-14;13709~art9", fetched="2026-05-15"),
    ]
    pipe = _make_pipeline(chunks)
    pipe.llm.complete_structured.return_value = {
        "answer": "Resposta.",
        "citations": [c.urn for c in chunks],
        "unverified_claims": [],
    }
    ans = pipe.answer("Pergunta")
    assert len(ans.sources_consulted_at) == 1
    assert "2018-08-14;13709" in next(iter(ans.sources_consulted_at))
