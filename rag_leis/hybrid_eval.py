"""Hybrid retrieval eval for BGE-M3: dense, sparse (lexical), and RRF fusion.

BGE-M3 emits a dense vector and a sparse lexical-weight dict in a single forward
pass. This script:
  1. Builds both indexes (cached to disk).
  2. For each query, retrieves dense top-K and sparse top-K.
  3. Fuses via Reciprocal Rank Fusion (RRF).
  4. Reports nDCG@10 / Recall@20 / MRR@10 for all three pipelines side-by-side.

Usage:
    python -m rag_leis.hybrid_eval --text-mode nav+caput+text --k 50

Sparse retrieval is brute-force (5937 docs is tiny). RRF uses the standard k=60
constant from Cormack et al. 2009.
"""

from __future__ import annotations

import argparse
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag_leis.embeddings import BGEM3Embedder, get_embedder  # noqa: E402
from rag_leis.eval_harness import (  # noqa: E402
    format_texts,
    load_chunks,
    load_queries,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)
from rag_leis.run_eval import _load_dotenv  # noqa: E402

CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _dense_search(qv: np.ndarray, doc_vecs: np.ndarray, k: int) -> list[int]:
    # Vectors are L2-normalized.
    sims = doc_vecs @ qv
    return list(np.argsort(-sims)[:k])


def _sparse_search(
    q_sparse: dict[str, float], docs_sparse: list[dict[str, float]], k: int
) -> tuple[list[int], list[float]]:
    """Brute-force lexical scoring. Returns (top-k indices, scores)."""
    n = len(docs_sparse)
    scores = np.zeros(n, dtype=np.float32)
    # Iterate over query tokens (small set) and accumulate into docs that contain them.
    # Build a token→doc-list index only if it pays off; with N=6k brute force is fine.
    for i, d in enumerate(docs_sparse):
        if not q_sparse or not d:
            continue
        # Inline lexical_score for speed.
        if len(q_sparse) > len(d):
            small, large = d, q_sparse
        else:
            small, large = q_sparse, d
        s = 0.0
        for tok, w in small.items():
            s += w * large.get(tok, 0.0)
        scores[i] = s
    order = np.argsort(-scores)[:k]
    return list(order), scores[order].tolist()


