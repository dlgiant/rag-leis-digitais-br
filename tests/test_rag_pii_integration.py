"""RAGPipeline + PII redactor integration.

No-network test that mocks the LLM and asserts the pipeline:
  1. Calls redact() before retrieve + LLM
  2. The LLM (mock) sees only redacted query, not original
  3. RAGAnswer.pii_types_redacted is populated for observability
  4. With redact_pii=False, original passes through (escape hatch)

The point is to lock the contract: PII must never cross provider
boundary, period. If a refactor accidentally bypasses redact(), this
test fails.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from rag_leis.eval_harness import IndexChunk
from rag_leis.rag import RAGPipeline


def _make_chunk(urn: str = "urn:test;art1", text: str = "Texto operativo.") -> IndexChunk:
    return IndexChunk(
        urn=urn,
        text=text,
        nav_text="LGPD > Capítulo I",
        caput_text="",
        citation="Art. 1",
        vigencia=None,
    )


def _make_pipeline_with_mock_llm(redact_pii: bool = True, audit_log: object = None) -> RAGPipeline:
    """Build a pipeline whose embedder + LLM are mocks. Embedder returns
    a fixed unit vector so similarity = 1.0 for the single chunk; LLM
    captures the user message it received."""
    embedder = MagicMock()
    embedder.name = "mock"
    embedder.embed_query.return_value = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    llm = MagicMock()
    llm.name = "mock-llm"
    llm.provider = "mock"
    llm.complete_structured.return_value = {
        "answer": "Resposta padrão.",
        "citations": [],
        "unverified_claims": [],
    }

    chunks = [_make_chunk()]
    return RAGPipeline(
        embedder=embedder,
        urns=[c.urn for c in chunks],
        doc_vecs=np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        chunks_by_urn={c.urn: c for c in chunks},
        llm=llm,
        top_k=10,
        oos_threshold=0.0,
        adaptive_top_k=False,  # disable classifier for cleaner assertions
        redact_pii=redact_pii,
        pii_audit_log=audit_log,  # None for tests = no disk side effect
    )


def test_pipeline_redacts_query_before_llm_call():
    """The canonical production case: PII-laden query must never reach LLM."""
    pipe = _make_pipeline_with_mock_llm(redact_pii=True)
    pipe.answer(
        "Vazaram o CPF 123.456.789-00 e o email joao@x.com do funcionário, "
        "qual o procedimento LGPD?"
    )
    # Inspect what the LLM received
    call_args = pipe.llm.complete_structured.call_args
    user_msg = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("user", "")
    assert "123.456.789-00" not in user_msg, (
        "PII leaked to LLM — redactor bypassed or broken"
    )
    assert "joao@x.com" not in user_msg, "Email PII leaked to LLM"
    assert "[CPF#1]" in user_msg, "Placeholder substitution missing from LLM input"
    assert "[EMAIL#1]" in user_msg, "Email placeholder missing"


def test_pipeline_redacts_query_before_embedder_call():
    """The query embedding also crosses a provider boundary (Voyage US).
    PII must not be in the embedded text either."""
    pipe = _make_pipeline_with_mock_llm(redact_pii=True)
    pipe.answer("CPF 111.111.111-11 vazou")
    embed_arg = pipe.embedder.embed_query.call_args.args[0]
    assert "111.111.111-11" not in embed_arg
    assert "[CPF#1]" in embed_arg


def test_pipeline_redact_pii_false_passes_through():
    """Escape hatch: callers can disable redaction (e.g., for A/B comparison
    or in tests where the query embedding needs to be deterministic against
    a known input). Original query reaches both embedder and LLM."""
    pipe = _make_pipeline_with_mock_llm(redact_pii=False)
    pipe.answer("CPF 111.111.111-11 vazou")
    embed_arg = pipe.embedder.embed_query.call_args.args[0]
    user_msg = pipe.llm.complete_structured.call_args.args[1]
    assert "111.111.111-11" in embed_arg
    assert "111.111.111-11" in user_msg


def test_ragacanswer_reports_pii_types_redacted():
    """Observability: caller sees which types were redacted."""
    pipe = _make_pipeline_with_mock_llm(redact_pii=True)
    ans = pipe.answer("CPF 111.111.111-11 e email a@b.com")
    assert sorted(ans.pii_types_redacted) == ["cpf", "email"]


def test_ragacanswer_pii_types_empty_for_clean_query():
    pipe = _make_pipeline_with_mock_llm(redact_pii=True)
    ans = pipe.answer("o que é dado pessoal na LGPD?")
    assert ans.pii_types_redacted == []


def test_audit_log_written_on_redact(tmp_path):
    """End-to-end audit log integration."""
    log_path = tmp_path / "audit.jsonl"
    pipe = _make_pipeline_with_mock_llm(redact_pii=True, audit_log=log_path)
    pipe.answer("CPF 999.888.777-66")
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert content.count("\n") == 1
    import json
    record = json.loads(content.strip())
    assert "cpf" in record["pii_types_found"]
    # Original PII must NOT be in the audit log
    assert "999.888.777-66" not in content


def test_audit_log_skipped_when_path_none(tmp_path):
    """Caller can disable audit logging by passing None — useful in tests
    and in production paths where logging is delegated to a different
    sink (Phase 7 observability)."""
    pipe = _make_pipeline_with_mock_llm(redact_pii=True, audit_log=None)
    # No log file ever created
    pipe.answer("CPF 999.888.777-66")
    # No exception, query proceeded.


def test_pipeline_works_when_audit_log_write_fails(tmp_path, monkeypatch):
    """Audit log write failure must NOT 500 the query — production-grade
    degradation. Pipeline keeps serving."""
    log_path = tmp_path / "noaccess" / "audit.jsonl"

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("rag_leis.rag.write_audit", boom)
    pipe = _make_pipeline_with_mock_llm(redact_pii=True, audit_log=log_path)
    # Should not raise
    ans = pipe.answer("CPF 999.888.777-66")
    assert ans.answer == "Resposta padrão."
