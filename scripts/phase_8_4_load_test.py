"""Phase 8.4 — Load test + capacity harness.

Hits a running `rag_leis.server` instance with concurrent /v1/ask
requests across a sweep of concurrency levels. Workload = the 78
queries from eval/answer_queries.yaml + eval/legalbench_br_oos.yaml,
shuffled with replacement to fill each level's request budget.

Plan: study/phase-8.4-load-test-plan.md. Single-axis-at-a-time:
v1 only varies concurrency. Cache is pre-warmed via the cap=1 level
so subsequent levels measure server-side capacity (not provider
rate limit). The server should be started with
`RAG_RATE_LIMIT_PER_MINUTE=0` so the harness measures capacity, not
the rate limiter.

Usage:
    # Terminal 1 — start the server with cache + rate limit disabled
    RAG_API_KEYS=rag_loadtest RAG_RATE_LIMIT_PER_MINUTE=0 \\
        RAG_LLM_CACHE_DIR=data/cache/llm \\
        uv run uvicorn rag_leis.server:app --port 8000

    # Terminal 2 — run the sweep
    PYTHONPATH=. uv run python -m scripts.phase_8_4_load_test \\
        --api-key rag_loadtest --base-url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_PATHS = [
    PROJECT_ROOT / "eval" / "answer_queries.yaml",
    PROJECT_ROOT / "eval" / "legalbench_br_oos.yaml",
]
DEFAULT_OUT = PROJECT_ROOT / "eval" / "runs" / "phase-8.4-load-test.json"


def load_workload() -> list[str]:
    """Load all queries from both eval surfaces."""
    all_queries: list[str] = []
    for p in EVAL_PATHS:
        rows = yaml.safe_load(p.read_text(encoding="utf-8"))
        for r in rows:
            q = r.get("query")
            if isinstance(q, str) and q.strip():
                all_queries.append(q)
    return all_queries


async def one_request(client: httpx.AsyncClient, url: str, api_key: str, query: str) -> dict[str, Any]:
    """Send one request; return per-request stats. Never raises — errors
    captured into the result dict so the worker can continue."""
    t0 = time.monotonic()
    try:
        r = await client.post(
            url,
            json={"query": query},
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        )
        latency_ms = (time.monotonic() - t0) * 1000.0
        body: dict[str, Any] = {}
        if r.status_code == 200:
            try:
                body = r.json()
            except Exception:
                body = {}
        return {
            "status": r.status_code,
            "latency_ms": latency_ms,
            "cost_estimate_usd": float(body.get("cost_estimate_usd", 0.0)),
            "error": None,
        }
    except Exception as e:
        return {
            "status": 0,
            "latency_ms": (time.monotonic() - t0) * 1000.0,
            "cost_estimate_usd": 0.0,
            "error": f"{type(e).__name__}: {e}",
        }


async def worker(
    queue: asyncio.Queue[str],
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    results: list[dict[str, Any]],
) -> None:
    """One concurrent worker: pull queries off the queue until empty."""
    while True:
        try:
            query = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        result = await one_request(client, url, api_key, query)
        results.append(result)


async def run_level(
    concurrency: int,
    total: int,
    queries: list[str],
    base_url: str,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    """Execute one (concurrency, total) cell; return aggregate stats."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    for _ in range(total):
        queue.put_nowait(random.choice(queries))
    results: list[dict[str, Any]] = []
    url = f"{base_url}/v1/ask"
    async with httpx.AsyncClient(timeout=timeout) as client:
        workers = [
            worker(queue, client, url, api_key, results) for _ in range(concurrency)
        ]
        t0 = time.monotonic()
        await asyncio.gather(*workers)
        wall_seconds = time.monotonic() - t0
    return _aggregate(results, concurrency, wall_seconds)


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = max(1, min(len(sorted_values), int(round(p / 100.0 * len(sorted_values)))))
    return sorted_values[k - 1]