def _rrf_fuse(
    rankings: list[list[int]],
    rrf_k: int = 60,
    top_k: int = 50,
    weights: list[float] | None = None,
) -> list[int]:
    """Reciprocal Rank Fusion. Weighted variant: each retriever contributes
    `weight / (rrf_k + rank)`. weights=[1, 1, ...] reduces to standard RRF.
    """
    if weights is None:
        weights = [1.0] * len(rankings)
    acc: dict[int, float] = defaultdict(float)
    for ranking, w in zip(rankings, weights, strict=True):
        for rank, idx in enumerate(ranking, start=1):
            acc[idx] += w / (rrf_k + rank)
    return sorted(acc, key=lambda i: -acc[i])[:top_k]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--text-mode",
        choices=["text", "nav+text", "caput+text", "nav+caput+text", "label+nav+caput+text"],
        default="nav+caput+text",
    )
    p.add_argument("--k", type=int, default=50, help="candidate depth for each retriever")
    p.add_argument("--eval", default="eval/queries.yaml")
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--rrf-k", type=int, default=60)
    p.add_argument(
        "--dense-weight",
        type=float,
        default=1.0,
        help="RRF weight for dense (sparse weight is fixed at 1.0). dense-weight=3 → 3:1 favoring dense.",
    )
    p.add_argument(
        "--dense-model",
        default="bge-m3",
        help="Dense embedder; sparse always uses BGE-M3. Cross-model with voyage-3-large is supported.",
    )
    args = p.parse_args()

    _load_dotenv(PROJECT_ROOT / ".env")

    chunks = load_chunks(CHUNKS_DIR)
    print(f"Loaded {len(chunks)} chunks")
    texts = format_texts(chunks, args.text_mode)
    urns = [c.urn for c in chunks]

    safe_dense_name = args.dense_model.replace("/", "_")
    dense_cache = INDEX_DIR / f"{safe_dense_name}__{args.text_mode}.npz"
    # Sparse is always BGE-M3 (it's the model that emits both representations).
    sparse_cache = INDEX_DIR / f"bge-m3__{args.text_mode}.sparse.pkl"

    from rag_leis.cache import cache_is_fresh, texts_hash, write_meta

    current_hash = texts_hash(texts)
    sparse_meta_path = sparse_cache.with_suffix(".meta.json")

    # Resolve dense and sparse caches independently — cross-model uses voyage
    # dense + BGE-M3 sparse, and each may already be cached separately.
    def _try_load_dense() -> tuple[np.ndarray, list[str]] | None:
        if args.rebuild:
            return None
        if not cache_is_fresh(dense_cache, current_hash):
            if dense_cache.exists():
                print(f"Dense cache stale ({dense_cache.name}) — rebuilding.")
            return None
        loaded = np.load(dense_cache, allow_pickle=True)
        return loaded["vecs"].astype(np.float32), list(loaded["urns"])

    def _try_load_sparse() -> list[dict[str, float]] | None:
        if args.rebuild or not sparse_cache.exists():
            return None
        # Sparse uses a sidecar .meta.json next to the .pkl file (same scheme as .npz).
        from rag_leis.cache import read_meta

        meta = read_meta(sparse_meta_path)
        if meta is None or meta.get("content_hash") != current_hash:
            print(f"Sparse cache stale ({sparse_cache.name}) — rebuilding.")
            return None
        with sparse_cache.open("rb") as f:
            return pickle.load(f)  # type: ignore[no-any-return]

    dense_loaded = _try_load_dense()
    sparse_loaded = _try_load_sparse()

    sparse_embedder = BGEM3Embedder() if sparse_loaded is None else None
    dense_embedder = None
    if dense_loaded is None:
        if args.dense_model == "bge-m3":
            dense_embedder = sparse_embedder or BGEM3Embedder()
            sparse_embedder = dense_embedder  # share one model for both
        else:
            dense_embedder = get_embedder(args.dense_model)

    if dense_loaded is not None:
        doc_dense, _ = dense_loaded
        print(f"Loaded cached dense: {dense_cache.name}")
    else:
        print(f"Embedding {len(chunks)} chunks with {args.dense_model} (mode={args.text_mode})...")
        assert dense_embedder is not None
        doc_dense = dense_embedder.embed_docs(texts)
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(dense_cache, urns=np.array(urns, dtype=object), vecs=doc_dense)
        write_meta(
            dense_cache,
            content_hash=current_hash,
            n_chunks=len(urns),
            model=args.dense_model,
            text_mode=args.text_mode,
        )
        print(f"Cached dense → {dense_cache.name}")

    if sparse_loaded is not None:
        doc_sparse = sparse_loaded
        print(f"Loaded cached sparse: {sparse_cache.name}")
    else:
        assert sparse_embedder is not None
        print(f"Embedding {len(chunks)} chunks with bge-m3 sparse (mode={args.text_mode})...")
        _, doc_sparse = sparse_embedder.embed_docs_dense_sparse(texts)
        with sparse_cache.open("wb") as f:
            pickle.dump(doc_sparse, f)
        # Sparse pickle uses the same sidecar scheme as .npz caches.
        sparse_meta_path.write_text(
            __import__("json").dumps(
                {
                    "content_hash": current_hash,
                    "n_chunks": len(urns),
                    "model": "bge-m3-sparse",
                    "text_mode": args.text_mode,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Cached sparse → {sparse_cache.name}")

    # Ensure embedders exist for query-time encoding.
    if sparse_embedder is None:
        sparse_embedder = BGEM3Embedder()
    if dense_embedder is None:
        dense_embedder = (
            sparse_embedder if args.dense_model == "bge-m3" else get_embedder(args.dense_model)
        )

    queries = load_queries(PROJECT_ROOT / args.eval)
    print(f"Loaded {len(queries)} queries\n")

    metrics: dict[str, dict[str, list[float]]] = {
        "dense": {"ndcg": [], "recall": [], "mrr": []},
        "sparse": {"ndcg": [], "recall": [], "mrr": []},
        "rrf": {"ndcg": [], "recall": [], "mrr": []},
    }

    # Per-query: for each pipeline, store the top-K urn list (for later inspection).
    per_query: list[dict[str, list[str]]] = []

    for q in queries:
        if dense_embedder is sparse_embedder:
            qd, qs = sparse_embedder.embed_query_dense_sparse(q.query)
        else:
            qd = dense_embedder.embed_query(q.query)
            _, qs = sparse_embedder.embed_query_dense_sparse(q.query)

        dense_idx = _dense_search(qd, doc_dense, args.k)
        sparse_idx, _ = _sparse_search(qs, doc_sparse, args.k)
        rrf_idx = _rrf_fuse(
            [dense_idx, sparse_idx],
            rrf_k=args.rrf_k,
            top_k=args.k,
            weights=[args.dense_weight, 1.0],
        )

        dense_urns = [urns[i] for i in dense_idx]
        sparse_urns = [urns[i] for i in sparse_idx]
        rrf_urns = [urns[i] for i in rrf_idx]

        per_query.append({"dense": dense_urns, "sparse": sparse_urns, "rrf": rrf_urns})

        for name, ranked in [("dense", dense_urns), ("sparse", sparse_urns), ("rrf", rrf_urns)]:
            metrics[name]["ndcg"].append(ndcg_at_k(ranked, q, 10))
            metrics[name]["recall"].append(recall_at_k(ranked, q.relevant, 20))
            metrics[name]["mrr"].append(mrr_at_k(ranked, q.relevant, 10))

    print("=" * 72)
    label = (
        f"{args.dense_model}+bge-m3-sparse"
        if args.dense_model != "bge-m3"
        else "bge-m3 (dense+sparse)"
    )
    print(f"Aggregate ({label} / {args.text_mode}, {len(queries)} queries, k={args.k}, rrf-k={args.rrf_k})")
    print("=" * 72)
    print(f"{'pipeline':<10} {'nDCG@10':>8} {'Recall@20':>10} {'MRR@10':>8}")
    for name in ("dense", "sparse", "rrf"):
        m = metrics[name]
        print(
            f"{name:<10} {_mean(m['ndcg']):>8.4f} {_mean(m['recall']):>10.4f} {_mean(m['mrr']):>8.4f}"
        )

    # Per-query: where does RRF help/hurt vs dense?
    print("\n" + "=" * 72)
    print("Per-query Δ for RRF vs dense (sorted by ΔnDCG asc)")
    print("=" * 72)
    rows: list[tuple[float, float, int]] = []
    for i, q in enumerate(queries):
        d_ndcg = metrics["dense"]["ndcg"][i]
        r_ndcg = metrics["rrf"]["ndcg"][i]
        d_mrr = metrics["dense"]["mrr"][i]
        r_mrr = metrics["rrf"]["mrr"][i]
        rows.append((r_ndcg - d_ndcg, r_mrr - d_mrr, i))
    rows.sort()
    for d_ndcg, d_mrr, i in rows:
        q = queries[i]
        flag = ""
        if d_ndcg < -0.05:
            flag = " ⚠ HURT"
        elif d_ndcg > 0.05:
            flag = " ✓ helped"
        print(f"\n[{i + 1:>2}] ΔnDCG={d_ndcg:+.3f}  ΔMRR={d_mrr:+.3f}{flag}")
        print(f"     query: {q.query}")
        print(f"     dense top-3 : {per_query[i]['dense'][:3]}")
        print(f"     sparse top-3: {per_query[i]['sparse'][:3]}")
        print(f"     RRF top-3   : {per_query[i]['rrf'][:3]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
