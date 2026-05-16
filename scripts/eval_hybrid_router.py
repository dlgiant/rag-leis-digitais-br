"""Compare hybrid router (title-prefix for law-name queries, baseline for the
rest) against pure baseline and pure title-prefix.

⚠️ EXPERIMENTAL — keep for future routing experiments, but not the production
operating point. Phase 6.6 r4 (2026-05-16) used this script to test the
"route by law-name mention" hypothesis and FOUND IT DOMINATED by pure
title-prefix for our nDCG-optimized RAG-to-LLM use case. Production
DEFAULT_TEXT_MODE in rag.py is now `title+label+nav+caput+text` (pure).

Use this script when:
  - testing a NEW routing heuristic (modify rag_leis.query_router.mentions_law_name
    or write a sibling detector)
  - measuring trade-offs between text-modes after corpus changes (per-route
    audit surfaces where each path wins/loses; agg numbers hide this)
  - validating that a future hybrid router doesn't regress vs pure title-prefix

Reads both pre-cached Voyage indices and embeds each query once. Routing
decision via `rag_leis.query_router.mentions_law_name`. Reports per-pipeline
aggregate metrics, per-type breakdown, and per-query routing decisions.

Uso:
  uv run python -m scripts.eval_hybrid_router

Pré-requisito: both indices cached:
  data/index/voyage-3-large__label+nav+caput+text.npz
  data/index/voyage-3-large__title+label+nav+caput+text.npz
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

from rag_leis.embeddings import get_embedder
from rag_leis.eval_harness import Query, mrr_at_k, ndcg_at_k, recall_at_k
from rag_leis.query_router import mentions_law_name

PROJECT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT / "data" / "index"


def _load_index(filename: str):
    cache = np.load(INDEX_DIR / filename, allow_pickle=True)
    return list(cache["urns"]), cache["vecs"]


def _parse_queries(path: Path) -> list[Query]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[Query] = []
    for item in data:
        rel = item.get("relevant")
        if isinstance(rel, dict):
            core = frozenset(rel.get("core", []))
            supporting = frozenset(rel.get("supporting", []))
        else:
            core = frozenset(rel or [])
            supporting = frozenset()
        out.append(
            Query(
                query=item["query"],
                core=core,
                supporting=supporting,
                qtype=item.get("type"),
                notes=item.get("notes"),
            )
        )
    return out


def _evaluate(retrieved_per_query: list[list[str]], queries: list[Query], k_recall: int = 20):
    """Aggregate nDCG@10, Recall@20, MRR@10 from retrieved URN lists."""
    ndcgs, recalls, mrrs = [], [], []
    for retrieved, q in zip(retrieved_per_query, queries, strict=True):
        rel_union = q.core | q.supporting
        ndcgs.append(ndcg_at_k(retrieved, q, 10))
        recalls.append(recall_at_k(retrieved, rel_union, k_recall))
        mrrs.append(mrr_at_k(retrieved, q.relevant, 10))
    return (
        sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
        sum(recalls) / len(recalls) if recalls else 0.0,
        sum(mrrs) / len(mrrs) if mrrs else 0.0,
    )


def _evaluate_by_type(retrieved_per_query, queries):
    by_type: dict[str, list[tuple]] = defaultdict(list)
    for retrieved, q in zip(retrieved_per_query, queries, strict=True):
        rel_union = q.core | q.supporting
        by_type[q.qtype or "unknown"].append((
            ndcg_at_k(retrieved, q, 10),
            recall_at_k(retrieved, rel_union, 20),
            mrr_at_k(retrieved, q.relevant, 10),
        ))
    rows = []
    for t in sorted(by_type):
        triples = by_type[t]
        n = len(triples)
        nd = sum(x[0] for x in triples) / n
        rc = sum(x[1] for x in triples) / n
        mrr = sum(x[2] for x in triples) / n
        rows.append((t, n, nd, rc, mrr))
    return rows


def main() -> int:
    baseline_urns, baseline_vecs = _load_index("voyage-3-large__label+nav+caput+text.npz")
    title_urns, title_vecs = _load_index("voyage-3-large__title+label+nav+caput+text.npz")
    assert baseline_urns == title_urns, "URN lists must align between caches"

    queries = _parse_queries(PROJECT / "eval" / "queries.yaml")
    print(f"Loaded {len(queries)} queries; corpus={len(baseline_urns)} chunks")

    embedder = get_embedder("voyage-3-large")

    # Embed every query once. Score against both indices.
    qvecs = np.asarray([embedder.embed_query(q.query) for q in queries], dtype=np.float32)
    sims_baseline = qvecs @ baseline_vecs.T
    sims_title = qvecs @ title_vecs.T

    K = 20

    def topk_urns(sims_row, urns):
        idx = np.argpartition(-sims_row, K - 1)[:K]
        idx = idx[np.argsort(-sims_row[idx])]
        return [urns[i] for i in idx]

    retrieved_baseline = [topk_urns(sims_baseline[i], baseline_urns) for i in range(len(queries))]
    retrieved_title = [topk_urns(sims_title[i], title_urns) for i in range(len(queries))]

    # Routing decision
    routes = [mentions_law_name(q.query) for q in queries]
    retrieved_hybrid = [
        retrieved_title[i] if routes[i] else retrieved_baseline[i]
        for i in range(len(queries))
    ]

    routed_to_title = sum(routes)
    print(f"Routing: {routed_to_title}/{len(queries)} → title-prefix ; "
          f"{len(queries) - routed_to_title}/{len(queries)} → baseline\n")

    print(f"{'pipeline':35} {'nDCG@10':>9} {'Recall@20':>11} {'MRR@10':>9}")
    for name, retrieved in [
        ("baseline (label+nav+caput+text)", retrieved_baseline),
        ("pure title-prefix", retrieved_title),
        ("hybrid (router)", retrieved_hybrid),
    ]:
        nd, rc, mrr = _evaluate(retrieved, queries)
        print(f"{name:35} {nd:9.4f} {rc:11.4f} {mrr:9.4f}")

    print("\nHybrid per-type:")
    print(f"  {'type':18} {'n':>3} {'nDCG@10':>9} {'Recall@20':>11} {'MRR@10':>9}")
    for t, n, nd, rc, mrr in _evaluate_by_type(retrieved_hybrid, queries):
        print(f"  {t:18} {n:>3} {nd:9.4f} {rc:11.4f} {mrr:9.4f}")

    # Per-route audit: did the router actually pick the BETTER pipeline for each query?
    print("\nRouter quality audit (does routing match per-query optimal?):")
    sub_baseline = [(retrieved_baseline[i], queries[i]) for i in range(len(queries)) if not routes[i]]
    sub_title    = [(retrieved_title[i],    queries[i]) for i in range(len(queries)) if routes[i]]

    def _agg(pairs):
        if not pairs: return (0.0, 0.0, 0.0)
        rs = [x[0] for x in pairs]; qs = [x[1] for x in pairs]
        return _evaluate(rs, qs)

    # For each routed subset, also compute what the OTHER pipeline would have given.
    sub_baseline_alt = [(retrieved_title[i],    queries[i]) for i in range(len(queries)) if not routes[i]]
    sub_title_alt    = [(retrieved_baseline[i], queries[i]) for i in range(len(queries)) if routes[i]]

    nd, rc, mrr = _agg(sub_baseline)
    nd2, rc2, mrr2 = _agg(sub_baseline_alt)
    print(f"  Routed→baseline ({len(sub_baseline)} q):")
    print(f"    chosen path: nDCG={nd:.4f}  Recall={rc:.4f}  MRR={mrr:.4f}")
    print(f"    if had used title-prefix instead: nDCG={nd2:.4f}  Recall={rc2:.4f}  MRR={mrr2:.4f}")
    print(f"    → routing-to-baseline gain: ΔnDCG={nd-nd2:+.4f}  ΔRecall={rc-rc2:+.4f}  ΔMRR={mrr-mrr2:+.4f}")

    nd, rc, mrr = _agg(sub_title)
    nd2, rc2, mrr2 = _agg(sub_title_alt)
    print(f"  Routed→title-prefix ({len(sub_title)} q):")
    print(f"    chosen path: nDCG={nd:.4f}  Recall={rc:.4f}  MRR={mrr:.4f}")
    print(f"    if had used baseline instead: nDCG={nd2:.4f}  Recall={rc2:.4f}  MRR={mrr2:.4f}")
    print(f"    → routing-to-title gain: ΔnDCG={nd-nd2:+.4f}  ΔRecall={rc-rc2:+.4f}  ΔMRR={mrr-mrr2:+.4f}")

    # Per-query: where does hybrid differ from baseline + title? Show only
    # queries where the choice changed the top-1 chunk.
    print("\nQueries where routing changed top-1:")
    changes = 0
    for i, q in enumerate(queries):
        chosen = retrieved_title[i] if routes[i] else retrieved_baseline[i]
        other = retrieved_baseline[i] if routes[i] else retrieved_title[i]
        if chosen[0] != other[0]:
            changes += 1
            tag = "→title" if routes[i] else "→baseline"
            print(f"  [{q.qtype or '?':10}] {tag:10} {q.query[:65]}")
            print(f"     chosen top-1: {chosen[0]}")
            print(f"     other  top-1: {other[0]}")
    print(f"\n{changes} queries have different top-1 between routed paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
