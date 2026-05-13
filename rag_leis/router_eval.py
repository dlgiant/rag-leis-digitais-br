"""Gated router pipeline — voyage dense default, ColBERT RRF for low-confidence
citation queries.

Routing rule (the simplest one supported by the v3 calibration data):

    if query matches /art\\.?\\s*\\d+/i  AND  voyage_gap < gap_threshold:
        return RRF(voyage_dense, bge_colbert, dense_weight=3)
    else:
        return voyage_dense

Why this rule:
  - Citation queries are where dense+colbert RRF actually beat voyage alone
    (citacao-literal nDCG 0.356 → 0.384 in colbert experiment).
  - The gap (top1−top2) is a useful confidence signal — gap < ~0.016 correlates
    with low top-1 correctness (~23% vs ~67% above the median).
  - On confident citation queries (gap large), dense is already right; routing
    only adds latency.
  - On non-citation queries, RRF with colbert is a net loss (parafrase
    regresses sharply, definicao loses a couple of points), so we don't route
    them at all.

Usage:
    python -m rag_leis.router_eval --gap-threshold 0.016
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag_leis.embeddings import BGEM3Embedder, get_embedder  # noqa: E402
from rag_leis.eval_harness import (  # noqa: E402
    load_chunks,
    load_queries,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)
from rag_leis.run_eval import _load_dotenv  # noqa: E402

CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks" / "tier-1"
INDEX_DIR = PROJECT_ROOT / "data" / "index"

# Matches "art. 7", "art 7", "art.7", "artigo 7", "art. 154-A", etc.
CITATION_RE = re.compile(r"\bart(?:igo)?\.?\s*\d+(?:-[A-Za-z])?", re.IGNORECASE)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _rrf_fuse(
    rankings: list[list[int]],
    weights: list[float],
    rrf_k: int = 60,
    top_k: int = 50,
) -> list[int]:
    acc: dict[int, float] = defaultdict(float)
    for ranking, w in zip(rankings, weights, strict=True):
        for rank, doc in enumerate(ranking, start=1):
            acc[doc] += w / (rrf_k + rank)
    return sorted(acc, key=lambda i: -acc[i])[:top_k]


def _colbert_search_gpu(
    q_vecs: np.ndarray, flat_gpu: object, offsets: np.ndarray, k: int, torch: object
) -> list[int]:
    qv_gpu = torch.from_numpy(q_vecs).half().cuda()
    sims = (qv_gpu @ flat_gpu.T).float().cpu().numpy()
    max_per_doc = np.maximum.reduceat(sims, offsets[:-1], axis=1)
    scores = max_per_doc.sum(axis=0)
    return list(np.argsort(-scores)[:k])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dense-model", default="voyage-3-large")
    p.add_argument("--text-mode", default="label+nav+caput+text")
    p.add_argument("--k", type=int, default=20)
    p.add_argument("--eval", default="eval/queries.yaml")
    p.add_argument("--gap-threshold", type=float, default=0.016)
    p.add_argument(
        "--gate-mode",
        choices=["citation-and-gap", "citation-only", "gap-only"],
        default="citation-and-gap",
        help="citation-and-gap: route when query matches regex AND gap<threshold (default). "
        "citation-only: route every citation query regardless of confidence. "
        "gap-only: route every low-confidence query regardless of type.",
    )
    p.add_argument("--rrf-dense-weight", type=float, default=3.0)
    args = p.parse_args()

    _load_dotenv(PROJECT_ROOT / ".env")

    safe = args.dense_model.replace("/", "_")
    dense_cache = INDEX_DIR / f"{safe}__{args.text_mode}.npz"
    colbert_cache = INDEX_DIR / f"bge-m3__{args.text_mode}.colbert.npz"
    if not dense_cache.exists():
        print(f"Dense cache missing: {dense_cache.name}")
        return 1
    if not colbert_cache.exists():
        print(f"ColBERT cache missing: {colbert_cache.name}")
        return 1

    chunks = load_chunks(CHUNKS_DIR)
    urns = [c.urn for c in chunks]
    print(f"Loaded {len(chunks)} chunks")

    d_loaded = np.load(dense_cache, allow_pickle=True)
    doc_dense = d_loaded["vecs"].astype(np.float32)
    c_loaded = np.load(colbert_cache, allow_pickle=True)
    flat_vecs = c_loaded["vecs"]
    offsets = c_loaded["offsets"]

    import torch

    flat_gpu = torch.from_numpy(flat_vecs).half().cuda()

    dense_embedder = get_embedder(args.dense_model)
    bge = BGEM3Embedder()  # for colbert queries

    queries = load_queries(PROJECT_ROOT / args.eval)
    print(f"Loaded {len(queries)} queries\n")

    # Run dense for all queries; lazy-run colbert only for routed ones.
    metrics: dict[str, dict[str, list[float]]] = {
        "dense": {"ndcg": [], "recall": [], "mrr": []},
        "router": {"ndcg": [], "recall": [], "mrr": []},
    }
    route_decisions: list[dict] = []

    for q in queries:
        # Dense baseline (always compute).
        qv = dense_embedder.embed_query(q.query)
        sims = doc_dense @ qv
        dense_idx_all = np.argsort(-sims)[:50]  # keep 50 for potential RRF
        dense_idx = list(dense_idx_all[: args.k])
        top1_score = float(sims[dense_idx_all[0]])
        top2_score = float(sims[dense_idx_all[1]])
        gap = top1_score - top2_score
        dense_urns = [urns[i] for i in dense_idx]

        is_citation = bool(CITATION_RE.search(q.query))
        if args.gate_mode == "citation-and-gap":
            should_route = is_citation and gap < args.gap_threshold
        elif args.gate_mode == "citation-only":
            should_route = is_citation
        else:  # gap-only
            should_route = gap < args.gap_threshold

        if should_route:
            # Run colbert for this query and RRF-fuse.
            qv_col = bge.embed_query_colbert(q.query)
            colbert_idx = _colbert_search_gpu(qv_col, flat_gpu, offsets, 50, torch)
            fused = _rrf_fuse(
                [list(dense_idx_all), colbert_idx],
                [args.rrf_dense_weight, 1.0],
                top_k=args.k,
            )
            router_urns = [urns[i] for i in fused]
        else:
            router_urns = dense_urns

        route_decisions.append(
            {
                "query": q.query,
                "qtype": q.qtype or "untagged",
                "is_citation": is_citation,
                "gap": gap,
                "routed": should_route,
            }
        )

        for name, ranked in [("dense", dense_urns), ("router", router_urns)]:
            metrics[name]["ndcg"].append(ndcg_at_k(ranked, q, 10))
            metrics[name]["recall"].append(recall_at_k(ranked, q.relevant, 20))
            metrics[name]["mrr"].append(mrr_at_k(ranked, q.relevant, 10))

    n_routed = sum(1 for d in route_decisions if d["routed"])
    print(
        f"Router decisions: {n_routed}/{len(queries)} queries routed to RRF "
        f"(gate_mode={args.gate_mode}, gap_threshold={args.gap_threshold}, "
        f"rrf_dense_weight={args.rrf_dense_weight})"
    )

    print("\n" + "=" * 72)
    print(
        f"Aggregate ({args.dense_model} / {args.text_mode}, "
        f"{len(queries)} queries, k={args.k})"
    )
    print("=" * 72)
    print(f"{'pipeline':<10} {'nDCG@10':>8} {'Recall@20':>10} {'MRR@10':>8}")
    for name in ("dense", "router"):
        m = metrics[name]
        print(
            f"{name:<10} {_mean(m['ndcg']):>8.4f} "
            f"{_mean(m['recall']):>10.4f} {_mean(m['mrr']):>8.4f}"
        )

    # Per-type breakdown.
    buckets: dict[str, list[int]] = defaultdict(list)
    for i, q in enumerate(queries):
        buckets[q.qtype or "untagged"].append(i)

    print("\nBy type — dense vs router:")
    print(
        f"  {'type':<18} {'n':>3}  "
        f"{'dense nDCG':>10}  {'router nDCG':>11}  "
        f"{'dense MRR':>9}  {'router MRR':>10}  {'routed':>6}"
    )
    for qtype in sorted(buckets):
        idxs = buckets[qtype]
        n = len(idxs)
        d_ndcg = _mean([metrics["dense"]["ndcg"][i] for i in idxs])
        r_ndcg = _mean([metrics["router"]["ndcg"][i] for i in idxs])
        d_mrr = _mean([metrics["dense"]["mrr"][i] for i in idxs])
        r_mrr = _mean([metrics["router"]["mrr"][i] for i in idxs])
        n_routed_type = sum(1 for i in idxs if route_decisions[i]["routed"])
        print(
            f"  {qtype:<18} {n:>3}  "
            f"{d_ndcg:>10.4f}  {r_ndcg:>11.4f}  "
            f"{d_mrr:>9.4f}  {r_mrr:>10.4f}  {n_routed_type:>6}"
        )

    # Per-routed-query: dense vs router rank movement for inspection.
    print("\nRouted queries — per-query Δ:")
    for i, d in enumerate(route_decisions):
        if not d["routed"]:
            continue
        delta_ndcg = metrics["router"]["ndcg"][i] - metrics["dense"]["ndcg"][i]
        delta_mrr = metrics["router"]["mrr"][i] - metrics["dense"]["mrr"][i]
        flag = ""
        if delta_ndcg > 0.05:
            flag = " ✓"
        elif delta_ndcg < -0.05:
            flag = " ⚠"
        print(
            f"  [{i + 1:>3}] {d['qtype']:<16} gap={d['gap']:.4f}  "
            f"ΔnDCG={delta_ndcg:+.3f}  ΔMRR={delta_mrr:+.3f}{flag}  {d['query'][:60]}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
