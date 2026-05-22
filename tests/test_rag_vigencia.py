"""Integration of vigência overlays with RAGPipeline.

Three layers of test:
  1. Pure-logic on `_build_context` — overlay renders into <fonte> XML
  2. Pure-logic on `_collect_flagged_vigencia` — only overlaid chunks
     surface; non-overlaid cited URNs are silently passed through
  3. Cross-module: load_chunks finds overlays.yaml relative to data dir
     and populates IndexChunk.vigencia for matching URNs (the canonical
     MCI art. 19 case)

The live-pipeline assertion (model emits ⚠️ when context has the
attribute) is in the network-marked smoke test in tests/test_llm.py
or eval/runs/ logs — not duplicated here to keep this file fast.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from rag_leis.eval_harness import IndexChunk, load_chunks
from rag_leis.rag import FlaggedVigencia, RAGPipeline
from rag_leis.vigencia import Vigencia


def _make_chunk(urn: str, text: str = "caput text", vigencia: Vigencia | None = None) -> IndexChunk:
    return IndexChunk(
        urn=urn,
        text=text,
        nav_text="LGPD > Capítulo II",
        caput_text="",
        citation="Art. 7",
        vigencia=vigencia,
    )


def _make_pipeline(chunks: list[IndexChunk]) -> RAGPipeline:
    return RAGPipeline(
        embedder=MagicMock(),
        urns=[c.urn for c in chunks],
        doc_vecs=np.zeros((len(chunks), 4), dtype=np.float32),
        chunks_by_urn={c.urn: c for c in chunks},
        llm=MagicMock(),
        top_k=10,
        oos_threshold=0.0,
    )


def test_build_context_omits_vigencia_attr_when_unset():
    """Backward-compat: a chunk without overlay gets the bare <fonte urn=...>
    tag the older eval runs verified against. No accidental attribute leak."""
    pipe = _make_pipeline([_make_chunk("urn:test;art1", "Texto operativo.")])
    ctx = pipe._build_context([("urn:test;art1", 0.7)])
    assert "<fonte urn=" in ctx
    assert "vigencia=" not in ctx


def test_build_context_renders_vigencia_attr_when_set():
    """An overlaid chunk renders `vigencia="..."` containing status,
    fundamento, and the ⚠️ marker that the SYSTEM_PROMPT keys off."""
    vig = Vigencia(
        status="sub_judice",
        fundamento="STF Tema 987",
        desde="2017-09-29",
        descricao_curta="Aplicação em discussão no STF.",
    )
    pipe = _make_pipeline([_make_chunk("urn:test;art1", vigencia=vig)])
    ctx = pipe._build_context([("urn:test;art1", 0.7)])
    assert 'vigencia="' in ctx
    assert "sub_judice" in ctx
    assert "STF Tema 987" in ctx
    assert "⚠️" in ctx
    assert "2017-09-29" in ctx


def test_collect_flagged_vigencia_filters_to_overlaid_only():
    """Cited URNs without overlay are silently passed through; only
    overlaid chunks emit FlaggedVigencia entries."""
    vig = Vigencia(
        status="sub_judice",
        fundamento="STF Tema 987",
        desde="2017-09-29",
        descricao_curta="x",
    )
    pipe = _make_pipeline([
        _make_chunk("urn:test;art1", vigencia=vig),
        _make_chunk("urn:test;art2"),  # no overlay
    ])
    flagged = pipe._collect_flagged_vigencia(["urn:test;art1", "urn:test;art2"])
    assert len(flagged) == 1
    assert isinstance(flagged[0], FlaggedVigencia)
    assert flagged[0].urn == "urn:test;art1"
    assert flagged[0].status == "sub_judice"
    assert flagged[0].fundamento == "STF Tema 987"


def test_collect_flagged_vigencia_skips_unknown_urn():
    """If LLM cites an URN that's somehow not in chunks_by_urn (verify
    should have rejected it, but defensive-coding), don't crash."""
    pipe = _make_pipeline([_make_chunk("urn:test;art1")])
    flagged = pipe._collect_flagged_vigencia(["urn:not-in-corpus"])
    assert flagged == []


@pytest.mark.requires_local_data
def test_load_chunks_applies_real_overlays_to_mci_art19():
    """End-to-end: the canonical MCI art. 19 case from the reviewer's
    critique. With overlays.yaml in place, that IndexChunk MUST carry
    vigencia.status='sub_judice' and Tema 987 in fundamento."""
    project_root = Path(__file__).resolve().parents[1]
    chunks = load_chunks(project_root / "data" / "chunks")
    by_urn = {c.urn: c for c in chunks}
    art19 = by_urn.get("urn:lex:br:federal:lei:2014-04-23;12965~art19")
    assert art19 is not None, "MCI art.19 must be indexed (corpus regression?)"
    assert art19.vigencia is not None, (
        "MCI art.19 must carry vigência overlay — auto-discovery of "
        "data/vigencia/overlays.yaml broke OR overlays.yaml lost the entry"
    )
    # Phase 16.2 (2026-05-22) — MCI art.19 movido de `sub_judice` para
    # `alterado_por_jurisprudencia` após o STF fixar a tese do Tema 987
    # em 26/06/2024. Status `sub_judice` afirmava que a matéria estava
    # pendente; era falso.
    assert art19.vigencia.status == "alterado_por_jurisprudencia"
    assert "Tema 987" in art19.vigencia.fundamento
    assert "2024-06-26" in art19.vigencia.fundamento


