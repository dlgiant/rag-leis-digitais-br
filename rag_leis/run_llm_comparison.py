"""Phase 4.0.c — LLM provider comparison runner.

Drives N runs of the answer-eval against M providers, aggregates per-provider
stats (mean ± stddev), and emits a side-by-side decision-ready report.

Decision matrix (Phase 4.0 plan, study/phase-4-0-llm-comparison-plan.md):

    Sabiá-3 passes 4 thresholds simultaneously?
      faithfulness mean       ≥ 3.7 / 5    (-10% vs sonnet-4-5 baseline)
      cit_precision_lenient   ≥ 0.55       (-15%)
      rejected_citation_rate  ≤ 0.05       (load-bearing)
      refusal_accuracy        ≥ 0.85

    pass-all  → swap generator pra Sabiá-3
    pass 3/4  → hybrid (Sabiá default + Anthropic fallback by query type)
    fail rejected_rate → keep Anthropic + ZDR/DPA path

Cost: each provider x N runs ≈ N x ($0.85 anthropic | ~$0.30 marítaca).
Run with --runs 3 → ~$3-4 anthropic + ~$1 marítaca.

Usage:

    uv run python -m rag_leis.run_llm_comparison \\
        --providers anthropic,maritaca \\
        --runs 3 \\
        --output study/llm-comparison-2026-05-15.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from rag_leis.llm import DEFAULT_JUDGE_MODEL, get_llm
from rag_leis.rag import (
    DEFAULT_EMBEDDER,
    DEFAULT_OOS_THRESHOLD,
    DEFAULT_TEXT_MODE,
    DEFAULT_TOP_K,
    load_pipeline,
)
from rag_leis.run_answer_eval import (
    DEFAULT_EVAL_PATH,
    Aggregate,
    aggregate,
    load_answer_queries,
    score_in_scope,
    score_oos,
    serialize_row,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"


# ----------------------------------------------------------------------------
# Per-run data
# ----------------------------------------------------------------------------


@dataclass
class RunResult:
    provider: str
    model: str
    run_index: int
    duration_seconds: float
    aggregate: Aggregate
    rows: list[dict[str, Any]]


def run_one(
    provider: str,
    model: str | None,
    run_index: int,
    queries,
    judge,
) -> RunResult:
    pipeline = load_pipeline(
        chunks_dir=CHUNKS_DIR,
        index_dir=INDEX_DIR,
        embedder_name=DEFAULT_EMBEDDER,
        text_mode=DEFAULT_TEXT_MODE,
        llm_provider=provider,
        llm_model=model,
        top_k=DEFAULT_TOP_K,
        oos_threshold=DEFAULT_OOS_THRESHOLD,
    )
    print(
        f"\n  [{provider}/{pipeline.llm.name} run {run_index + 1}] "
        f"answering {len(queries)} queries..."
    )
    started = time.monotonic()
    rows = []
    for i, q in enumerate(queries):
        marker = "OOS" if q.oos else q.type
        print(
            f"    [{i + 1}/{len(queries)}] ({marker}) "
            f"{q.query[:60]}{'…' if len(q.query) > 60 else ''}"
        )
        ans = pipeline.answer(q.query)
        row = score_oos(q, ans) if q.oos else score_in_scope(q, ans, judge)
        rows.append(row)
    duration = time.monotonic() - started

    agg = aggregate(rows)
    return RunResult(
        provider=provider,
        model=pipeline.llm.name,
        run_index=run_index,
        duration_seconds=duration,
        aggregate=agg,
        rows=[serialize_row(r) for r in rows],
    )


# ----------------------------------------------------------------------------
# Aggregation across runs of one provider
# ----------------------------------------------------------------------------


@dataclass
class ProviderSummary:
    provider: str
    model: str
    n_runs: int
    duration_mean: float
    duration_stddev: float
    cit_precision_strict: tuple[float, float]   # (mean, stddev)
    cit_precision_lenient: tuple[float, float]
    cit_recall: tuple[float, float]
    cit_f1: tuple[float, float]
    faithfulness: tuple[float, float]
    refusal_accuracy: tuple[float, float]
    rejected_citation_rate: tuple[float, float]
    by_type: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)


def _meanstd(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return (0.0, 0.0)
    m = statistics.fmean(xs)
    s = statistics.pstdev(xs) if len(xs) > 1 else 0.0
    return (m, s)


def summarize_provider(runs: list[RunResult]) -> ProviderSummary:
    by_type_metrics: dict[str, dict[str, list[float]]] = {}
    for r in runs:
        for t, b in r.aggregate.by_type.items():
            if t not in by_type_metrics:
                by_type_metrics[t] = {
                    "cit_precision": [],
                    "cit_precision_lenient": [],
                    "cit_recall": [],
                    "cit_f1": [],
                    "faithfulness": [],
                    "refusal_accuracy": [],
                }
            for k in by_type_metrics[t]:
                by_type_metrics[t][k].append(b[k])

    by_type_meanstd = {
        t: {k: _meanstd(v) for k, v in metrics.items()}
        for t, metrics in by_type_metrics.items()
    }

    return ProviderSummary(
        provider=runs[0].provider,
        model=runs[0].model,
        n_runs=len(runs),
        duration_mean=_meanstd([r.duration_seconds for r in runs])[0],
        duration_stddev=_meanstd([r.duration_seconds for r in runs])[1],
        cit_precision_strict=_meanstd([r.aggregate.cit_precision_mean for r in runs]),
        cit_precision_lenient=_meanstd([r.aggregate.cit_precision_lenient_mean for r in runs]),
        cit_recall=_meanstd([r.aggregate.cit_recall_mean for r in runs]),
        cit_f1=_meanstd([r.aggregate.cit_f1_mean for r in runs]),
        faithfulness=_meanstd([r.aggregate.faithfulness_mean for r in runs]),
        refusal_accuracy=_meanstd([r.aggregate.refusal_accuracy for r in runs]),
        rejected_citation_rate=_meanstd([r.aggregate.rejected_citation_rate for r in runs]),
        by_type=by_type_meanstd,
    )


# ----------------------------------------------------------------------------
# Decision matrix vs Phase 4.0 plan thresholds
# ----------------------------------------------------------------------------


@dataclass
class ThresholdResult:
    metric: str
    value: float
    threshold: float
    operator: str   # ">=" or "<="
    passes: bool


def evaluate_thresholds(s: ProviderSummary) -> list[ThresholdResult]:
    """Apply the 4 Phase 4.0 thresholds to a summary."""
    return [
        ThresholdResult(
            metric="faithfulness",
            value=s.faithfulness[0],
            threshold=3.7,
            operator=">=",
            passes=s.faithfulness[0] >= 3.7,
        ),
        ThresholdResult(
            metric="cit_precision_lenient",
            value=s.cit_precision_lenient[0],
            threshold=0.55,
            operator=">=",
            passes=s.cit_precision_lenient[0] >= 0.55,
        ),
        ThresholdResult(
            metric="rejected_citation_rate",
            value=s.rejected_citation_rate[0],
            threshold=0.05,
            operator="<=",
            passes=s.rejected_citation_rate[0] <= 0.05,
        ),
        ThresholdResult(
            metric="refusal_accuracy",
            value=s.refusal_accuracy[0],
            threshold=0.85,
            operator=">=",
            passes=s.refusal_accuracy[0] >= 0.85,
        ),
    ]


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------


def _fmt_meanstd(ms: tuple[float, float], precision: int = 3) -> str:
    m, s = ms
    if s == 0.0:
        return f"{m:.{precision}f}"
    return f"{m:.{precision}f} ± {s:.{precision}f}"


def print_side_by_side(summaries: list[ProviderSummary]) -> None:
    """Print a markdown-friendly side-by-side comparison."""
    print()
    print("# LLM Comparison Report")
    print()
    headers = ["metric"] + [f"{s.provider}/{s.model}" for s in summaries]
    print(" | ".join(headers))
    print(" | ".join(["---"] * len(headers)))

    rows = [
        ("Citation P strict", "cit_precision_strict"),
        ("Citation P lenient", "cit_precision_lenient"),
        ("Citation recall", "cit_recall"),
        ("Citation F1 (strict)", "cit_f1"),
        ("Faithfulness (0-5)", "faithfulness"),
        ("Refusal accuracy", "refusal_accuracy"),
        ("Rejected cit. rate", "rejected_citation_rate"),
        ("Wall-clock per run (s)", "duration"),
    ]
    for label, attr in rows:
        if attr == "duration":
            cells = [_fmt_meanstd((s.duration_mean, s.duration_stddev), precision=1) for s in summaries]
        else:
            cells = [_fmt_meanstd(getattr(s, attr)) for s in summaries]
        print(f"{label} | " + " | ".join(cells))

    print()
    print("## Decision matrix (Phase 4.0 thresholds)")
    print()
    for s in summaries:
        results = evaluate_thresholds(s)
        passes = sum(1 for r in results if r.passes)
        verdict = "✅ PASS-ALL" if passes == 4 else (
            "⚠️ PARTIAL" if passes >= 2 else "❌ FAIL"
        )
        print(f"\n### {s.provider}/{s.model} — {verdict} ({passes}/4)")
        print()
        for r in results:
            mark = "✅" if r.passes else "❌"
            print(
                f"  {mark} `{r.metric}` = {r.value:.3f} "
                f"{r.operator} {r.threshold} → {'pass' if r.passes else 'fail'}"
            )

    print()
    print("## Per-type breakdown")
    print()
    if not summaries:
        return
    types = sorted(summaries[0].by_type.keys())
    for t in types:
        print(f"\n### type: {t}")
        print()
        bt_headers = ["metric"] + [f"{s.provider}/{s.model}" for s in summaries]
        print(" | ".join(bt_headers))
        print(" | ".join(["---"] * len(bt_headers)))
        for label, key in [
            ("cit_precision", "cit_precision"),
            ("cit_precision_lenient", "cit_precision_lenient"),
            ("cit_recall", "cit_recall"),
            ("cit_f1", "cit_f1"),
            ("faithfulness", "faithfulness"),
            ("refusal_accuracy", "refusal_accuracy"),
        ]:
            cells = [_fmt_meanstd(s.by_type.get(t, {}).get(key, (0.0, 0.0))) for s in summaries]
            print(f"{label} | " + " | ".join(cells))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Compare LLM providers across N runs of the answer-eval."
    )
    p.add_argument(
        "--providers",
        default="anthropic,maritaca",
        help="Comma-separated list of providers to compare",
    )
    p.add_argument(
        "--models",
        default=None,
        help=(
            "Comma-separated list of model overrides matching --providers "
            "(e.g., 'claude-sonnet-4-5,sabia-4'). If omitted, each provider's "
            "default is used."
        ),
    )
    p.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Runs per provider (default: 3)",
    )
    p.add_argument(
        "--judge-provider",
        default="anthropic",
        choices=["anthropic", "maritaca"],
        help="Judge provider (default: anthropic — opus-4-7)",
    )
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument(
        "--eval", default=str(DEFAULT_EVAL_PATH), help="Path to answer_queries.yaml"
    )
    p.add_argument(
        "--output",
        default=None,
        help="Optional path to dump per-provider per-run JSON (default: stdout only)",
    )
    args = p.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    if args.models:
        models_list: list[str | None] = [
            (m.strip() or None) for m in args.models.split(",")
        ]
        if len(models_list) != len(providers):
            print(
                f"--models has {len(models_list)} entries but --providers has "
                f"{len(providers)}. Use empty string to default a slot.",
                file=sys.stderr,
            )
            return 2
    else:
        models_list = [None] * len(providers)

    print(f"Comparing {len(providers)} providers x {args.runs} runs each")
    print(f"  providers : {providers}")
    print(f"  models    : {models_list}")
    print(f"  judge     : {args.judge_provider}/{args.judge_model}")

    queries = load_answer_queries(Path(args.eval))
    print(f"  queries   : {len(queries)} from {args.eval}")

    judge = get_llm(provider=args.judge_provider, model=args.judge_model)

    all_runs: dict[str, list[RunResult]] = {}
    for provider, model in zip(providers, models_list, strict=True):
        runs_for_provider: list[RunResult] = []
        for i in range(args.runs):
            r = run_one(provider, model, i, queries, judge)
            runs_for_provider.append(r)
            print(
                f"\n  → {provider}/{r.model} run {i + 1}: "
                f"faith={r.aggregate.faithfulness_mean:.2f}, "
                f"P_l={r.aggregate.cit_precision_lenient_mean:.2f}, "
                f"rejected={r.aggregate.rejected_citation_rate:.3f}, "
                f"refusal={r.aggregate.refusal_accuracy:.2f}, "
                f"{r.duration_seconds:.0f}s"
            )
        all_runs[f"{provider}/{runs_for_provider[0].model}"] = runs_for_provider

    summaries = [summarize_provider(runs) for runs in all_runs.values()]
    print_side_by_side(summaries)

    if args.output:
        payload = {
            "config": {
                "providers": providers,
                "models": models_list,
                "runs_per_provider": args.runs,
                "judge": f"{args.judge_provider}/{args.judge_model}",
                "eval_path": str(args.eval),
                "n_queries": len(queries),
            },
            "summaries": [asdict(s) for s in summaries],
            "raw_runs": {
                key: [
                    {
                        "provider": r.provider,
                        "model": r.model,
                        "run_index": r.run_index,
                        "duration_seconds": r.duration_seconds,
                        "aggregate": asdict(r.aggregate),
                        "rows": r.rows,
                    }
                    for r in runs
                ]
                for key, runs in all_runs.items()
            },
        }
        Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\nWrote raw + summary JSON → {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
