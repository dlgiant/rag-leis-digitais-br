"""ColBERT (late interaction) eval over BGE-M3 multi-vector output.

For each query, ColBERT scoring is:

    score(q, d) = Σ_{i in query tokens} max_{j in doc tokens} (q_i · d_j)

(MaxSim — Khattab & Zaharia, 2020.) Token vectors are L2-normalized, so the
inner product is cosine similarity.

The index is stored flat:
  - flat_vecs:  (sum_T, D) float16 array — all doc token vectors concatenated
  - offsets:    (N+1,) int32 — slice boundaries: doc i occupies flat_vecs[offsets[i]:offsets[i+1]]
  - urns:       (N,) object — chunk URNs in order

This lets us do one big query-vs-all matmul on GPU/CPU and slice per doc.

Usage:
    python -m rag_leis.colbert_eval --text-mode label+nav+caput+text --k 20

Compares ColBERT-alone vs dense-alone (loads cached dense .npz for the same
text-mode if available) and reports per-type metrics.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collections import defaultdict  # noqa: E402

from rag_leis.embeddings import BGEM3Embedder, get_embedder  # noqa: E402
from rag_leis.eval_harness import (  # noqa: E402
    Query,
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


def _build_flat_index(per_doc: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Pack a list of (Ti, D) arrays into (sum_T, D) with offsets[i+1]-offsets[i] = Ti."""
    counts = np.array([v.shape[0] for v in per_doc], dtype=np.int32)
    offsets = np.zeros(len(per_doc) + 1, dtype=np.int32)
    offsets[1:] = np.cumsum(counts)
    dim = per_doc[0].shape[1]
    flat = np.empty((int(offsets[-1]), dim), dtype=np.float16)  # fp16 to halve memory
    for i, v in enumerate(per_doc):
        flat[offsets[i] : offsets[i + 1]] = v.astype(np.float16)
    return flat, offsets


