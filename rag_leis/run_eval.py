from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

from rag_leis.embeddings import get_embedder
from rag_leis.eval_harness import (
    build_index,
    format_texts,
    load_chunks,
    load_queries,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    search,
)
from rag_leis.rerank import get_reranker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks" / "tier-1"
INDEX_DIR = PROJECT_ROOT / "data" / "index"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    p = argparse.ArgumentParser(description="Run retrieval eval against the Tier 1 chunk index.")
    p.add_argument("--model", required=True, help="bge-m3 | voyage-3-large | ...")
    p.add_argument("--eval", default="eval/queries.yaml", help="Path to eval queries YAML")
    p.add_argument(
        "--text-mode",
        choices=["text", "nav+text", "caput+text", "nav+caput+text"],
        default="text",
    )
    p.add_argument("--k", type=int, default=20, help="Max retrieval depth")
    p.add_argument("--rebuild", action="store_true", help="Force re-embed even if cache exists")
    p.add_argument("--show-misses", action="store_true", help="Print top retrieval for missed queries")
    p.add_argument(
        "--rerank",
        default=None,
        help="Optional cross-encoder reranker (e.g. bge-reranker-v2-m3). "
        "Re-scores the top-K dense candidates and reports side-by-side metrics.",
    )
    args = p.parse_args()

    _load_dotenv(PROJECT_ROOT / ".env")

    embedder = get_embedder(args.model)
    chunks = load_chunks(CHUNKS_DIR)
    print(f"Loaded {len(chunks)} chunks (after filtering empty/revoked)")

    safe_name = embedder.name.replace("/", "_")
    cache_path = INDEX_DIR / f"{safe_name}__{args.text_mode}.npz"

    if cache_path.exists() and not args.rebuild:
        print(f"Loading cached index: {cache_path}")
        loaded = np.load(cache_path, allow_pickle=True)
        urns: list[str] = list(loaded["urns"])
        doc_vecs = loaded["vecs"]
    else:
        print(f"Embedding {len(chunks)} chunks with {embedder.name} (mode={args.text_mode})...")
        urns, doc_vecs = build_index(chunks, embedder, mode=args.text_mode)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache_path, urns=np.array(urns, dtype=object), vecs=doc_vecs)
        print(f"Cached index → {cache_path}")

    # Build a urn → passage-text dict (matching the index's text mode) so the
    # reranker scores the same surface form the bi-encoder saw.
    urn_to_text = dict(
        zip([c.urn for c in chunks], format_texts(chunks, args.text_mode), strict=True)
    )

    queries = load_queries(Path(args.eval))
    print(f"Loaded {len(queries)} queries from {args.eval}")

    urn_set = set(urns)
    missing = [r for q in queries for r in q.relevant if r not in urn_set]
    if missing:
        print(f"\nWARN: {len(missing)} relevant URN(s) missing from index:")
        for m in sorted(set(missing))[:10]:
            print(f"  - {m}")
        print()

    reranker = get_reranker(args.rerank) if args.rerank else None
    if reranker:
        print(f"Reranker: {reranker.name} (top-{args.k})")

    dense_ndcg: list[float] = []
    dense_recall: list[float] = []
    dense_mrr: list[float] = []
    rr_ndcg: list[float] = []
    rr_recall: list[float] = []
    rr_mrr: list[float] = []
    misses: list[tuple[str, list[str], frozenset[str]]] = []

    for q in queries:
        q_vec = embedder.embed_query(q.query)
        idx = search(q_vec, doc_vecs, k=args.k)
        retrieved = [urns[i] for i in idx]
        dense_ndcg.append(ndcg_at_k(retrieved, q.relevant, 10))
        dense_recall.append(recall_at_k(retrieved, q.relevant, 20))
        dense_mrr.append(mrr_at_k(retrieved, q.relevant, 10))

        if reranker:
            passages = [urn_to_text[u] for u in retrieved]
            scores = reranker.score(q.query, passages)
            order = sorted(range(len(retrieved)), key=lambda i: -scores[i])
            reranked = [retrieved[i] for i in order]
            rr_ndcg.append(ndcg_at_k(reranked, q.relevant, 10))
            rr_recall.append(recall_at_k(reranked, q.relevant, 20))
            rr_mrr.append(mrr_at_k(reranked, q.relevant, 10))
            top_for_misses = reranked
        else:
            top_for_misses = retrieved

        if (rr_mrr[-1] if reranker else dense_mrr[-1]) == 0.0:
            misses.append((q.query, top_for_misses[:5], q.relevant))

    print()
    print(f"model={embedder.name}  text_mode={args.text_mode}  queries={len(queries)}  k={args.k}")
    if reranker:
        print("                dense     reranked     Δ")
        _print_row("nDCG@10  ", dense_ndcg, rr_ndcg)
        _print_row("Recall@20", dense_recall, rr_recall)
        _print_row("MRR@10   ", dense_mrr, rr_mrr)
    else:
        print(f"  nDCG@10  : {_mean(dense_ndcg):.4f}")
        print(f"  Recall@20: {_mean(dense_recall):.4f}")
        print(f"  MRR@10   : {_mean(dense_mrr):.4f}")

    if args.show_misses and misses:
        print()
        print(f"Misses ({len(misses)}):")
        for query, top5, relevant in misses:
            print(f"  Q: {query}")
            print(f"    relevant : {sorted(relevant)}")
            print(f"    top5     : {top5}")

    return 0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _print_row(label: str, dense: list[float], reranked: list[float]) -> None:
    d, r = _mean(dense), _mean(reranked)
    delta = r - d
    sign = "+" if delta >= 0 else ""
    print(f"  {label}    {d:.4f}      {r:.4f}    {sign}{delta:.4f}")


if __name__ == "__main__":
    sys.exit(main())
