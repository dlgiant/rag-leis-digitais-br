from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

from rag_leis.embeddings import get_embedder
from rag_leis.eval_harness import (
    build_index,
    load_chunks,
    load_queries,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    search,
)

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

    queries = load_queries(Path(args.eval))
    print(f"Loaded {len(queries)} queries from {args.eval}")

    urn_set = set(urns)
    missing = [r for q in queries for r in q.relevant if r not in urn_set]
    if missing:
        print(f"\nWARN: {len(missing)} relevant URN(s) missing from index:")
        for m in sorted(set(missing))[:10]:
            print(f"  - {m}")
        print()

    ndcg_scores: list[float] = []
    recall_scores: list[float] = []
    mrr_scores: list[float] = []
    misses: list[tuple[str, list[str], frozenset[str]]] = []

    for q in queries:
        q_vec = embedder.embed_query(q.query)
        idx = search(q_vec, doc_vecs, k=args.k)
        retrieved = [urns[i] for i in idx]
        ndcg = ndcg_at_k(retrieved, q.relevant, 10)
        recall = recall_at_k(retrieved, q.relevant, 20)
        mrr = mrr_at_k(retrieved, q.relevant, 10)
        ndcg_scores.append(ndcg)
        recall_scores.append(recall)
        mrr_scores.append(mrr)
        if mrr == 0.0:
            misses.append((q.query, retrieved[:5], q.relevant))

    print()
    print(f"model={embedder.name}  text_mode={args.text_mode}  queries={len(queries)}  k={args.k}")
    print(f"  nDCG@10  : {_mean(ndcg_scores):.4f}")
    print(f"  Recall@20: {_mean(recall_scores):.4f}")
    print(f"  MRR@10   : {_mean(mrr_scores):.4f}")

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


if __name__ == "__main__":
    sys.exit(main())
