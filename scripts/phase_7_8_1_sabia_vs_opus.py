"""Phase 7.8.1 — A/B the relevance gate's judge model.

Tests the Sabiá-judging-Sabiá self-defense bias concern from Phase 7.8
findings. Runs the same legalbench OOS eval twice:

  Variant A: relevance gate uses Sabiá-3.1 (current default = self.llm)
  Variant B: relevance gate uses Opus-4-7 (set via relevance_judge field)

Compares per-row decisions: which rows refused under Sabiá but not Opus
(and vice versa), and whether the headline oos_a_refusal_rate moves
materially. Pre-locked decision criterion: |Opus rate - Sabiá rate| > 0.10pp
→ evidence of Sabiá bias, swap default to Opus. Smaller delta → keep Sabiá.

Uso:
    set -a && source .env && set +a && uv run python -m scripts.phase_7_8_1_sabia_vs_opus
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml
from dotenv import load_dotenv

from rag_leis.llm import DEFAULT_JUDGE_MODEL, get_llm
from rag_leis.rag import DEFAULT_TOP_K, RAGAnswer, load_pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"
EVAL_PATH = PROJECT_ROOT / "eval" / "legalbench_br_oos.yaml"
# Phase 7.8.2 — separate output path so the original 7.8.1 record stays
# intact for historical reference. The 7.8.2 re-run captures
# classified_type per row (the field 7.8.2 Option C needs).
OUT_PATH = PROJECT_ROOT / "eval" / "runs" / "phase-7.8.2-legalbench-with-type.json"
# Phase 7.9 — enable LLM cache by default for this script. Re-runs and
# future cached-data sweeps benefit; first run pays the API bill once.
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "llm"


def _run_against_eval(pipe, queries, label: str) -> list[dict]:
    """Run the pipeline against the eval queries; return per-row records."""
    rows = []
    for i, q in enumerate(queries, 1):
        query = q["query"]
        print(f"  [{label}] [{i:>2}/{len(queries)}] {q['source_id']}", flush=True)
        try:
            ans: RAGAnswer = pipe.answer(query)
            rows.append({
                "source_id": q["source_id"],
                "refused": ans.refused,
                "refusal_reason": ans.refusal_reason,
                "citations": ans.citations,
                "rejected_irrelevant": ans.rejected_irrelevant_citations,
                # Phase 7.8.2 prep — classified_type is the query-router's
                # output, needed to project the adaptive-by-type relevance
                # gate (Option C in phase-7.8.2-partial-relevance-gate-
                # findings.md) on this surface from cached data.
                "classified_type": ans.classified_type,
                "cost_usd": ans.cost_estimate_usd,
                "latency_ms": ans.latency_ms,
                "llm_calls": ans.llm_calls,
            })
        except Exception as e:
            rows.append({
                "source_id": q["source_id"],
                "refused": True,
                "refusal_reason": f"ERROR: {type(e).__name__}: {e}",
                "citations": [],
                "rejected_irrelevant": [],
                "classified_type": None,
                "cost_usd": 0.0,
                "latency_ms": 0.0,
                "llm_calls": 0,
            })
    return rows


def _refusal_summary(rows: list[dict]) -> dict:
    refused = [r for r in rows if r["refused"]]
    reasons = Counter(
        (r["refusal_reason"] or "no-reason")[:40] for r in refused
    )
    total_cost = sum(r["cost_usd"] for r in rows)
    return {
        "n_total": len(rows),
        "n_refused": len(refused),
        "refusal_rate": len(refused) / len(rows) if rows else 0.0,
        "by_reason": dict(reasons),
        "total_cost_usd": round(total_cost, 4),
    }


def main() -> int:
    load_dotenv()

    print(f"Loading queries from {EVAL_PATH.name}")
    queries = yaml.safe_load(EVAL_PATH.read_text(encoding="utf-8"))
    print(f"  {len(queries)} rows")

    print("\nBuilding pipeline (Sabiá generator, LLM cache active)")
    pipe = load_pipeline(
        chunks_dir=CHUNKS_DIR, index_dir=INDEX_DIR,
        llm_provider="maritaca", top_k=DEFAULT_TOP_K,
        llm_cache_dir=CACHE_DIR,
    )

    # --- Variant A: default (relevance_judge = None → uses self.llm = Sabiá) ---
    print("\n=== Variant A: relevance gate uses Sabiá (default) ===")
    pipe.relevance_judge = None
    rows_sabia = _run_against_eval(pipe, queries, label="sabia")
    sum_sabia = _refusal_summary(rows_sabia)

    # --- Variant B: Opus as relevance judge ---
    print("\n=== Variant B: relevance gate uses Opus-4-7 ===")
    opus = get_llm(provider="anthropic", model=DEFAULT_JUDGE_MODEL, cache_dir=CACHE_DIR)
    pipe.relevance_judge = opus
    rows_opus = _run_against_eval(pipe, queries, label="opus ")
    sum_opus = _refusal_summary(rows_opus)

    # --- Per-row comparison ---
    by_id_sabia = {r["source_id"]: r for r in rows_sabia}
    by_id_opus = {r["source_id"]: r for r in rows_opus}
    only_sabia = []  # refused by Sabiá but not Opus
    only_opus = []   # refused by Opus but not Sabiá
    both = []        # refused by both
    neither = []     # neither
    for sid in by_id_sabia:
        s = by_id_sabia[sid]["refused"]
        o = by_id_opus[sid]["refused"]
        if s and o:
            both.append(sid)
        elif s and not o:
            only_sabia.append(sid)
        elif o and not s:
            only_opus.append(sid)
        else:
            neither.append(sid)

    # --- Headline result ---
    delta = sum_opus["refusal_rate"] - sum_sabia["refusal_rate"]
    print()
    print("=" * 60)
    print("HEADLINE COMPARISON")
    print("=" * 60)
    print(f"  Sabiá judge: refusal_rate = {sum_sabia['refusal_rate']:.3f}  "
          f"({sum_sabia['n_refused']}/{sum_sabia['n_total']})")
    print(f"  Opus judge:  refusal_rate = {sum_opus['refusal_rate']:.3f}  "
          f"({sum_opus['n_refused']}/{sum_opus['n_total']})")
    print(f"  Delta:        {delta:+.3f}pp")
    print()
    print("Per-row agreement:")
    print(f"  Both refused:    {len(both):>2}")
    print(f"  Only Sabiá:      {len(only_sabia):>2}  (Opus was lenient)")
    print(f"  Only Opus:       {len(only_opus):>2}  (Sabiá was lenient)")
    print(f"  Neither refused: {len(neither):>2}")
    print()
    print("Decision criterion (pre-locked):")
    print("  |delta| ≤ 0.10pp → keep Sabiá default")
    print("  |delta| > 0.10pp AND Opus refuses more → swap to Opus default")
    if abs(delta) <= 0.10:
        verdict = "KEEP SABIÁ — within stochastic noise"
    elif delta > 0.10:
        verdict = "SWAP TO OPUS — evidence of Sabiá leniency bias"
    else:
        verdict = "INVESTIGATE — Opus refuses materially LESS (unexpected)"
    print(f"  → {verdict}")
    print()
    print(f"Cost: Sabiá ${sum_sabia['total_cost_usd']:.4f} vs "
          f"Opus ${sum_opus['total_cost_usd']:.4f}")

    # --- Write structured output ---
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps({
            "summary": {
                "sabia": sum_sabia,
                "opus": sum_opus,
                "delta_pp": round(delta, 4),
                "verdict": verdict,
            },
            "agreement": {
                "both_refused": both,
                "only_sabia_refused": only_sabia,
                "only_opus_refused": only_opus,
                "neither_refused": neither,
            },
            "per_row": {
                "sabia": rows_sabia,
                "opus": rows_opus,
            },
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote per-row comparison → {OUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
