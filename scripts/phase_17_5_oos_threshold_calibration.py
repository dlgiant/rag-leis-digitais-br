"""Phase 17.5 — calibrate / pin DEFAULT_OOS_THRESHOLD.

Sweeps candidate values of `rag_leis.rag.DEFAULT_OOS_THRESHOLD` and
measures two rates per value:

  * **OOS-refusal recall** — fraction of `eval/legalbench_br_oos.yaml`
    rows (49) whose top-1 cosine drops below the candidate threshold,
    i.e., the fraction the cosine fast-path catches before reaching
    the LLM. Higher = more OOS pre-empted.

  * **In-scope false-refusal rate** — fraction of `eval/queries.yaml`
    rows (102) whose top-1 cosine drops below the candidate threshold.
    Higher = more good queries refused for the wrong reason.

The threshold is INTENTIONALLY a low fast-path filter (see
`rag.py:109-114`): the load-bearing OOS detection happens at the LLM
self-refusal stage, NOT here. The cosine gate exists to catch the
clearly-different cases (paragraphs in another language, OCR garbage,
prompt injection attempts that don't reach domain vocabulary). So the
calibration goal is: pick the HIGHEST threshold that still keeps
false_refusal_rate ≈ 0, not the threshold that maximizes OOS recall.

Output format mirrors the Phase 8.4 + 7.5 sweep layouts so the
companion `study/phase-17.5-oos-threshold-calibration.md` doc can
embed the table verbatim.

Run:
    uv run python -m scripts.phase_17_5_oos_threshold_calibration

Cost: ~$0.0009 (49 + 102 query embeddings via voyage-3-large). No
LLM calls. Reproducible — deterministic given the same chunks +
queries + Voyage model version.
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from dotenv import load_dotenv

from rag_leis.cache import cache_is_fresh, texts_hash
from rag_leis.embeddings import get_embedder
from rag_leis.eval_harness import format_texts, load_chunks

# Phase 17.5 — load .env so VOYAGE_API_KEY is available for the
# query-embedding step. Idempotent if already loaded by a caller.
# Phase 17.3 may centralize this; for now, the script does it
# defensively at module-import time (same posture as run_eval).
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"
OOS_EVAL = PROJECT_ROOT / "eval" / "legalbench_br_oos.yaml"
INSCOPE_EVAL = PROJECT_ROOT / "eval" / "queries.yaml"

DEFAULT_EMBEDDER = "voyage-3-large"
DEFAULT_TEXT_MODE = "title+label+nav+caput+text"

# Candidate thresholds — wider than the production 0.40 ± a few points
# so the curve shape (not just the chosen point) is visible.
CANDIDATE_THRESHOLDS = [round(0.20 + 0.025 * i, 3) for i in range(17)]  # 0.200..0.600


@dataclass(frozen=True)
class QueryScore:
    source_id: str
    query: str
    top_1_cosine: float


def _load_doc_vectors() -> tuple[np.ndarray, list[str]]:
    """Returns (doc_vectors, ordered_urns). Hard-fails if the cache is
    stale — the calibration is only meaningful against a current index."""
    chunks = load_chunks(CHUNKS_DIR)
    npz_path = INDEX_DIR / f"{DEFAULT_EMBEDDER}__{DEFAULT_TEXT_MODE}.npz"
    current_hash = texts_hash(format_texts(chunks, DEFAULT_TEXT_MODE))
    if not cache_is_fresh(npz_path, current_hash):
        raise RuntimeError(
            f"Voyage index stale at {npz_path}. Rebuild with: "
            f"`uv run python -m rag_leis.run_eval --model "
            f"{DEFAULT_EMBEDDER} --text-mode {DEFAULT_TEXT_MODE}`."
        )
    # The .npz archive stores `urns` as an object array; allow_pickle
    # is required to read it. `vecs` is the float32 doc-embedding matrix.
    npz = np.load(npz_path, allow_pickle=True)
    vecs = npz["vecs"]
    urns = list(npz["urns"])
    assert vecs.shape[0] == len(urns), (
        f"index/chunks mismatch: {vecs.shape[0]} vecs vs {len(urns)} urns"
    )
    return vecs, urns


def _score_queries(
    queries: list[tuple[str, str]],
    doc_vecs: np.ndarray,
) -> list[QueryScore]:
    """Embeds queries via voyage-3-large + computes top-1 cosine for each.

    `queries` is a list of (source_id, query_text) tuples. Vectors are
    L2-normalized at index time so dot product = cosine similarity.
    """
    embedder = get_embedder(DEFAULT_EMBEDDER)
    # The Embedder interface emits one query at a time (Voyage's
    # input-type=query path has different prep than docs). We loop here;
    # 49 + 102 = 151 calls totals <30s for the network round-trips.
    query_vecs = np.stack([embedder.embed_query(q) for _, q in queries])
    # query_vecs shape: (n_queries, dim); doc_vecs: (n_docs, dim).
    sims = query_vecs @ doc_vecs.T  # (n_queries, n_docs)
    top_1 = sims.max(axis=1)  # (n_queries,)
    return [
        QueryScore(source_id=sid, query=q, top_1_cosine=float(s))
        for (sid, q), s in zip(queries, top_1.tolist(), strict=True)
    ]


def _load_oos_queries() -> list[tuple[str, str]]:
    rows = yaml.safe_load(OOS_EVAL.read_text(encoding="utf-8"))
    return [(r["source_id"], r["query"]) for r in rows]


def _load_inscope_queries() -> list[tuple[str, str]]:
    """eval/queries.yaml is the canonical in-scope set (102 rows).
    Each row's `query` field is the natural-language query."""
    rows = yaml.safe_load(INSCOPE_EVAL.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for r in rows:
        # Different rows in queries.yaml use different shapes (some
        # have an `id`, some inline `query` only). Be defensive.
        sid = r.get("id") or r.get("source_id") or r.get("query", "")[:40]
        q = r.get("query") or r.get("text") or ""
        if q:
            out.append((sid, q))
    return out


def _sweep(
    oos_scores: list[QueryScore],
    inscope_scores: list[QueryScore],
    thresholds: list[float],
) -> list[dict]:
    rows: list[dict] = []
    n_oos = len(oos_scores)
    n_in = len(inscope_scores)
    for t in thresholds:
        oos_caught = sum(1 for s in oos_scores if s.top_1_cosine < t)
        in_false = sum(1 for s in inscope_scores if s.top_1_cosine < t)
        rows.append({
            "threshold": t,
            "oos_refusal_recall": oos_caught / n_oos if n_oos else 0.0,
            "false_refusal_rate": in_false / n_in if n_in else 0.0,
            "oos_caught_n": oos_caught,
            "false_refusal_n": in_false,
        })
    return rows


def _summarize_distribution(scores: list[QueryScore], label: str) -> dict:
    vals = [s.top_1_cosine for s in scores]
    if not vals:
        return {"label": label, "n": 0}
    return {
        "label": label,
        "n": len(vals),
        "min": min(vals),
        "max": max(vals),
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "p10": np.percentile(vals, 10),
        "p25": np.percentile(vals, 25),
        "p75": np.percentile(vals, 75),
        "p90": np.percentile(vals, 90),
    }


def _print_distribution(dist: dict) -> None:
    print(f"\n{dist['label']} (n={dist['n']})")
    print(
        f"  min={dist['min']:.4f}  p10={dist['p10']:.4f}  p25={dist['p25']:.4f}  "
        f"median={dist['median']:.4f}  mean={dist['mean']:.4f}  "
        f"p75={dist['p75']:.4f}  p90={dist['p90']:.4f}  max={dist['max']:.4f}"
    )


def _print_sweep(rows: list[dict]) -> None:
    print(f"\n{'threshold':>10} | {'oos_refusal_recall':>18} | {'false_refusal_rate':>18} | {'caught':>7} | {'false_refusals':>14}")
    print("-" * 79)
    for r in rows:
        print(
            f"{r['threshold']:>10.3f} | {r['oos_refusal_recall']:>18.4f} | "
            f"{r['false_refusal_rate']:>18.4f} | {r['oos_caught_n']:>7} | "
            f"{r['false_refusal_n']:>14}"
        )


def _recommend(rows: list[dict], max_false_refusal: float = 0.02) -> dict | None:
    """Pick the HIGHEST threshold where false_refusal_rate ≤ cap.

    See module docstring for the design choice: this calibration is
    about safely raising the fast-path floor without false-refusing
    good queries — NOT about maximizing OOS recall (the LLM owns that).
    """
    eligible = [r for r in rows if r["false_refusal_rate"] <= max_false_refusal]
    if not eligible:
        return None
    return max(eligible, key=lambda r: r["threshold"])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out-json",
        type=Path,
        default=PROJECT_ROOT / "eval" / "runs" / "phase-17.5-oos-threshold-sweep.json",
        help="Where to write the sweep + distributions for the study doc.",
    )
    p.add_argument(
        "--false-refusal-cap",
        type=float,
        default=0.02,
        help="Max acceptable false-refusal rate for the recommended threshold.",
    )
    args = p.parse_args()

    print(f"Loading doc vectors from {INDEX_DIR}...")
    doc_vecs, urns = _load_doc_vectors()
    print(f"  {doc_vecs.shape[0]} doc vectors loaded.")

    print(f"\nLoading OOS queries from {OOS_EVAL}...")
    oos_queries = _load_oos_queries()
    print(f"  {len(oos_queries)} OOS rows.")
    print(f"Loading in-scope queries from {INSCOPE_EVAL}...")
    inscope_queries = _load_inscope_queries()
    print(f"  {len(inscope_queries)} in-scope rows.")

    print("\nEmbedding + scoring (voyage-3-large)...")
    oos_scores = _score_queries(oos_queries, doc_vecs)
    inscope_scores = _score_queries(inscope_queries, doc_vecs)

    oos_dist = _summarize_distribution(oos_scores, "OOS top-1 cosine")
    in_dist = _summarize_distribution(inscope_scores, "In-scope top-1 cosine")
    _print_distribution(oos_dist)
    _print_distribution(in_dist)

    print("\nThreshold sweep:")
    rows = _sweep(oos_scores, inscope_scores, CANDIDATE_THRESHOLDS)
    _print_sweep(rows)

    rec = _recommend(rows, max_false_refusal=args.false_refusal_cap)
    print()
    if rec is None:
        print(
            f"NO threshold in {CANDIDATE_THRESHOLDS[0]:.3f}-"
            f"{CANDIDATE_THRESHOLDS[-1]:.3f} keeps false_refusal_rate ≤ "
            f"{args.false_refusal_cap}."
        )
    else:
        print(
            f"Recommended threshold: {rec['threshold']:.3f}  "
            f"(oos_refusal_recall={rec['oos_refusal_recall']:.4f}, "
            f"false_refusal_rate={rec['false_refusal_rate']:.4f})"
        )

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps({
            "config": {
                "embedder": DEFAULT_EMBEDDER,
                "text_mode": DEFAULT_TEXT_MODE,
                "n_docs": doc_vecs.shape[0],
                "n_oos": len(oos_scores),
                "n_inscope": len(inscope_scores),
                "false_refusal_cap": args.false_refusal_cap,
            },
            "oos_distribution": oos_dist,
            "inscope_distribution": in_dist,
            "sweep": rows,
            "recommended": rec,
            "oos_scores": [
                {"source_id": s.source_id, "top_1": s.top_1_cosine}
                for s in oos_scores
            ],
            "inscope_scores": [
                {"source_id": s.source_id, "top_1": s.top_1_cosine}
                for s in inscope_scores
            ],
        }, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
