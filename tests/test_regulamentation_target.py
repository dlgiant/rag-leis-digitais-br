"""Phase 17.6 — tests for the regulamento → parent-lei registry.

Covers:
  * Registry file parses + filters out underscore-prefixed doc keys
    (the schema reserves those for `_schema_version`, `_note`,
    `_evidence` documentation strings).
  * IndexChunk.regulamenta_{urn,label} populate when chunk's doc is
    in the registry.
  * IndexChunk fields stay empty when chunk's doc is NOT in the
    registry (the common case — registry only covers the 3 known
    regulamentos in the corpus).
  * `<fonte>` rendering: `_build_context` emits regulamenta_urn +
    regulamenta_label as XML attributes when present, omits them
    otherwise.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from rag_leis.eval_harness import (
    IndexChunk,
    _locate_regulamentation_targets_registry,
    load_chunks,
)
from rag_leis.rag import RAGPipeline


# ---------------------------------------------------------------------------
# Registry locator + schema validation
# ---------------------------------------------------------------------------


def test_registry_file_exists_and_parses():
    """The shipped registry MUST parse as valid JSON."""
    project_root = Path(__file__).resolve().parents[1]
    path = project_root / "data" / "metadata" / "regulamentation_targets.json"
    assert path.exists(), f"missing: {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_registry_covers_known_regulamentos():
    """The three regulamentos we know about must be in the registry
    with both regulamenta_urn + regulamenta_label fields populated.
    Future Phase 18.x docs added to the registry are welcome but the
    minimum set is asserted here."""
    project_root = Path(__file__).resolve().parents[1]
    path = project_root / "data" / "metadata" / "regulamentation_targets.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    required_urns = {
        "urn:lex:br:federal:decreto:2016-05-11;8771": "urn:lex:br:federal:lei:2014-04-23;12965",
        "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2023-02-24;4": "urn:lex:br:federal:lei:2018-08-14;13709",
        "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15": "urn:lex:br:federal:lei:2018-08-14;13709",
    }
    for doc_urn, expected_parent in required_urns.items():
        assert doc_urn in data, f"missing registry entry: {doc_urn}"
        entry = data[doc_urn]
        assert entry.get("regulamenta_urn") == expected_parent
        assert entry.get("regulamenta_label"), (
            f"{doc_urn}: regulamenta_label must be a non-empty string"
        )


def test_locate_registry_walks_up_from_chunks_dir(tmp_path):
    """Mirrors the fetched_at registry walk-up behavior — locator
    succeeds whether passed the chunks dir or a deeper subdir."""
    metadata = tmp_path / "data" / "metadata"
    metadata.mkdir(parents=True)
    reg = metadata / "regulamentation_targets.json"
    reg.write_text('{"_schema_version": 1}', encoding="utf-8")

    chunks_dir = tmp_path / "data" / "chunks" / "tier-1"
    chunks_dir.mkdir(parents=True)
    deeper = chunks_dir / "subdir"
    deeper.mkdir()

    assert _locate_regulamentation_targets_registry(chunks_dir) == reg
    assert _locate_regulamentation_targets_registry(deeper) == reg


def test_locate_registry_returns_none_when_absent(tmp_path):
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir(parents=True)
    assert _locate_regulamentation_targets_registry(chunks_dir) is None


# ---------------------------------------------------------------------------
# load_chunks populates regulamenta_* fields
# ---------------------------------------------------------------------------


def _write_chunk(path: Path, document_urn: str, urn_suffix: str, text: str):
    """Minimal fixture chunk-row writer."""
    row = {
        "document_urn": document_urn,
        "urn": f"{document_urn}~{urn_suffix}",
        "partition": urn_suffix,
        "kind": "artigo",
        "label": "Art. 1",
        "text": text,
        "parent_partition": None,
        "nav": {},
        "notes": [],
        "is_revoked": False,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _make_tree(tmp_path: Path, registry: dict | None = None) -> Path:
    """Build a minimal chunks-dir tree with an optional registry."""
    chunks_dir = tmp_path / "data" / "chunks" / "tier-1"
    chunks_dir.mkdir(parents=True)
    if registry is not None:
        metadata_dir = tmp_path / "data" / "metadata"
        metadata_dir.mkdir(parents=True)
        (metadata_dir / "regulamentation_targets.json").write_text(
            json.dumps(registry), encoding="utf-8",
        )
    return chunks_dir


def test_chunk_in_registry_gets_regulamenta_fields(tmp_path):
    """A chunk whose document_urn is registered → both fields populate."""
    registry = {
        "_schema_version": 1,
        "urn:lex:br:federal:decreto:2016-05-11;8771": {
            "regulamenta_urn": "urn:lex:br:federal:lei:2014-04-23;12965",
            "regulamenta_label": "Marco Civil da Internet (Lei 12.965/2014)",
        },
    }
    chunks_dir = _make_tree(tmp_path, registry)
    _write_chunk(
        chunks_dir / "decreto_8771.jsonl",
        document_urn="urn:lex:br:federal:decreto:2016-05-11;8771",
        urn_suffix="art1",
        text="Este Decreto regulamenta a Lei nº 12.965, de 23 de abril de 2014.",
    )

    chunks = load_chunks(chunks_dir)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.regulamenta_urn == "urn:lex:br:federal:lei:2014-04-23;12965"
    assert c.regulamenta_label == "Marco Civil da Internet (Lei 12.965/2014)"


def test_chunk_not_in_registry_has_empty_fields(tmp_path):
    """A chunk whose document_urn is absent → fields stay empty.
    Pre-17.6 behavior for any document that doesn't regulamentate
    another (original legislation, jurisprudência, etc.)."""
    registry = {
        "_schema_version": 1,
        "urn:lex:br:federal:decreto:2016-05-11;8771": {
            "regulamenta_urn": "urn:lex:br:federal:lei:2014-04-23;12965",
            "regulamenta_label": "Marco Civil da Internet (Lei 12.965/2014)",
        },
    }
    chunks_dir = _make_tree(tmp_path, registry)
    _write_chunk(
        chunks_dir / "lgpd.jsonl",
        document_urn="urn:lex:br:federal:lei:2018-08-14;13709",
        urn_suffix="art5",
        text="Para os fins desta Lei, considera-se: I - dado pessoal: ...",
    )

    chunks = load_chunks(chunks_dir)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.regulamenta_urn == ""
    assert c.regulamenta_label == ""


def test_registry_absent_degrades_to_empty_fields(tmp_path):
    """No registry file at all → chunks load with empty fields
    (graceful degradation; no crash on fresh checkouts)."""
    chunks_dir = _make_tree(tmp_path, registry=None)
    _write_chunk(
        chunks_dir / "decreto_8771.jsonl",
        document_urn="urn:lex:br:federal:decreto:2016-05-11;8771",
        urn_suffix="art1",
        text="Este Decreto regulamenta a Lei nº 12.965, de 23 de abril de 2014.",
    )
    chunks = load_chunks(chunks_dir)
    assert chunks[0].regulamenta_urn == ""
    assert chunks[0].regulamenta_label == ""


def test_registry_filters_underscore_prefixed_keys(tmp_path):
    """`_schema_version`, `_note`, `_evidence` etc. must be ignored —
    they're documentation, not regulamento entries."""
    registry = {
        "_schema_version": 1,
        "_note": "this is documentation, not a registry entry",
        "urn:lex:br:federal:decreto:2016-05-11;8771": {
            "regulamenta_urn": "urn:lex:br:federal:lei:2014-04-23;12965",
            "regulamenta_label": "Marco Civil da Internet (Lei 12.965/2014)",
            "_evidence": "documentation field — also ignored",
        },
    }
    chunks_dir = _make_tree(tmp_path, registry)
    # A chunk whose document_urn LITERALLY equals "_schema_version"
    # should NOT pick up that registry entry. (Synthetic adversarial
    # case — guards against a future bug where a doc URN happens to
    # start with underscore.)
    _write_chunk(
        chunks_dir / "weird.jsonl",
        document_urn="_schema_version",
        urn_suffix="art1",
        text="Adversarial document URN starting with underscore.",
    )
    chunks = load_chunks(chunks_dir)
    assert chunks[0].regulamenta_urn == ""
    assert chunks[0].regulamenta_label == ""