def _colbert_search(
    q_vecs: "np.ndarray | object",  # np or torch.Tensor
    flat_vecs: "np.ndarray | object",
    offsets: np.ndarray,
    k: int,
    *,
    torch_module: object = None,
) -> list[int]:
    """Brute-force MaxSim scoring, fully vectorized.

    With `torch_module` provided, runs the matmul on GPU (~10ms/query). Otherwise
    falls back to numpy on CPU (~10s/query for a 300K-token index — viable only
    for small corpora or one-off debug runs).

    `np.maximum.reduceat(arr, starts, axis=1)` computes the max within each
    consecutive segment defined by `starts`, in one pass. Then sum across
    query tokens (axis=0) to get MaxSim.
    """
    if torch_module is not None:
        torch = torch_module
        # Single matmul on GPU.
        sims_gpu = q_vecs @ flat_vecs.T  # (Tq, sum_T), still fp16
        sims = sims_gpu.float().cpu().numpy()
    else:
        sims = (q_vecs.astype(np.float16) @ flat_vecs.T).astype(np.float32)
    max_per_doc = np.maximum.reduceat(sims, offsets[:-1], axis=1)  # (Tq, N)
    scores = max_per_doc.sum(axis=0)  # (N,)
    return list(np.argsort(-scores)[:k])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--text-mode",
        choices=[
            "text",
            "nav+text",
            "caput+text",
            "nav+caput+text",
            "label+nav+caput+text",
        ],
        default="label+nav+caput+text",
    )
    p.add_argument("--k", type=int, default=20)
    p.add_argument("--eval", default="eval/queries.yaml")
    p.add_argument("--rebuild", action="store_true")
    p.add_argument(
        "--compare-dense",
        action="store_true",
        help="Also report dense-alone metrics (loads cached bge-m3 index for same text-mode).",
    )
    p.add_argument(
        "--rrf-dense-model",
        default=None,
        help="If set, also runs dense via this model (e.g. voyage-3-large) and reports "
        "dense / colbert / RRF(dense+colbert) side-by-side. Reuses the cached dense index.",
    )
    p.add_argument("--rrf-k", type=int, default=60)
    p.add_argument("--rrf-dense-weight", type=float, default=1.0)
    args = p.parse_args()

    _load_dotenv(PROJECT_ROOT / ".env")

    chunks = load_chunks(CHUNKS_DIR)
    texts = format_texts(chunks, args.text_mode)
    urns = [c.urn for c in chunks]
    print(f"Loaded {len(chunks)} chunks")

    cache = INDEX_DIR / f"bge-m3__{args.text_mode}.colbert.npz"
    if cache.exists() and not args.rebuild:
        print(f"Loading cached ColBERT index: {cache.name}")
        loaded = np.load(cache, allow_pickle=True)
        flat_vecs = loaded["vecs"].astype(np.float16)
        offsets = loaded["offsets"]
        cached_urns = list(loaded["urns"])
        if cached_urns != urns:
            print("Cache urn mismatch — rebuilding.")
            cache.unlink()
        else:
            embedder = BGEM3Embedder()

    if not cache.exists() or args.rebuild:
        embedder = BGEM3Embedder()
        print(f"Embedding {len(chunks)} chunks with bge-m3 ColBERT (mode={args.text_mode})...")
        per_doc = embedder.embed_docs_colbert(texts)
        flat_vecs, offsets = _build_flat_index(per_doc)
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            cache,
            vecs=flat_vecs,
            offsets=offsets,
            urns=np.array(urns, dtype=object),
        )
        print(
            f"Cached ColBERT → {cache.name} "
            f"(flat: {flat_vecs.shape}, ~{flat_vecs.nbytes / 1e6:.0f} MB fp16)"
        )

    queries = load_queries(PROJECT_ROOT / args.eval)
    print(f"Loaded {len(queries)} queries\n")

    # Optional dense baseline for side-by-side comparison.
    dense_top: list[list[str]] | None = None
    if args.compare_dense:
        dense_cache = INDEX_DIR / f"bge-m3__{args.text_mode}.npz"
        if dense_cache.exists():
            print(f"Loading dense baseline: {dense_cache.name}")
            d_loaded = np.load(dense_cache, allow_pickle=True)
            doc_dense = d_loaded["vecs"].astype(np.float32)
            dense_top = []
            for q in queries:
                qv = embedder.embed_query(q.query)
                sims = doc_dense @ qv
                dense_top.append([urns[i] for i in np.argsort(-sims)[: args.k]])
        else:
            print(f"Dense cache missing ({dense_cache.name}) — skipping comparison.")

    # Move flat_vecs to GPU once if torch+CUDA available; ~3 orders of magnitude
    # faster than numpy on CPU for the 300K-token matmul.
    torch_module: object = None
    flat_for_search: object = flat_vecs
    try:
        import torch

        if torch.cuda.is_available():
            print("Using GPU for ColBERT MaxSim matmul.")
            flat_for_search = torch.from_numpy(flat_vecs).half().cuda()
            torch_module = torch
    except ImportError:
        pass

    colbert_top: list[list[str]] = []
    colbert_idx_top: list[list[int]] = []
    for q in queries:
        qv = embedder.embed_query_colbert(q.query)
        if torch_module is not None:
            qv_for_search = torch_module.from_numpy(qv).half().cuda()
        else:
            qv_for_search = qv
        idx = _colbert_search(
            qv_for_search, flat_for_search, offsets, args.k, torch_module=torch_module
        )
        colbert_idx_top.append(idx)
        colbert_top.append([urns[i] for i in idx])

    # Optional cross-model RRF: voyage (or other) dense + bge-m3 colbert.
    rrf_top: list[list[str]] | None = None
    rrf_dense_top: list[list[str]] | None = None
    if args.rrf_dense_model:
        safe = args.rrf_dense_model.replace("/", "_")
        rrf_cache = INDEX_DIR / f"{safe}__{args.text_mode}.npz"
        if not rrf_cache.exists():
            print(
                f"RRF dense cache missing ({rrf_cache.name}). Run "
                f"`python -m rag_leis.run_eval --model {args.rrf_dense_model} "
                f"--text-mode {args.text_mode}` first."
            )
            return 1
        print(f"Loading RRF dense ({args.rrf_dense_model}): {rrf_cache.name}")
        r_loaded = np.load(rrf_cache, allow_pickle=True)
        rrf_dense_vecs = r_loaded["vecs"].astype(np.float32)
        rrf_embedder = get_embedder(args.rrf_dense_model)

        rrf_dense_top = []
        rrf_dense_idx_top: list[list[int]] = []
        for q in queries:
            qv2 = rrf_embedder.embed_query(q.query)
            sims2 = rrf_dense_vecs @ qv2
            idx2 = list(np.argsort(-sims2)[: args.k])
            rrf_dense_idx_top.append(idx2)
            rrf_dense_top.append([urns[i] for i in idx2])

        # RRF fuse: voyage_dense rank + colbert rank.
        rrf_top = []
        for d_idx, c_idx in zip(rrf_dense_idx_top, colbert_idx_top, strict=True):
            acc: dict[int, float] = defaultdict(float)
            for rank, doc in enumerate(d_idx, start=1):
                acc[doc] += args.rrf_dense_weight / (args.rrf_k + rank)
            for rank, doc in enumerate(c_idx, start=1):
                acc[doc] += 1.0 / (args.rrf_k + rank)
            fused = sorted(acc, key=lambda i: -acc[i])[: args.k]
            rrf_top.append([urns[i] for i in fused])

    def _metrics(ranked: list[list[str]]) -> dict[str, float]:
        return {
            "ndcg": _mean([ndcg_at_k(r, q, 10) for r, q in zip(ranked, queries, strict=True)]),
            "recall": _mean(
                [recall_at_k(r, q.relevant, 20) for r, q in zip(ranked, queries, strict=True)]
            ),
            "mrr": _mean(
                [mrr_at_k(r, q.relevant, 10) for r, q in zip(ranked, queries, strict=True)]
            ),
        }

    print("=" * 72)
    print(f"Aggregate (bge-m3 / {args.text_mode}, {len(queries)} queries, k={args.k})")
    print("=" * 72)
    print(f"{'pipeline':<10} {'nDCG@10':>8} {'Recall@20':>10} {'MRR@10':>8}")
    if dense_top is not None:
        m = _metrics(dense_top)
        print(f"{'bge-dense':<22} {m['ndcg']:>8.4f} {m['recall']:>10.4f} {m['mrr']:>8.4f}")
    if rrf_dense_top is not None:
        m = _metrics(rrf_dense_top)
        print(
            f"{args.rrf_dense_model + '-dense':<22} {m['ndcg']:>8.4f} {m['recall']:>10.4f} {m['mrr']:>8.4f}"
        )
    m = _metrics(colbert_top)
    print(f"{'bge-colbert':<22} {m['ndcg']:>8.4f} {m['recall']:>10.4f} {m['mrr']:>8.4f}")
    if rrf_top is not None:
        m = _metrics(rrf_top)
        wt = f", dense×{args.rrf_dense_weight:g}" if args.rrf_dense_weight != 1.0 else ""
        print(
            f"{'rrf(' + args.rrf_dense_model + '+colbert' + wt + ')':<22} "
            f"{m['ndcg']:>8.4f} {m['recall']:>10.4f} {m['mrr']:>8.4f}"
        )

    # Per-type breakdown.
    buckets: dict[str, list[int]] = defaultdict(list)
    for i, q in enumerate(queries):
        buckets[q.qtype or "untagged"].append(i)

    def _print_by_type(label: str, ranked: list[list[str]]) -> None:
        print(f"\n{label} — by type:")
        print(f"  {'type':<18} {'n':>3}  {'nDCG@10':>8}  {'Recall@20':>10}  {'MRR@10':>8}")
        for qtype in sorted(buckets):
            idxs = buckets[qtype]
            n = len(idxs)
            sub_ndcg = _mean([ndcg_at_k(ranked[i], queries[i], 10) for i in idxs])
            sub_recall = _mean(
                [recall_at_k(ranked[i], queries[i].relevant, 20) for i in idxs]
            )
            sub_mrr = _mean(
                [mrr_at_k(ranked[i], queries[i].relevant, 10) for i in idxs]
            )
            print(
                f"  {qtype:<18} {n:>3}  {sub_ndcg:>8.4f}  {sub_recall:>10.4f}  {sub_mrr:>8.4f}"
            )

    _print_by_type("ColBERT", colbert_top)
    if dense_top is not None:
        _print_by_type("BGE-M3 Dense", dense_top)
    if rrf_dense_top is not None:
        _print_by_type(f"{args.rrf_dense_model} dense", rrf_dense_top)
    if rrf_top is not None:
        _print_by_type(f"RRF({args.rrf_dense_model}+colbert)", rrf_top)

    # Don't let `embedder` go unused warning when only loading cache.
    _ = embedder  # type: ignore[has-type]
    _ = Query
    return 0


if __name__ == "__main__":
    sys.exit(main())
