"""Phase 8.0 — Production cost baseline.

Runs the pipeline in PRODUCTION config (Sabiá generator + Sabiá relevance
judge, no answer-quality judge) against the internal answer eval + the
legalbench OOS eval. Reports per-row cost, latency, refusal, and
aggregates — the actual numbers Phase 8 SLO conversations need.

The default `run_answer_eval` runs an Opus answer-quality judge to score
faithfulness; that judge call is eval-only, not production. This script
skips it entirely so `RAGAnswer.cost_estimate_usd` reflects prod-only
cost (generator + relevance gate).

LLM cache active. Sabiá generator + Sabiá relevance judge calls on
legalbench were cached during today's Phase 7.8.2 legalbench re-run;
internal eval Sabiá-relevance-judge calls will be fresh (we previously
only ran the internal eval with Opus relevance judge today). Expected
fresh API spend: ~$0.05 for the new Sabiá relevance calls.

Uso:
    PYTHONPATH=. uv run python -m scripts.phase_8_0_prod_cost_baseline
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter, defaultdict
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
OUT_PATH = PROJECT_ROOT / "eval" / "runs" / "phase-8-0-prod-cost-baseline.json"


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
                "oos": q.get("oos", None),  # may be absent on legalbench
                "refused": ans.refused,
                "refusal_reason": ans.refusal_reason,
                "n_citations": len(ans.citations),
                "n_rejected_irrelevant": len(ans.rejected_irrelevant_citations),
                "classified_type": ans.classified_type,
                "cost_estimate_usd": round(ans.cost_estimate_usd, 6),
                "tokens_input": (ans.tokens_used or {}).get("input_tokens", 0),
                "tokens_output": (ans.tokens_used or {}).get("output_tokens", 0),
                "llm_calls": ans.llm_calls,
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
                "tokens_input": 0,
                "tokens_output": 0,
                "llm_calls": 0,
                "latency_ms": 0.0,
                "error": f"{type(e).__name__}: {e}",
            })
    return rows


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "median": 0.0}
    s = sorted(values)
    def pct(p: float) -> float:
        # nearest-rank percentile, 1-indexed to match Phase 7.5.7 convention
        if not s:
            return 0.0
        k = max(1, min(len(s), int(round(p / 100.0 * len(s)))))
        return s[k - 1]
    return {
        "p50": pct(50),
        "p95": pct(95),
        "p99": pct(99),
        "mean": statistics.mean(s),
        "median": statistics.median(s),
    }


def _aggregate(rows: list[dict], surface: str) -> dict:
    n = len(rows)
    errors = sum(1 for r in rows if r["error"])
    refused = sum(1 for r in rows if r["refused"])
    answered = n - refused
    costs_all = [r["cost_estimate_usd"] for r in rows if r["error"] is None]
    costs_answered = [r["cost_estimate_usd"] for r in rows if not r["refused"] and r["error"] is None]
    costs_refused = [r["cost_estimate_usd"] for r in rows if r["refused"] and r["error"] is None]
    lats_all = [r["latency_ms"] for r in rows if r["error"] is None]
    lats_answered = [r["latency_ms"] for r in rows if not r["refused"] and r["error"] is None]

    by_type = defaultdict(list)
    for r in rows:
        if r["error"] is None:
            by_type[r["classified_type"] or "unclassified"].append(
                (r["cost_estimate_usd"], r["latency_ms"])
            )
    by_type_summary = {}
    for t, pairs in by_type.items():
        cs = [p[0] for p in pairs]
        ls = [p[1] for p in pairs]
        by_type_summary[t] = {
            "n": len(pairs),
            "cost_mean": statistics.mean(cs) if cs else 0,
            "latency_p50_ms": _percentiles(ls)["p50"],
            "latency_p95_ms": _percentiles(ls)["p95"],
        }

    return {
        "surface": surface,
        "n_total": n,
        "n_refused": refused,
        "n_answered": answered,
        "n_error": errors,
        "refusal_rate": refused / n if n else 0,
        "error_rate": errors / n if n else 0,
        "cost_all": _percentiles(costs_all),
        "cost_answered_only": _percentiles(costs_answered),
        "cost_refused_only": _percentiles(costs_refused),
        "latency_ms_all": _percentiles(lats_all),
        "latency_ms_answered_only": _percentiles(lats_answered),
        "cost_total_usd": round(sum(costs_all), 4),
        "by_classified_type": by_type_summary,
    }


def main() -> int:
    load_dotenv()

    print("Loading pipeline in PROD config")
    print(f"  generator:        Sabiá-3.1 (maritaca)")
    print(f"  relevance judge:  Sabiá (default — uses self.llm; no override)")
    print(f"  answer-quality judge:  NOT CALLED (eval-only; this script skips it)")
    print(f"  cache:            {CACHE_DIR}")
    pipe = load_pipeline(
        chunks_dir=CHUNKS_DIR, index_dir=INDEX_DIR,
        llm_provider="maritaca", llm_model=None,
        top_k=DEFAULT_TOP_K, oos_threshold=0.4,
        llm_cache_dir=CACHE_DIR,
    )
    # Explicit: no override → relevance_judge stays None → gate uses self.llm
    assert pipe.relevance_judge is None
    print(f"  generator instance: {pipe.llm.provider}/{pipe.llm.name}")

    print(f"\n=== Surface 1: internal answer eval ({INSCOPE_EVAL.name}) ===")
    inscope_queries = yaml.safe_load(INSCOPE_EVAL.read_text(encoding="utf-8"))
    print(f"  n={len(inscope_queries)}")
    inscope_rows = _run_against_eval(pipe, inscope_queries, label="internal", query_field="query")

    print(f"\n=== Surface 2: legalbench OOS ({LEGALBENCH_EVAL.name}) ===")
    legalbench_queries = yaml.safe_load(LEGALBENCH_EVAL.read_text(encoding="utf-8"))
    print(f"  n={len(legalbench_queries)}")
    legalbench_rows = _run_against_eval(pipe, legalbench_queries, label="legalbench", query_field="query")

    agg_inscope = _aggregate(inscope_rows, surface="internal_answer_eval")
    agg_legalbench = _aggregate(legalbench_rows, surface="legalbench_br_oos")
    agg_combined = _aggregate(inscope_rows + legalbench_rows, surface="combined")

    print()
    print("=" * 72)
    print("PHASE 8.0 — PRODUCTION COST BASELINE")
    print("=" * 72)
    for label, agg in [("INTERNAL", agg_inscope), ("LEGALBENCH OOS", agg_legalbench), ("COMBINED", agg_combined)]:
        print(f"\n  {label}  (n={agg['n_total']}, answered={agg['n_answered']}, refused={agg['n_refused']}, errors={agg['n_error']})")
        print(f"    Cost (all rows):                       mean ${agg['cost_all']['mean']:.4f}  p50 ${agg['cost_all']['p50']:.4f}  p95 ${agg['cost_all']['p95']:.4f}  p99 ${agg['cost_all']['p99']:.4f}")
        print(f"    Cost (answered only — SLO target):     mean ${agg['cost_answered_only']['mean']:.4f}  p50 ${agg['cost_answered_only']['p50']:.4f}  p95 ${agg['cost_answered_only']['p95']:.4f}")
        print(f"    Latency (all rows):                    p50 {agg['latency_ms_all']['p50']/1000:.2f}s  p95 {agg['latency_ms_all']['p95']/1000:.2f}s  p99 {agg['latency_ms_all']['p99']/1000:.2f}s")
        print(f"    Refusal rate:  {agg['refusal_rate']:.3f}")
        print(f"    Error rate:    {agg['error_rate']:.3f}")
        print(f"    Cost total (this surface):  ${agg['cost_total_usd']}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "config": {
            "generator": f"{pipe.llm.provider}/{pipe.llm.name}",
            "relevance_judge": "self.llm (default, no override)",
            "answer_quality_judge": "DISABLED — eval-only",
            "cache_dir": str(CACHE_DIR.relative_to(PROJECT_ROOT)),
            "top_k": DEFAULT_TOP_K,
        },
        "aggregate": {
            "internal": agg_inscope,
            "legalbench": agg_legalbench,
            "combined": agg_combined,
        },
        "rows": {
            "internal": inscope_rows,
            "legalbench": legalbench_rows,
        },
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote → {OUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
