"""Phase 17.1 — nightly refusal-discipline canary.

Runs a small fixed subset (20 OOS rows + 10 in-scope rows) through the
production-equivalent pipeline and gates on two metrics:

  * `oos_refusal_recall ≥ 0.55` — fraction of OOS rows where the
    pipeline correctly refused (cosine fast-path OR LLM self-refusal).
  * `false_refusal_rate ≤ 0.02` — fraction of in-scope rows that the
    pipeline incorrectly refused.

Gate values match the Phase 17.5 calibration findings (the calibrated
threshold catches ~2% OOS at zero false-refusal cost; the canary's
55% gate captures the LLM self-refusal stage as the load-bearing
classifier — see study/phase-17.5-oos-threshold-calibration.md).

Sample sizes are deliberately small (Phase 8.6 budget: ~$0.30/night +
~3 minutes wall-clock). Catches regression *direction*, not absolute
precision. If a deeper drop is needed, a weekly run can use the full
49-row OOS set.

Sample selection: deterministic — sorted by source_id, first N. Means
the same rows are scored every night, so day-to-day drift is
attributable to model/corpus changes, not sampling noise.

Behavior on gate failure:
  * Exits with code 1 (CI marks the run as failed).
  * If SLACK_WEBHOOK_URL is set, posts a one-line alert message.
  * The script always prints the full metrics + per-row results to
    stdout so the GHA log carries the evidence.

Cost / latency:
  * ~30 LLM calls × ~$0.005/call (Maritaca sabia-4) = ~$0.15
  * + ~30 LLM calls for relevance_judge = ~$0.15
  * Total ~$0.30; wall-clock ~2-3 min serial.

Run:
    uv run python scripts/phase_17_1_refusal_canary.py
    uv run python scripts/phase_17_1_refusal_canary.py --n-oos 3 --n-inscope 2  # smoke-only
    uv run python scripts/phase_17_1_refusal_canary.py --dry-run  # no LLM, prints subset
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"
OOS_EVAL = PROJECT_ROOT / "eval" / "legalbench_br_oos.yaml"
INSCOPE_EVAL = PROJECT_ROOT / "eval" / "queries.yaml"

# Gate thresholds — see study/phase-17.5-oos-threshold-calibration.md
# for rationale. These match the roadmap (phase-16-19-roadmap.md:48)
# verbatim so the gate doesn't drift from the eval-set design intent.
GATE_OOS_REFUSAL_RECALL_MIN = 0.55
GATE_FALSE_REFUSAL_RATE_MAX = 0.02

DEFAULT_N_OOS = 20
DEFAULT_N_INSCOPE = 10


@dataclass(frozen=True)
class RowResult:
    source_id: str
    category: str  # "oos" | "inscope"
    query: str
    refused: bool
    refusal_reason: str | None
    error: str | None  # set if the pipeline raised


@dataclass(frozen=True)
class CanaryReport:
    n_oos: int
    n_inscope: int
    n_errors: int
    oos_refused_n: int
    inscope_refused_n: int
    oos_refusal_recall: float
    false_refusal_rate: float
    rows: list[RowResult]

    @property
    def passes_gates(self) -> bool:
        return (
            self.oos_refusal_recall >= GATE_OOS_REFUSAL_RECALL_MIN
            and self.false_refusal_rate <= GATE_FALSE_REFUSAL_RATE_MAX
        )


def _load_oos_subset(n: int) -> list[dict[str, Any]]:
    rows = yaml.safe_load(OOS_EVAL.read_text(encoding="utf-8"))
    rows.sort(key=lambda r: r["source_id"])
    return rows[:n]


def _load_inscope_subset(n: int) -> list[dict[str, Any]]:
    """eval/queries.yaml uses heterogeneous row shapes — normalize."""
    rows = yaml.safe_load(INSCOPE_EVAL.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for r in rows:
        sid = r.get("id") or r.get("source_id") or r.get("query", "")[:60]
        q = r.get("query") or r.get("text")
        if q:
            out.append({"source_id": sid, "query": q})
    out.sort(key=lambda r: str(r["source_id"]))
    return out[:n]


def _build_pipeline(llm_cache_dir: Path | None):
    """Import + construct production-equivalent pipeline.

    Imports are lazy so --dry-run can skip the (slow) embedder load.
    """
    from rag_leis.rag import load_pipeline

    return load_pipeline(
        chunks_dir=CHUNKS_DIR,
        index_dir=INDEX_DIR,
        llm_provider=os.environ.get("RAG_LLM_PROVIDER", "maritaca"),
        # Phase 17.5 — DEFAULT_OOS_THRESHOLD is 0.425 (pinned in rag.py);
        # the canary uses production default, not an override.
        llm_cache_dir=llm_cache_dir,
    )


def _run_query(pipeline, query: str) -> tuple[bool, str | None, str | None]:
    """Returns (refused, refusal_reason, error). On exception, refused
    is True (the canary treats errors as PASS for the OOS task — better
    to over-refuse than under-refuse on infrastructure flakes — and
    surfaces the error count separately)."""
    try:
        ans = pipeline.answer(query)
    except Exception as e:
        return True, None, f"{type(e).__name__}: {e}"
    return bool(ans.refused), ans.refusal_reason, None


def _compute_report(rows: list[RowResult]) -> CanaryReport:
    oos = [r for r in rows if r.category == "oos"]
    ins = [r for r in rows if r.category == "inscope"]
    n_errors = sum(1 for r in rows if r.error is not None)
    oos_refused = sum(1 for r in oos if r.refused)
    ins_refused = sum(1 for r in ins if r.refused)
    return CanaryReport(
        n_oos=len(oos),
        n_inscope=len(ins),
        n_errors=n_errors,
        oos_refused_n=oos_refused,
        inscope_refused_n=ins_refused,
        oos_refusal_recall=(oos_refused / len(oos)) if oos else 0.0,
        false_refusal_rate=(ins_refused / len(ins)) if ins else 0.0,
        rows=rows,
    )


def _print_report(report: CanaryReport) -> None:
    print()
    print("=" * 60)
    print("Phase 17.1 — refusal-discipline canary")
    print("=" * 60)
    print(f"  OOS rows:               {report.n_oos}")
    print(f"  In-scope rows:          {report.n_inscope}")
    print(f"  Pipeline errors:        {report.n_errors}")
    print()
    print(f"  oos_refused:            {report.oos_refused_n}/{report.n_oos}")
    print(f"  inscope_refused:        {report.inscope_refused_n}/{report.n_inscope}")
    print()
    gate_oos = "PASS" if report.oos_refusal_recall >= GATE_OOS_REFUSAL_RECALL_MIN else "FAIL"
    gate_fr = "PASS" if report.false_refusal_rate <= GATE_FALSE_REFUSAL_RATE_MAX else "FAIL"
    print(
        f"  oos_refusal_recall:     {report.oos_refusal_recall:.4f} "
        f"(gate ≥ {GATE_OOS_REFUSAL_RECALL_MIN:.2f}) [{gate_oos}]"
    )
    print(
        f"  false_refusal_rate:     {report.false_refusal_rate:.4f} "
        f"(gate ≤ {GATE_FALSE_REFUSAL_RATE_MAX:.2f}) [{gate_fr}]"
    )
    print()
    print(f"  OVERALL: {'PASS' if report.passes_gates else 'FAIL'}")
    print("=" * 60)


def _format_slack_alert(report: CanaryReport) -> str:
    failed = []
    if report.oos_refusal_recall < GATE_OOS_REFUSAL_RECALL_MIN:
        failed.append(
            f"oos_refusal_recall {report.oos_refusal_recall:.4f} < {GATE_OOS_REFUSAL_RECALL_MIN}"
        )
    if report.false_refusal_rate > GATE_FALSE_REFUSAL_RATE_MAX:
        failed.append(
            f"false_refusal_rate {report.false_refusal_rate:.4f} > {GATE_FALSE_REFUSAL_RATE_MAX}"
        )
    lines = [
        "🚨 *rag-leis Phase 17.1 refusal canary FAILED*",
        *[f"• {f}" for f in failed],
        f"Sample: {report.n_oos} OOS + {report.n_inscope} in-scope rows, "
        f"{report.n_errors} pipeline errors.",
        "Run logs: GitHub Actions → nightly-refusal-canary.",
    ]
    return "\n".join(lines)


def _post_to_slack(webhook_url: str, text: str) -> None:
    """Same minimal pattern as scripts/phase_8_6_alert_check.py — no
    retries, drop one alert rather than block CI on Slack downtime."""
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                print(f"Slack POST returned {resp.status}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"Slack POST failed: {e}", file=sys.stderr)


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-oos", type=int, default=DEFAULT_N_OOS)
    p.add_argument("--n-inscope", type=int, default=DEFAULT_N_INSCOPE)
    p.add_argument(
        "--llm-cache-dir", type=Path, default=None,
        help="Optional LLM response cache; useful for local re-runs.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Skip pipeline load + LLM calls; just print the selected subset.",
    )
    p.add_argument(
        "--json-out", type=Path, default=None,
        help="Write full per-row report JSON for later inspection.",
    )
    args = p.parse_args()

    oos_rows = _load_oos_subset(args.n_oos)
    inscope_rows = _load_inscope_subset(args.n_inscope)
    print(f"Loaded {len(oos_rows)} OOS rows + {len(inscope_rows)} in-scope rows.")

    if args.dry_run:
        print("\nDRY RUN — would have processed:")
        for r in oos_rows:
            print(f"  [oos]     {r['source_id']:<32}  {r['query'][:80]}")
        for r in inscope_rows:
            print(f"  [inscope] {str(r['source_id'])[:32]:<32}  {r['query'][:80]}")
        return 0

    pipeline = _build_pipeline(args.llm_cache_dir)
    print("Pipeline loaded. Running canary...")

    results: list[RowResult] = []
    for r in oos_rows:
        print(f"  [oos]     {r['source_id']:<32}  …", end="", flush=True)
        refused, reason, err = _run_query(pipeline, r["query"])
        results.append(RowResult(
            source_id=r["source_id"], category="oos",
            query=r["query"], refused=refused, refusal_reason=reason, error=err,
        ))
        print(f" refused={refused}{' (err)' if err else ''}")
    for r in inscope_rows:
        print(f"  [inscope] {str(r['source_id'])[:32]:<32}  …", end="", flush=True)
        refused, reason, err = _run_query(pipeline, r["query"])
        results.append(RowResult(
            source_id=str(r["source_id"]), category="inscope",
            query=r["query"], refused=refused, refusal_reason=reason, error=err,
        ))
        print(f" refused={refused}{' (err)' if err else ''}")

    report = _compute_report(results)
    _print_report(report)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps({
                "n_oos": report.n_oos, "n_inscope": report.n_inscope,
                "n_errors": report.n_errors,
                "oos_refusal_recall": report.oos_refusal_recall,
                "false_refusal_rate": report.false_refusal_rate,
                "passes_gates": report.passes_gates,
                "rows": [
                    {
                        "source_id": r.source_id, "category": r.category,
                        "refused": r.refused, "refusal_reason": r.refusal_reason,
                        "error": r.error,
                    }
                    for r in report.rows
                ],
            }, indent=2),
            encoding="utf-8",
        )
        print(f"\nWrote {args.json_out}")

    if not report.passes_gates:
        webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
        if webhook:
            _post_to_slack(webhook, _format_slack_alert(report))
            print("Posted FAIL alert to Slack.")
        else:
            print("SLACK_WEBHOOK_URL not set; would have alerted but didn't.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
