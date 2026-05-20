"""Phase 8.0.1 — sabia-3.1 vs sabia-4 A/B in production config.

The 2026-05-15 LLM provider decision (study/llm-provider-decision-2026-05-15.md)
locked sabia-3.1 as the production default vs sonnet-4-5, but explicitly
deferred a sabia-3.1 vs sabia-4 bake-off ("re-run when sabia-4 matures").
All three deferral conditions are now met (sabia-4 available, eval set
>50 rows, Phase 8.0 entry anchored to whichever generator we pick), so
this is the re-run.

Compares both surfaces (internal + legalbench), both variants, with
relevance_judge=None (default → self-judging). Reports cost, latency,
refusal patterns, and agreement matrix. Pre-locked criterion:

  Swap to sabia-4 default iff:
  1. In-scope false_refusal_rate decreases by ≥ 0.07pp
     (i.e., sabia-3.1's 0.143 → sabia-4 ≤ 0.071), AND
  2. OOS refusal recall doesn't regress more than 0.05pp, AND
  3. Cost increase < 2× (sabia-4 list pricing is +60%; effective cost
     may be more/less depending on refused-row distribution).

Cost estimate this run: ~$1 (sabia-4 calls on ~78 rows; sabia-3.1
is fully cached from today's Phase 8.0).

Uso:
    PYTHONPATH=. uv run python -m scripts.phase_8_0_1_sabia_3_1_vs_4
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from rag_leis.rag import DEFAULT_TOP_K, RAGAnswer, load_pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "llm"
INSCOPE_EVAL = PROJECT_ROOT / "eval" / "answer_queries.yaml"
LEGALBENCH_EVAL = PROJECT_ROOT / "eval" / "legalbench_br_oos.yaml"
OUT_PATH = PROJECT_ROOT / "eval" / "runs" / "phase-8-0-1-sabia-3.1-vs-4.json"


def _run_against_eval(pipe, queries, label: str, query_field: str) -> list[dict]:
    rows: list[dict] = []
    for i, q in enumerate(queries, 1):
        query = q[query_field]
        print(f"  [{label}] [{i:>2}/{len(queries)}] {query[:60]}", flush=True)
        try:
            ans: RAGAnswer = pipe.answer(query)
            rows.append({
                "query": query[:200],
                "source_id": q.get("source_id"),
                "oos": q.get("oos", None),
                "refused": ans.refused,
                "refusal_reason": ans.refusal_reason,
                "n_citations": len(ans.citations),
                "n_rejected_irrelevant": len(ans.rejected_irrelevant_citations),
                "classified_type": ans.classified_type,
                "cost_estimate_usd": round(ans.cost_estimate_usd, 6),
                "latency_ms": round(ans.latency_ms, 1),
                "error": None,
            })
        except Exception as e:
            rows.append({
                "query": query[:200],
                "source_id": q.get("source_id"),
                "oos": q.get("oos", None),
                "refused": True,
                "refusal_reason": None,
                "n_citations": 0,
                "n_rejected_irrelevant": 0,
                "classified_type": None,
                "cost_estimate_usd": 0.0,
                "latency_ms": 0.0,
                "error": f"{type(e).__name__}: {e}",
            })
    return rows


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}
    s = sorted(values)
    def pct(p):
        k = max(1, min(len(s), round(p / 100.0 * len(s))))
        return s[k - 1]
    return {"p50": pct(50), "p95": pct(95), "p99": pct(99), "mean": statistics.mean(s)}


def _summarize(rows: list[dict]) -> dict:
    n = len(rows)
    refused = sum(1 for r in rows if r["refused"])
    in_scope = [r for r in rows if r.get("oos") is False]
    oos = [r for r in rows if r.get("oos") is True or (r.get("source_id") or "").startswith("celsowm")]
    in_scope_refused = sum(1 for r in in_scope if r["refused"])
    oos_refused = sum(1 for r in oos if r["refused"])
    costs = [r["cost_estimate_usd"] for r in rows if r["error"] is None]
    lats = [r["latency_ms"] for r in rows if r["error"] is None]
    return {
        "n_total": n,
        "n_refused": refused,
        "refusal_rate": refused / n if n else 0,
        "n_inscope": len(in_scope),
        "inscope_refused": in_scope_refused,
        "inscope_false_refusal_rate": in_scope_refused / len(in_scope) if in_scope else 0,
        "n_oos": len(oos),
        "oos_refused": oos_refused,
        "oos_refusal_recall": oos_refused / len(oos) if oos else 0,
        "cost": _percentiles(costs),
        "cost_total_usd": round(sum(costs), 4),
        "latency_ms": _percentiles(lats),
    }


def _agreement_matrix(rows_a: list[dict], rows_b: list[dict]) -> dict:
    """Pair up rows by query (first-200-char prefix) and compare refusal decisions."""
    by_q_a = {r["query"]: r for r in rows_a}
    by_q_b = {r["query"]: r for r in rows_b}
    both = []
    only_a = []
    only_b = []
    neither = []
    for q, ra in by_q_a.items():
        rb = by_q_b.get(q)
        if rb is None:
            continue
        if ra["refused"] and rb["refused"]:
            both.append(q[:80])
        elif ra["refused"]:
            only_a.append(q[:80])
        elif rb["refused"]:
            only_b.append(q[:80])
        else:
            neither.append(q[:80])
    return {
        "both_refused": len(both),
        "only_a_refused": len(only_a),
        "only_b_refused": len(only_b),
        "neither_refused": len(neither),
        "only_a_refused_queries": only_a,
        "only_b_refused_queries": only_b,
    }


def main() -> int:
    load_dotenv()

    inscope_queries = yaml.safe_load(INSCOPE_EVAL.read_text(encoding="utf-8"))
    legalbench_queries = yaml.safe_load(LEGALBENCH_EVAL.read_text(encoding="utf-8"))
    print(f"Loaded {len(inscope_queries)} internal + {len(legalbench_queries)} legalbench = {len(inscope_queries) + len(legalbench_queries)} rows")

    print("\n=== Variant A: sabia-3.1 (current default) ===")
    pipe_a = load_pipeline(
        chunks_dir=CHUNKS_DIR, index_dir=INDEX_DIR,
        llm_provider="maritaca", llm_model="sabia-3.1",
        top_k=DEFAULT_TOP_K, oos_threshold=0.4,
        llm_cache_dir=CACHE_DIR,
    )
    print(f"  generator: {pipe_a.llm.provider}/{pipe_a.llm.name}  (cache: {CACHE_DIR.name})")
    rows_a_internal = _run_against_eval(pipe_a, inscope_queries, "a-int", "query")
    rows_a_legalbench = _run_against_eval(pipe_a, legalbench_queries, "a-leg", "query")
    rows_a = rows_a_internal + rows_a_legalbench

    print("\n=== Variant B: sabia-4 (candidate) ===")
    pipe_b = load_pipeline(
        chunks_dir=CHUNKS_DIR, index_dir=INDEX_DIR,
        llm_provider="maritaca", llm_model="sabia-4",
        top_k=DEFAULT_TOP_K, oos_threshold=0.4,
        llm_cache_dir=CACHE_DIR,
    )
    print(f"  generator: {pipe_b.llm.provider}/{pipe_b.llm.name}  (cache: {CACHE_DIR.name})")
    rows_b_internal = _run_against_eval(pipe_b, inscope_queries, "b-int", "query")
    rows_b_legalbench = _run_against_eval(pipe_b, legalbench_queries, "b-leg", "query")
    rows_b = rows_b_internal + rows_b_legalbench

    sum_a = _summarize(rows_a)
    sum_b = _summarize(rows_b)
    agreement = _agreement_matrix(rows_a, rows_b)

    delta_inscope_fr = sum_b["inscope_false_refusal_rate"] - sum_a["inscope_false_refusal_rate"]
    delta_oos_recall = sum_b["oos_refusal_recall"] - sum_a["oos_refusal_recall"]
    cost_ratio = sum_b["cost_total_usd"] / sum_a["cost_total_usd"] if sum_a["cost_total_usd"] else float('inf')

    print()
    print("=" * 72)
    print("PHASE 8.0.1 — sabia-3.1 vs sabia-4 (production config)")
    print("=" * 72)
    print()
    print(f"{'Metric':40} {'sabia-3.1':>12} {'sabia-4':>12} {'Δ':>10}")
    print(f"{'in-scope false_refusal_rate':40} {sum_a['inscope_false_refusal_rate']:>12.3f} {sum_b['inscope_false_refusal_rate']:>12.3f} {delta_inscope_fr:>+10.3f}")
    print(f"{'OOS refusal recall':40} {sum_a['oos_refusal_recall']:>12.3f} {sum_b['oos_refusal_recall']:>12.3f} {delta_oos_recall:>+10.3f}")
    print(f"{'cost mean per query (all rows)':40} {sum_a['cost']['mean']:>12.4f} {sum_b['cost']['mean']:>12.4f} {sum_b['cost']['mean']-sum_a['cost']['mean']:>+10.4f}")
    print(f"{'cost p95':40} {sum_a['cost']['p95']:>12.4f} {sum_b['cost']['p95']:>12.4f}")
    print(f"{'cost total (78 rows)':40} {sum_a['cost_total_usd']:>12.4f} {sum_b['cost_total_usd']:>12.4f}  ({cost_ratio:.2f}x)")
    print(f"{'latency p50 (ms)':40} {sum_a['latency_ms']['p50']:>12.0f} {sum_b['latency_ms']['p50']:>12.0f}")
    print(f"{'latency p95 (ms)':40} {sum_a['latency_ms']['p95']:>12.0f} {sum_b['latency_ms']['p95']:>12.0f}")
    print(f"{'latency p99 (ms)':40} {sum_a['latency_ms']['p99']:>12.0f} {sum_b['latency_ms']['p99']:>12.0f}")

    print()
    print("Per-row refusal agreement (n=78):")
    print(f"  Both refused:    {agreement['both_refused']}")
    print(f"  Only sabia-3.1:  {agreement['only_a_refused']}  (sabia-4 was lenient)")
    print(f"  Only sabia-4:    {agreement['only_b_refused']}  (sabia-3.1 was lenient)")
    print(f"  Neither refused: {agreement['neither_refused']}")

    if agreement["only_a_refused_queries"]:
        print("\n  Rows ONLY sabia-3.1 refused (sabia-4 answered):")
        for q in agreement["only_a_refused_queries"]:
            print(f"    - {q}")
    if agreement["only_b_refused_queries"]:
        print("\n  Rows ONLY sabia-4 refused (sabia-3.1 answered):")
        for q in agreement["only_b_refused_queries"]:
            print(f"    - {q}")

    # Pre-locked criterion check
    print()
    print("Pre-locked criterion (swap to sabia-4 default iff all of):")
    c1 = delta_inscope_fr <= -0.07
    c2 = delta_oos_recall >= -0.05
    c3 = cost_ratio < 2.0
    print(f"  1. in-scope FR drops by >= 0.07pp:           {sum_a['inscope_false_refusal_rate']:.3f} -> {sum_b['inscope_false_refusal_rate']:.3f}  ({delta_inscope_fr:+.3f})  {'MET' if c1 else 'NOT MET'}")
    print(f"  2. OOS recall doesn't drop more than 0.05pp: {sum_a['oos_refusal_recall']:.3f} -> {sum_b['oos_refusal_recall']:.3f}  ({delta_oos_recall:+.3f})  {'MET' if c2 else 'NOT MET'}")
    print(f"  3. cost increase < 2x:                        {cost_ratio:.2f}x  {'MET' if c3 else 'NOT MET'}")
    if c1 and c2 and c3:
        verdict = "SWAP — sabia-4 dominates on the criterion"
    elif c2 and c3 and not c1:
        verdict = "KEEP sabia-3.1 — sabia-4 cheaper/comparable but doesn't fix in-scope FR"
    else:
        verdict = "INVESTIGATE — criterion partially met"
    print(f"\n  → {verdict}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "config": {
            "variant_a": "maritaca/sabia-3.1",
            "variant_b": "maritaca/sabia-4",
            "relevance_judge": "self.llm (no override) for both variants",
            "answer_quality_judge": "DISABLED",
            "cache_dir": str(CACHE_DIR.relative_to(PROJECT_ROOT)),
            "criterion": {
                "in_scope_fr_drop_pct": 0.07,
                "max_oos_recall_drop_pct": 0.05,
                "max_cost_ratio": 2.0,
            },
        },
        "summary": {
            "sabia_3_1": sum_a,
            "sabia_4": sum_b,
            "delta_inscope_fr": round(delta_inscope_fr, 4),
            "delta_oos_recall": round(delta_oos_recall, 4),
            "cost_ratio": round(cost_ratio, 4),
            "verdict": verdict,
        },
        "agreement": agreement,
        "rows": {
            "sabia_3_1": rows_a,
            "sabia_4": rows_b,
        },
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote → {OUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