def _aggregate(results: list[dict[str, Any]], concurrency: int, wall_seconds: float) -> dict[str, Any]:
    n = len(results)
    success = [r for r in results if r["status"] == 200]
    errors = [r for r in results if r["status"] != 200]
    latencies = sorted([r["latency_ms"] for r in success])
    status_counter = Counter(r["status"] for r in results)
    return {
        "concurrency": concurrency,
        "n_total": n,
        "n_success": len(success),
        "n_error": len(errors),
        "error_rate": round(len(errors) / n, 4) if n else 0.0,
        "latency_p50_ms": round(_percentile(latencies, 50), 1),
        "latency_p95_ms": round(_percentile(latencies, 95), 1),
        "latency_p99_ms": round(_percentile(latencies, 99), 1),
        "latency_mean_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "throughput_qps": round(len(success) / wall_seconds, 2) if wall_seconds > 0 else 0,
        "wall_seconds": round(wall_seconds, 2),
        "cost_total_usd": round(sum(r["cost_estimate_usd"] for r in success), 6),
        "cost_mean_usd": (
            round(statistics.mean([r["cost_estimate_usd"] for r in success]), 6) if success else 0.0
        ),
        "status_distribution": dict(status_counter),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--levels", default="1,2,4,8,16,32",
                   help="Comma-separated concurrency levels")
    p.add_argument("--per-level", default="50,50,100,100,200,200",
                   help="Comma-separated total requests per level (same length as --levels)")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--api-key", required=True)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--max-cost-usd", type=float, default=1.0,
                   help="Cumulative spend cap; sweep aborts past this")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--seed", type=int, default=42, help="random.seed() for repeatable workload sampling")
    args = p.parse_args()

    levels = [int(x) for x in args.levels.split(",")]
    per_level = [int(x) for x in args.per_level.split(",")]
    if len(levels) != len(per_level):
        print(f"ERROR: --levels has {len(levels)} entries; --per-level has {len(per_level)}; must match.")
        return 1

    random.seed(args.seed)
    queries = load_workload()
    if not queries:
        print("ERROR: no queries loaded from eval yamls")
        return 1

    print(f"Loaded {len(queries)} queries from eval surfaces")
    print(f"Sweeping concurrency levels: {levels}")
    print(f"Requests per level: {per_level}")
    print(f"Budget cap: ${args.max_cost_usd}\n")

    # Pre-flight: confirm server is reachable
    try:
        h = httpx.get(f"{args.base_url}/health", timeout=10.0)
        if h.status_code != 200 or not h.json().get("pipeline_loaded"):
            print(f"ERROR: server at {args.base_url} not ready: {h.status_code} {h.text[:200]}")
            return 1
    except Exception as e:
        print(f"ERROR: cannot reach {args.base_url}/health: {e}")
        return 1
    print(f"Server ready at {args.base_url}\n")

    sweep: list[dict[str, Any]] = []
    cumulative_cost = 0.0
    for level, total in zip(levels, per_level):
        if cumulative_cost > args.max_cost_usd:
            print(f"!! Cost cap reached (${cumulative_cost:.4f}); aborting before level={level}")
            break
        print(f"--- concurrency={level}, total={total} ---", flush=True)
        agg = asyncio.run(run_level(level, total, queries, args.base_url, args.api_key, args.timeout))
        cumulative_cost += agg["cost_total_usd"]
        agg["cumulative_cost_usd"] = round(cumulative_cost, 6)
        sweep.append(agg)
        print(
            f"  n={agg['n_total']:>3}  err={agg['n_error']:>2}  "
            f"p50={agg['latency_p50_ms']:>6.0f}ms  p95={agg['latency_p95_ms']:>6.0f}ms  "
            f"p99={agg['latency_p99_ms']:>6.0f}ms  qps={agg['throughput_qps']:>5.2f}  "
            f"cost=${agg['cost_total_usd']:.4f}  cum=${cumulative_cost:.4f}",
            flush=True,
        )

    # Headline table
    print()
    print("=" * 84)
    print("PHASE 8.4 — LOAD TEST CAPACITY TABLE")
    print("=" * 84)
    print(f"  {'concur':>6}  {'n':>4}  {'err%':>5}  {'p50':>6}  {'p95':>6}  {'p99':>6}  {'qps':>5}  {'cost_total':>10}")
    for row in sweep:
        print(
            f"  {row['concurrency']:>6}  "
            f"{row['n_total']:>4}  "
            f"{row['error_rate']*100:>4.1f}%  "
            f"{row['latency_p50_ms']:>6.0f}  "
            f"{row['latency_p95_ms']:>6.0f}  "
            f"{row['latency_p99_ms']:>6.0f}  "
            f"{row['throughput_qps']:>5.2f}  "
            f"${row['cost_total_usd']:>9.4f}"
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "config": {
            "base_url": args.base_url,
            "levels": levels,
            "per_level": per_level,
            "timeout_s": args.timeout,
            "seed": args.seed,
            "n_unique_queries": len(queries),
        },
        "sweep": sweep,
        "cumulative_cost_usd": round(cumulative_cost, 6),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        display = out_path.relative_to(PROJECT_ROOT)
    except ValueError:
        display = out_path
    print(f"\nWrote → {display}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
