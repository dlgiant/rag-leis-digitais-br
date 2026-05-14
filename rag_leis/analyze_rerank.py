"""Per-query reranker analysis: which queries does each reranker help/hurt?

Loads a cached dense index, runs each reranker over the same top-K candidates,
and prints both aggregate metrics and the per-query diff (sorted by Δ-MRR).

Usage:
    python -m rag_leis.analyze_rerank \\
        --model voyage-3-large --text-mode text \\
        --rerankers bge-reranker-v2-m3,jina-reranker-v2-base-multilingual,bge-reranker-v2-gemma \\
        --k 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag_leis.embeddings import get_embedder  # noqa: E402
from rag_leis.eval_harness import (  # noqa: E402
    build_index,
    format_texts,
    load_chunks,
    load_queries,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    search,
)
from rag_leis.rerank import get_reranker  # noqa: E402
from rag_leis.run_eval import _load_dotenv  # noqa: E402

CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", required=True)
    p.add_argument(
        "--text-mode",
        choices=["text", "nav+text", "caput+text", "nav+caput+text"],
        default="text",
    )
    p.add_argument("--eval", default="eval/queries.yaml")
    p.add_argument("--k", type=int, default=20)
    p.add_argument("--rerankers", default="bge-reranker-v2-m3", help="comma-separated")
    p.add_argument("--top-show", type=int, default=3, help="top-N per query in dumps")
    args = p.parse_args()

    _load_dotenv(PROJECT_ROOT / ".env")

    rerankers = [r.strip() for r in args.rerankers.split(",") if r.strip()]

    embedder = get_embedder(args.model)
    chunks = load_chunks(CHUNKS_DIR)
    print(f"Loaded {len(chunks)} chunks")
    urns, doc_vecs = build_index(chunks, embedder, mode=args.text_mode)
    text_by_urn = dict(
        zip([c.urn for c in chunks], format_texts(chunks, args.text_mode), strict=True)
    )

    queries = load_queries(PROJECT_ROOT / args.eval)
    print(f"Loaded {len(queries)} queries\n")

    # Run dense once.
    dense_top: list[list[str]] = []
    for q in queries:
        qv = embedder.embed_query(q.query)
        idx = search(qv, doc_vecs, args.k)
        dense_top.append([urns[i] for i in idx])

    dense_ndcg = [ndcg_at_k(r, q.relevant, 10) for r, q in zip(dense_top, queries, strict=True)]
    dense_mrr = [mrr_at_k(r, q.relevant, 10) for r, q in zip(dense_top, queries, strict=True)]
    dense_recall = [recall_at_k(r, q.relevant, 20) for r, q in zip(dense_top, queries, strict=True)]

    # Run each reranker over the same dense top-K.
    results: dict[str, dict[str, list]] = {}
    for rname in rerankers:
        print(f"--- Reranker: {rname} ---")
        rr = get_reranker(rname)
        rr_top: list[list[str]] = []
        for q, top in zip(queries, dense_top, strict=True):
            passages = [text_by_urn[u] for u in top]
            scores = rr.score(q.query, passages)
            order = sorted(range(len(scores)), key=lambda i: -scores[i])
            rr_top.append([top[i] for i in order])
        results[rname] = {
            "top": rr_top,
            "ndcg": [ndcg_at_k(r, q.relevant, 10) for r, q in zip(rr_top, queries, strict=True)],
            "mrr": [mrr_at_k(r, q.relevant, 10) for r, q in zip(rr_top, queries, strict=True)],
            "recall": [
                recall_at_k(r, q.relevant, 20) for r, q in zip(rr_top, queries, strict=True)
            ],
        }
        # Free GPU memory between rerankers if we have it.
        del rr
        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass

    # Aggregate table.
    print("\n" + "=" * 72)
    print(f"Aggregate ({args.model} / {args.text_mode}, 25 queries, k={args.k})")
    print("=" * 72)
    print(f"{'pipeline':<48} {'nDCG@10':>8} {'Recall@20':>10} {'MRR@10':>8}")
    print(f"{'dense':<48} {_mean(dense_ndcg):>8.4f} {_mean(dense_recall):>10.4f} {_mean(dense_mrr):>8.4f}")
    for rname, r in results.items():
        label = f"dense + {rname}"
        print(f"{label:<48} {_mean(r['ndcg']):>8.4f} {_mean(r['recall']):>10.4f} {_mean(r['mrr']):>8.4f}")

    # Per-query: for each reranker, sort by ΔMRR ascending (worst first).
    for rname, r in results.items():
        print("\n" + "=" * 72)
        print(f"Per-query Δ for {rname} (sorted by ΔMRR asc)")
        print("=" * 72)
        rows: list[tuple[float, float, int]] = []
        for i, _q in enumerate(queries):
            d_mrr = dense_mrr[i]
            r_mrr = r["mrr"][i]
            d_ndcg = dense_ndcg[i]
            r_ndcg = r["ndcg"][i]
            rows.append((r_mrr - d_mrr, r_ndcg - d_ndcg, i))
        rows.sort()
        for d_mrr_delta, d_ndcg_delta, i in rows:
            q = queries[i]
            arrow = ""
            if d_mrr_delta < -0.05:
                arrow = " ⚠ HURT"
            elif d_mrr_delta > 0.05:
                arrow = " ✓ helped"
            print(
                f"\n[{i + 1:>2}] ΔMRR={d_mrr_delta:+.3f}  ΔnDCG={d_ndcg_delta:+.3f}{arrow}"
            )
            print(f"     query: {q.query}")
            print(f"     gold : {sorted(q.relevant)}")
            print(f"     dense top-{args.top_show}:")
            for j, u in enumerate(dense_top[i][: args.top_show]):
                mark = "★" if u in q.relevant else " "
                print(f"       {j + 1}. {mark} {u}")
            print(f"     {rname} top-{args.top_show}:")
            for j, u in enumerate(r["top"][i][: args.top_show]):
                mark = "★" if u in q.relevant else " "
                print(f"       {j + 1}. {mark} {u}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
