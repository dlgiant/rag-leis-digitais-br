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
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"


def _load_dotenv(path: Path) -> None:
    """Load a .env file into os.environ. Kept as a thin wrapper so existing
    imports stay valid; delegates to python-dotenv for proper parsing
    (handles export prefix, multi-line values, escaped quotes, etc.)."""
    if not path.exists():
        return
    from dotenv import load_dotenv

    load_dotenv(path, override=False)


def main() -> int:
    p = argparse.ArgumentParser(description="Run retrieval eval against the Tier 1 chunk index.")
    p.add_argument("--model", required=True, help="bge-m3 | voyage-3-large | ...")
    p.add_argument("--eval", default="eval/queries.yaml", help="Path to eval queries YAML")
    p.add_argument(
        "--text-mode",
        choices=[
            "text",
            "nav+text",
            "caput+text",
            "nav+caput+text",
            "label+nav+caput+text",
            "title+label+nav+caput+text",
        ],
        default="text",
    )
    p.add_argument("--k", type=int, default=20, help="Max retrieval depth")
    p.add_argument("--rebuild", action="store_true", help="Force re-embed even if cache exists")
    p.add_argument("--show-misses", action="store_true", help="Print top retrieval for missed queries")
    p.add_argument(
        "--by-type",
        action="store_true",
        help="Break down metrics by Query.qtype (definicao / enumeracao / citacao-literal / parafrase / cross-doc).",
    )
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

    # Content-hash gate against silent staleness: any change to the embedded
    # surface forms (new chunks, parser fixes, text-mode tweaks) invalidates.
    from rag_leis.cache import cache_is_fresh, texts_hash, write_meta

    current_hash = texts_hash(format_texts(chunks, args.text_mode))

    if cache_is_fresh(cache_path, current_hash) and not args.rebuild:
        print(f"Loading cached index: {cache_path}")
        loaded = np.load(cache_path, allow_pickle=True)
        urns: list[str] = list(loaded["urns"])
        doc_vecs = loaded["vecs"]
    else:
        if cache_path.exists():
            print(f"Cache stale (hash mismatch or missing meta): {cache_path.name} — rebuilding.")
        print(f"Embedding {len(chunks)} chunks with {embedder.name} (mode={args.text_mode})...")
        urns, doc_vecs = build_index(chunks, embedder, mode=args.text_mode)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache_path, urns=np.array(urns, dtype=object), vecs=doc_vecs)
        write_meta(
            cache_path,
            content_hash=current_hash,
            n_chunks=len(urns),
            model=embedder.name,
            text_mode=args.text_mode,
        )
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
        # Pass the Query object so nDCG uses graded relevance when available;
        # falls back to binary when supporting is empty (numerically equivalent
        # to the old formula).
        dense_ndcg.append(ndcg_at_k(retrieved, q, 10))
        dense_recall.append(recall_at_k(retrieved, q.relevant, 20))
        dense_mrr.append(mrr_at_k(retrieved, q.relevant, 10))

        if reranker:
            passages = [urn_to_text[u] for u in retrieved]
            scores = reranker.score(q.query, passages)
            order = sorted(range(len(retrieved)), key=lambda i: -scores[i])
            reranked = [retrieved[i] for i in order]
            rr_ndcg.append(ndcg_at_k(reranked, q, 10))
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

    if args.by_type:
        _print_by_type(queries, dense_ndcg, dense_recall, dense_mrr, "dense")
        if reranker:
            _print_by_type(queries, rr_ndcg, rr_recall, rr_mrr, "reranked")

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


def _print_by_type(
    queries: list,
    ndcg: list[float],
    recall: list[float],
    mrr: list[float],
    label: str,
) -> None:
    # Bucket queries by qtype; "untagged" is the catch-all for v1 queries
    # (back-compat with the binary schema before type labels existed).
    from collections import defaultdict

    buckets: dict[str, list[int]] = defaultdict(list)
    for i, q in enumerate(queries):
        buckets[q.qtype or "untagged"].append(i)

    print()
    print(f"By type ({label}):")
    print(f"  {'type':<18} {'n':>3}  {'nDCG@10':>8}  {'Recall@20':>10}  {'MRR@10':>8}")
    for qtype in sorted(buckets):
        idxs = buckets[qtype]
        n = len(idxs)
        n_ndcg = _mean([ndcg[i] for i in idxs])
        n_recall = _mean([recall[i] for i in idxs])
        n_mrr = _mean([mrr[i] for i in idxs])
        print(f"  {qtype:<18} {n:>3}  {n_ndcg:>8.4f}  {n_recall:>10.4f}  {n_mrr:>8.4f}")


if __name__ == "__main__":
    sys.exit(main())
