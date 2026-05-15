"""Tests for RAGPipeline._compute_hierarchy_warning (Phase 5.2).

Brazilian normative hierarchy: CF > LC > LO > Decreto > Resolução.
The warning fires when the model cites lower-rank sources while
higher-rank ones were in top-K context.

Pure-logic tests using mocked pipeline (no network, no real chunks).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from rag_leis.eval_harness import IndexChunk
from rag_leis.legal_rank import (
    RANK_CONSTITUCIONAL,
    RANK_DECRETO,
    RANK_INFRALEGAL,
    RANK_LEI_ORDINARIA,
)
from rag_leis.rag import RAGPipeline


def _make_chunk(urn: str, rank: int = RANK_LEI_ORDINARIA) -> IndexChunk:
    return IndexChunk(
        urn=urn,
        text=f"texto {urn[-10:]}",
        nav_text="",
        caput_text="",
        citation="",
        vigencia=None,
        legal_rank=rank,
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


def test_no_warning_when_cited_includes_highest_rank():
    """Model cited CF + Decreto, with CF being the highest-rank chunk
    in top-K. No warning — model used the best authority."""
    cf = _make_chunk("urn:cf;art1", rank=RANK_CONSTITUCIONAL)
    decreto = _make_chunk("urn:dec;art1", rank=RANK_DECRETO)
    pipe = _make_pipeline([cf, decreto])
    warn = pipe._compute_hierarchy_warning(
        verified_urns=[cf.urn, decreto.urn],
        retrieved=[(cf.urn, 0.7), (decreto.urn, 0.6)],
    )
    assert warn is None


def test_warning_when_cited_only_lower_rank():
    """Model cited only Decreto when CF was available in top-K."""
    cf = _make_chunk("urn:cf;art1", rank=RANK_CONSTITUCIONAL)
    decreto = _make_chunk("urn:dec;art1", rank=RANK_DECRETO)
    pipe = _make_pipeline([cf, decreto])
    warn = pipe._compute_hierarchy_warning(
        verified_urns=[decreto.urn],  # only the lower-rank source
        retrieved=[(cf.urn, 0.7), (decreto.urn, 0.6)],
    )
    assert warn is not None
    assert "⚠️" in warn
    assert "hierarquia normativa" in warn.lower()
    # The warning mentions the higher-rank URN that was passed over
    assert "urn:cf;art1" in warn


def test_warning_lei_over_resolucao():
    """Cited Resolução (rank 5) while Lei (rank 3) was in top-K."""
    lei = _make_chunk("urn:lex:br:federal:lei:2018-08-14;13709~art7", rank=RANK_LEI_ORDINARIA)
    res = _make_chunk(
        "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2023-02-24;4~art1",
        rank=RANK_INFRALEGAL,
    )
    pipe = _make_pipeline([lei, res])
    warn = pipe._compute_hierarchy_warning(
        verified_urns=[res.urn],
        retrieved=[(lei.urn, 0.7), (res.urn, 0.6)],
    )
    assert warn is not None
    assert "Lei Ordinária" in warn


def test_no_warning_when_no_citations():
    """Refused / OOS / empty citations — never warn (nothing to compare)."""
    pipe = _make_pipeline([_make_chunk("urn:x;art1")])
    warn = pipe._compute_hierarchy_warning(
        verified_urns=[],
        retrieved=[("urn:x;art1", 0.7)],
    )
    assert warn is None


def test_no_warning_when_all_same_rank():
    """Top-K is all LO; cited subset of LO. No hierarchy issue."""
    a = _make_chunk("urn:lei;arta", rank=RANK_LEI_ORDINARIA)
    b = _make_chunk("urn:lei;artb", rank=RANK_LEI_ORDINARIA)
    pipe = _make_pipeline([a, b])
    warn = pipe._compute_hierarchy_warning(
        verified_urns=[a.urn],
        retrieved=[(a.urn, 0.7), (b.urn, 0.6)],
    )
    assert warn is None


def test_unknown_urns_in_citations_dont_crash():
    """If a verified URN somehow isn't in chunks_by_urn (defensive — verify
    should reject before we get here), don't crash."""
    a = _make_chunk("urn:cf;art1", rank=RANK_CONSTITUCIONAL)
    pipe = _make_pipeline([a])
    # cited URN doesn't exist in chunks_by_urn
    warn = pipe._compute_hierarchy_warning(
        verified_urns=["urn:phantom"],
        retrieved=[(a.urn, 0.7)],
    )
    assert warn is None  # no cited chunks to compare → no warning