@pytest.mark.requires_local_data
def test_load_chunks_no_overlay_no_vigencia():
    """A chunk WITHOUT an overlay entry must have vigencia=None — not
    coerced to 'vigente' or any other sentinel. None is the truth signal
    for downstream code (`if chunk.vigencia is not None`)."""
    project_root = Path(__file__).resolve().parents[1]
    chunks = load_chunks(project_root / "data" / "chunks")
    by_urn = {c.urn: c for c in chunks}
    # LGPD art.7 is not in the v0 overlays — should be None.
    art7 = by_urn.get("urn:lex:br:federal:lei:2018-08-14;13709~art7")
    assert art7 is not None
    assert art7.vigencia is None


# ----------------------------------------------------------------------------
# Live integration — actually call sonnet-4-5 and assert the overlay-driven
# warning surfaces in the answer text. Marked `network` (skipped by default
# `pytest`); run explicitly with `pytest -m network`. Costs ~1 sonnet call.
# ----------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.requires_local_data
@pytest.mark.skipif(
    "ANTHROPIC_API_KEY" not in os.environ,
    reason="ANTHROPIC_API_KEY not set; skipping live API test",
)
def test_pipeline_emits_vigencia_warning_for_mci_art19():
    """The canonical integration: a query about MCI art. 19 must cause the
    pipeline to (a) populate flagged_vigencia and (b) the model must emit
    ⚠️ Atenção + reference to Tema 987 in its answer text. This is the
    end-to-end test that the SYSTEM_PROMPT change is doing real work, not
    just decorating the context.

    Phase 16.3 added a `PENDENTE_` filter in load_chunks that excludes 3
    Tier-4 stub Temas — any Voyage index built before May 22 2026 is
    stale by 3 chunks and will fail the cache_is_fresh check. Rather
    than fail loudly here (the test isn't about cache freshness), we
    detect the stale state up-front and skip with the rebuild command,
    matching the requires_local_data marker added above.
    """
    project_root = Path(__file__).resolve().parents[1]
    # Stale-cache guard — cheap to compute (~7k chunks, ~30ms).
    import json as _json

    from rag_leis.cache import texts_hash
    from rag_leis.eval_harness import format_texts, load_chunks

    text_mode = "title+label+nav+caput+text"
    meta_path = (
        project_root / "data" / "index" / f"voyage-3-large__{text_mode}.meta.json"
    )
    if not meta_path.exists():
        pytest.skip(
            f"Voyage index not built at {meta_path}. Build it with: "
            f"`uv run python -m rag_leis.run_eval --model voyage-3-large "
            f"--text-mode {text_mode}`."
        )
    current_hash = texts_hash(
        format_texts(load_chunks(project_root / "data" / "chunks"), text_mode)
    )
    cached_hash = _json.loads(meta_path.read_text(encoding="utf-8")).get(
        "content_hash", ""
    )
    if current_hash != cached_hash:
        pytest.skip(
            f"Voyage index stale (current chunks hash "
            f"{current_hash[:8]}… != cached {cached_hash[:8]}…). "
            f"Rebuild with: `uv run python -m rag_leis.run_eval "
            f"--model voyage-3-large --text-mode {text_mode}`."
        )

    from rag_leis.rag import load_pipeline

    pipe = load_pipeline(
        chunks_dir=project_root / "data" / "chunks",
        index_dir=project_root / "data" / "index",
    )
    ans = pipe.answer(
        "qual o regime de responsabilidade do provedor de aplicações de "
        "internet por conteúdo de terceiros?"
    )
    # (a) Pipeline-side: art.19 should be flagged (and was cited).
    flagged_urns = {fv.urn for fv in ans.flagged_vigencia}
    assert "urn:lex:br:federal:lei:2014-04-23;12965~art19" in flagged_urns, (
        f"art.19 should appear in flagged_vigencia; got {flagged_urns}"
    )
    # (b) Answer-side: model must emit ⚠️ + Tema 987 reference.
    assert "⚠️" in ans.answer, "model must surface ⚠️ marker"
    assert "Tema 987" in ans.answer, "model must reference STF Tema 987"
    # And the overall answer must NOT be a refusal (in-scope query).
    assert not ans.refused, f"in-scope query refused unexpectedly: {ans.refusal_reason}"
