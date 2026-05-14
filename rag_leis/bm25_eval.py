"""BM25 sanity check: how does classic BM25 lexical retrieval compare to BGE-M3
sparse (which underperformed in hybrid RRF experiments)? Also tests dense+BM25
hybrid via weighted RRF, to see if a stronger sparse signal recovers the win.

Usage:
    python -m rag_leis.bm25_eval --text-mode nav+caput+text --dense-model voyage-3-large
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

from rag_leis.embeddings import get_embedder  # noqa: E402
from rag_leis.eval_harness import (  # noqa: E402
    format_texts,
    load_chunks,
    load_queries,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)
from rag_leis.run_eval import _load_dotenv  # noqa: E402

CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks" / "tier-1"
INDEX_DIR = PROJECT_ROOT / "data" / "index"

# Very simple Portuguese tokenizer: lowercase, strip punctuation, split on whitespace.
# Keeps digits (for citations like "art. 7") and roman numerals.
_TOKEN_RE = re.compile(r"[a-z0-9áàâãéêíïóôõöúüç-]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _rrf_fuse(
    rankings: list[list[int]], rrf_k: int, top_k: int, weights: list[float]
) -> list[int]:
    acc: dict[int, float] = defaultdict(float)
    for ranking, w in zip(rankings, weights, strict=True):
        for rank, idx in enumerate(ranking, start=1):
            acc[idx] += w / (rrf_k + rank)
    return sorted(acc, key=lambda i: -acc[i])[:top_k]


def main() -> int:
    from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--text-mode",
        choices=["text", "nav+text", "caput+text", "nav+caput+text", "label+nav+caput+text"],
        default="nav+caput+text",
    )
    p.add_argument("--dense-model", default="voyage-3-large")
    p.add_argument("--k", type=int, default=50)
    p.add_argument("--rrf-k", type=int, default=60)
    p.add_argument("--dense-weight", type=float, default=1.0)
    p.add_argument("--eval", default="eval/queries.yaml")
    args = p.parse_args()

    _load_dotenv(PROJECT_ROOT / ".env")

    chunks = load_chunks(CHUNKS_DIR)
    texts = format_texts(chunks, args.text_mode)
    urns = [c.urn for c in chunks]
    print(f"Loaded {len(chunks)} chunks")

    # Dense from cache (built by run_eval).
    safe_dense = args.dense_model.replace("/", "_")
    dense_cache = INDEX_DIR / f"{safe_dense}__{args.text_mode}.npz"
    if not dense_cache.exists():
        print(
            f"Dense cache {dense_cache.name} missing. Run "
            f"`python -m rag_leis.run_eval --model {args.dense_model} --text-mode {args.text_mode}` first."
        )
        return 1
    loaded = np.load(dense_cache, allow_pickle=True)
    doc_dense = loaded["vecs"].astype(np.float32)

    # BM25 index — tokenize, build, score.
    print("Building BM25 index...")
    tokenized = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized)

    embedder = get_embedder(args.dense_model)
    queries = load_queries(PROJECT_ROOT / args.eval)
    print(f"Loaded {len(queries)} queries\n")

    metrics: dict[str, dict[str, list[float]]] = {
        "dense": {"ndcg": [], "recall": [], "mrr": []},
        "bm25": {"ndcg": [], "recall": [], "mrr": []},
        "rrf": {"ndcg": [], "recall": [], "mrr": []},
    }
    per_query: list[dict[str, list[str]]] = []

    for q in queries:
        qv = embedder.embed_query(q.query)
        sims = doc_dense @ qv
        dense_idx = list(np.argsort(-sims)[: args.k])

        q_tokens = _tokenize(q.query)
        bm25_scores = bm25.get_scores(q_tokens)
        bm25_idx = list(np.argsort(-bm25_scores)[: args.k])

        rrf_idx = _rrf_fuse(
            [dense_idx, bm25_idx],
            rrf_k=args.rrf_k,
            top_k=args.k,
            weights=[args.dense_weight, 1.0],
        )

        dense_urns = [urns[i] for i in dense_idx]
        bm25_urns = [urns[i] for i in bm25_idx]
        rrf_urns = [urns[i] for i in rrf_idx]
        per_query.append({"dense": dense_urns, "bm25": bm25_urns, "rrf": rrf_urns})

        for name, ranked in [("dense", dense_urns), ("bm25", bm25_urns), ("rrf", rrf_urns)]:
            metrics[name]["ndcg"].append(ndcg_at_k(ranked, q, 10))
            metrics[name]["recall"].append(recall_at_k(ranked, q.relevant, 20))
            metrics[name]["mrr"].append(mrr_at_k(ranked, q.relevant, 10))

    label = f"{args.dense_model}+bm25"
    weight_tag = (
        f", dense-weight={args.dense_weight:g}" if args.dense_weight != 1.0 else ""
    )
    print("=" * 72)
    print(
        f"Aggregate ({label} / {args.text_mode}, {len(queries)} queries, k={args.k}, "
        f"rrf-k={args.rrf_k}{weight_tag})"
    )
    print("=" * 72)
    print(f"{'pipeline':<10} {'nDCG@10':>8} {'Recall@20':>10} {'MRR@10':>8}")
    for name in ("dense", "bm25", "rrf"):
        m = metrics[name]
        print(
            f"{name:<10} {_mean(m['ndcg']):>8.4f} {_mean(m['recall']):>10.4f} {_mean(m['mrr']):>8.4f}"
        )

    # Per-query Δ for RRF vs dense.
    print("\n" + "=" * 72)
    print("Per-query Δ for RRF vs dense (sorted by ΔnDCG asc)")
    print("=" * 72)
    rows = [
        (
            metrics["rrf"]["ndcg"][i] - metrics["dense"]["ndcg"][i],
            metrics["rrf"]["mrr"][i] - metrics["dense"]["mrr"][i],
            i,
        )
        for i in range(len(queries))
    ]
    rows.sort()
    for d_ndcg, d_mrr, i in rows:
        q = queries[i]
        flag = " ⚠ HURT" if d_ndcg < -0.05 else (" ✓ helped" if d_ndcg > 0.05 else "")
        print(f"\n[{i + 1:>2}] ΔnDCG={d_ndcg:+.3f}  ΔMRR={d_mrr:+.3f}{flag}")
        print(f"     query: {q.query}")
        print(f"     dense top-3: {per_query[i]['dense'][:3]}")
        print(f"     bm25 top-3 : {per_query[i]['bm25'][:3]}")
        print(f"     RRF top-3  : {per_query[i]['rrf'][:3]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