# ---------------------------------------------------------------------------
# _build_context renders the attributes
# ---------------------------------------------------------------------------


@dataclass
class _MinimalPipelineForBuildContext:
    """Just enough surface to call RAGPipeline._build_context as an
    unbound method. Avoids the full pipeline-construction cost."""

    chunks_by_urn: dict[str, IndexChunk]


def _build_context(chunks_by_urn: dict[str, IndexChunk], retrieved: list[tuple[str, float]]) -> str:
    """Call the real _build_context with a stand-in self. The method
    only reads `self.chunks_by_urn`; nothing else from pipeline state."""
    pipeline_stub = _MinimalPipelineForBuildContext(chunks_by_urn=chunks_by_urn)
    return RAGPipeline._build_context(pipeline_stub, retrieved)  # type: ignore[arg-type]


def _make_chunk(*, urn: str, text: str, regulamenta_urn: str = "", regulamenta_label: str = "") -> IndexChunk:
    return IndexChunk(
        urn=urn,
        text=text,
        nav_text="",
        caput_text="",
        citation="Art. 1",
        regulamenta_urn=regulamenta_urn,
        regulamenta_label=regulamenta_label,
    )


def test_build_context_emits_regulamenta_attrs_when_present():
    """`<fonte>` for a regulamento chunk includes both attrs."""
    urn = "urn:lex:br:federal:decreto:2016-05-11;8771~art1"
    chunk = _make_chunk(
        urn=urn,
        text="Este Decreto regulamenta a Lei nº 12.965/2014.",
        regulamenta_urn="urn:lex:br:federal:lei:2014-04-23;12965",
        regulamenta_label="Marco Civil da Internet (Lei 12.965/2014)",
    )
    ctx = _build_context({urn: chunk}, [(urn, 0.85)])

    assert 'regulamenta_urn="urn:lex:br:federal:lei:2014-04-23;12965"' in ctx
    assert 'regulamenta_label="Marco Civil da Internet (Lei 12.965/2014)"' in ctx
    # urn= attr must still come first (LLM-prompt stability — we don't
    # want attr-order churn to surprise the model).
    assert ctx.find(f'urn="{urn}"') < ctx.find("regulamenta_urn=")


