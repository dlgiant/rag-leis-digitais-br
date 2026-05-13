"""Confidence calibration analysis for dense retrieval.

For each query, extract two confidence signals from the dense retriever:
  1. top-1 similarity score (raw cosine sim, since vectors are L2-normalized)
  2. top1-top2 gap (margin between best and runner-up)

Cross-reference each with whether retrieval was correct (MRR > 0, i.e. a
relevant chunk in top-10). The goal: see whether high-confidence queries are
reliably correct, which would let a gated pipeline skip second-stage when
dense is confident and fall back to colbert/rerank otherwise.

Usage:
    python -m rag_leis.confidence_analysis --model voyage-3-large \\
        --text-mode label+nav+caput+text --k 20
"""

from __future__ import annotations

import argparse
import sys
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
)
from rag_leis.run_eval import _load_dotenv  # noqa: E402

CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks" / "tier-1"
INDEX_DIR = PROJECT_ROOT / "data" / "index"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="voyage-3-large")
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
    p.add_argument("--eval", default="eval/queries.yaml")
    p.add_argument("--k", type=int, default=20)
    args = p.parse_args()

    _load_dotenv(PROJECT_ROOT / ".env")

    safe = args.model.replace("/", "_")
    cache = INDEX_DIR / f"{safe}__{args.text_mode}.npz"
    if not cache.exists():
        print(
            f"Dense cache missing ({cache.name}). Run "
            f"`python -m rag_leis.run_eval --model {args.model} "
            f"--text-mode {args.text_mode}` first."
        )
        return 1
    loaded = np.load(cache, allow_pickle=True)
    doc_vecs = loaded["vecs"].astype(np.float32)
    urns = list(loaded["urns"])
    chunks = load_chunks(CHUNKS_DIR)
    assert len(chunks) == len(urns), (
        f"Cache stale ({len(urns)} vs {len(chunks)}). Rebuild with --rebuild."
    )

    # Build URN→text map only for reporting (not used in scoring).
    text_by_urn = dict(
        zip([c.urn for c in chunks], format_texts(chunks, args.text_mode), strict=True)
    )

    embedder = get_embedder(args.model)
    queries = load_queries(PROJECT_ROOT / args.eval)
    print(f"Loaded {len(queries)} queries\n")

    # Per-query signals.
    rows: list[dict] = []
    for q in queries:
        qv = embedder.embed_query(q.query)
        sims = doc_vecs @ qv  # cosine since normalized
        order = np.argsort(-sims)[: args.k]
        top_urns = [urns[i] for i in order]
        top1_score = float(sims[order[0]])
        top2_score = float(sims[order[1]])
        gap = top1_score - top2_score
        top1_correct = top_urns[0] in q.relevant
        ndcg = ndcg_at_k(top_urns, q, 10)
        mrr = mrr_at_k(top_urns, q.relevant, 10)
        rows.append(
            {
                "query": q.query,
                "qtype": q.qtype or "untagged",
                "top1_score": top1_score,
                "gap": gap,
                "top1_correct": top1_correct,
                "ndcg": ndcg,
                "mrr": mrr,
                "top1_urn": top_urns[0],
            }
        )

    # ─────────────────────────────────────────────────────────────────────
    # Bucket queries by top-1 score (quartiles) and report correctness.
    # ─────────────────────────────────────────────────────────────────────
    def _print_bucket_table(
        title: str, key: str, bucket_edges: list[float]
    ) -> None:
        print(f"\n{title} ({key}):")
        print(f"  {'bucket':<18} {'n':>3}  {'top1_correct':>13}  {'mean nDCG':>10}  {'mean MRR':>10}")
        labels = []
        for i in range(len(bucket_edges) - 1):
            lo, hi = bucket_edges[i], bucket_edges[i + 1]
            labels.append((f"[{lo:.3f}, {hi:.3f})", lo, hi))
        # Last bucket inclusive of upper bound.
        labels[-1] = (f"[{bucket_edges[-2]:.3f}, {bucket_edges[-1]:.3f}]", bucket_edges[-2], bucket_edges[-1])
        for label, lo, hi in labels:
            in_b = [
                r for r in rows
                if (lo <= r[key] < hi) or (hi == bucket_edges[-1] and r[key] == hi)
            ]
            n = len(in_b)
            if n == 0:
                print(f"  {label:<18} {n:>3}  {'-':>13}  {'-':>10}  {'-':>10}")
                continue
            frac_correct = sum(1 for r in in_b if r["top1_correct"]) / n
            mean_ndcg = _mean([r["ndcg"] for r in in_b])
            mean_mrr = _mean([r["mrr"] for r in in_b])
            print(
                f"  {label:<18} {n:>3}  {frac_correct * 100:>11.1f}%  "
                f"{mean_ndcg:>10.4f}  {mean_mrr:>10.4f}"
            )

    # Quartile cuts on observed distribution.
    top1_scores = sorted(r["top1_score"] for r in rows)
    gaps = sorted(r["gap"] for r in rows)
    q25, q50, q75 = (
        top1_scores[len(top1_scores) // 4],
        top1_scores[len(top1_scores) // 2],
        top1_scores[3 * len(top1_scores) // 4],
    )
    g25, g50, g75 = (
        gaps[len(gaps) // 4],
        gaps[len(gaps) // 2],
        gaps[3 * len(gaps) // 4],
    )

    print(
        f"Distribution stats (n={len(rows)}, model={args.model}, mode={args.text_mode}):"
    )
    print(
        f"  top1_score:  min={top1_scores[0]:.4f}  q25={q25:.4f}  "
        f"median={q50:.4f}  q75={q75:.4f}  max={top1_scores[-1]:.4f}"
    )
    print(
        f"  gap:         min={gaps[0]:.4f}  q25={g25:.4f}  median={g50:.4f}  "
        f"q75={g75:.4f}  max={gaps[-1]:.4f}"
    )

    _print_bucket_table(
        "Quartile bins — top-1 similarity score",
        "top1_score",
        [top1_scores[0], q25, q50, q75, top1_scores[-1]],
    )
    _print_bucket_table(
        "Quartile bins — top1-top2 gap",
        "gap",
        [gaps[0], g25, g50, g75, gaps[-1]],
    )

    # ─────────────────────────────────────────────────────────────────────
    # Threshold sweep: what's the precision at each threshold?
    # If we trust top-1 only when score ≥ T, fraction of "trusted" queries
    # and their correctness rate.
    # ─────────────────────────────────────────────────────────────────────
    print("\nThreshold sweep — top-1 SCORE")
    print(f"  {'threshold':>9}  {'trusted_n':>9}  {'correct_pct':>11}  {'untrusted_n':>11}  {'untrusted_correct_pct':>22}")
    for t in [
        top1_scores[0],
        q25,
        q50,
        q75,
        top1_scores[-1] * 0.95,
    ]:
        trusted = [r for r in rows if r["top1_score"] >= t]
        untrusted = [r for r in rows if r["top1_score"] < t]
        tc = (
            sum(1 for r in trusted if r["top1_correct"]) / len(trusted)
            if trusted else 0
        )
        uc = (
            sum(1 for r in untrusted if r["top1_correct"]) / len(untrusted)
            if untrusted else 0
        )
        print(
            f"  {t:>9.4f}  {len(trusted):>9}  {tc * 100:>10.1f}%  "
            f"{len(untrusted):>11}  {uc * 100:>21.1f}%"
        )

    print("\nThreshold sweep — top1-top2 GAP")
    print(f"  {'threshold':>9}  {'trusted_n':>9}  {'correct_pct':>11}  {'untrusted_n':>11}  {'untrusted_correct_pct':>22}")
    for t in [gaps[0], g25, g50, g75, gaps[-1] * 0.95]:
        trusted = [r for r in rows if r["gap"] >= t]
        untrusted = [r for r in rows if r["gap"] < t]
        tc = (
            sum(1 for r in trusted if r["top1_correct"]) / len(trusted)
            if trusted else 0
        )
        uc = (
            sum(1 for r in untrusted if r["top1_correct"]) / len(untrusted)
            if untrusted else 0
        )
        print(
            f"  {t:>9.4f}  {len(trusted):>9}  {tc * 100:>10.1f}%  "
            f"{len(untrusted):>11}  {uc * 100:>21.1f}%"
        )

    # ─────────────────────────────────────────────────────────────────────
    # By-type confidence breakdown.
    # ─────────────────────────────────────────────────────────────────────
    from collections import defaultdict

    type_buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        type_buckets[r["qtype"]].append(r)

    print("\nConfidence by query type:")
    print(
        f"  {'type':<18} {'n':>3}  {'mean_top1':>9}  {'mean_gap':>9}  "
        f"{'top1_correct%':>13}  {'mean_ndcg':>9}"
    )
    for qtype in sorted(type_buckets):
        b = type_buckets[qtype]
        n = len(b)
        mt = _mean([r["top1_score"] for r in b])
        mg = _mean([r["gap"] for r in b])
        cc = sum(1 for r in b if r["top1_correct"]) / n
        mn = _mean([r["ndcg"] for r in b])
        print(
            f"  {qtype:<18} {n:>3}  {mt:>9.4f}  {mg:>9.4f}  "
            f"{cc * 100:>12.1f}%  {mn:>9.4f}"
        )

    # ─────────────────────────────────────────────────────────────────────
    # Suppress unused-warning in case eval is happy.
    # ─────────────────────────────────────────────────────────────────────
    _ = text_by_urn
    return 0


if __name__ == "__main__":
    sys.exit(main())