def test_build_context_omits_regulamenta_attrs_when_absent():
    """`<fonte>` for an original-lei chunk renders without the attrs —
    pre-17.6 shape is preserved for non-regulamento documents."""
    urn = "urn:lex:br:federal:lei:2018-08-14;13709~art5"
    chunk = _make_chunk(urn=urn, text="Para os fins desta Lei, considera-se: ...")
    ctx = _build_context({urn: chunk}, [(urn, 0.85)])
    assert "regulamenta_urn=" not in ctx
    assert "regulamenta_label=" not in ctx


def test_build_context_escapes_double_quotes_in_label():
    """Defensive: a regulamenta_label containing a double-quote would
    break the XML attribute. The renderer must substitute or escape it.
    Brazilian legal titles don't typically contain `"`, but we guard
    against the adversarial input regardless."""
    urn = "urn:lex:br:federal:decreto:2016-05-11;8771~art1"
    chunk = _make_chunk(
        urn=urn,
        text="x",
        regulamenta_urn="urn:lex:br:federal:lei:2014-04-23;12965",
        regulamenta_label='Lei "Marco Civil" (12.965/2014)',
    )
    ctx = _build_context({urn: chunk}, [(urn, 0.85)])
    # The attr value MUST be valid (no unescaped " inside the value).
    # We accept either escape or single-quote substitution.
    assert 'regulamenta_label="Lei \'Marco Civil\' (12.965/2014)"' in ctx


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT carries the new rule
# ---------------------------------------------------------------------------


def test_system_prompt_documents_regulamento_rule():
    """The rule must mention both new attribute names and the contract
    (no refusal on orphaned regulamento; mention parent lei in text;
    don't cite parent URN). Pre-17.6 commits had no such rule."""
    from rag_leis.rag import SYSTEM_PROMPT

    assert "regulamenta_urn" in SYSTEM_PROMPT
    assert "regulamenta_label" in SYSTEM_PROMPT
    # The "don't refuse on orphaned regulamento" wording is the
    # load-bearing line — without it the fix is cosmetic.
    assert "NÃO recuse" in SYSTEM_PROMPT or "não recuse" in SYSTEM_PROMPT.lower()
    # The "cite only the regulamento URN" rule must be explicit so the
    # model doesn't hallucinate the parent lei as a citation.
    assert "APENAS o URN do regulamento" in SYSTEM_PROMPT or "apenas o urn" in SYSTEM_PROMPT.lower()
