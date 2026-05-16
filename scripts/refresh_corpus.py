"""Orchestrator for Phase 7: end-to-end weekly corpus refresh.

Sequence (matching study/phase-7-production-infra-plan.md §7.2):

  1. fetch_tier --tier all   → diff vs prior SHA-256s
  2. If no NEW/CHANGED docs: exit 0 (steady-state, nothing to do)
  3. parse_all_tier for affected tiers + re-apply CC filter
  4. pytest gate (must pass — catches parser regressions before re-embed)
  5. backup current index .npz/.meta.json (so we can roll back)
  6. run_eval on the default embedder × text-mode (Voyage rebuild kicks in
     here when chunk text changed; cost ~$0.50)
  7. compare new nDCG@10 to baseline in data/audit/last_eval_metrics.json
  8. if degraded > 0.02 → restore backup + exit 1 (loud failure)
     else → discard backup + persist new metrics + exit 0

This is the engine; Phase 7.3 (GitHub Actions cron) just calls this and
parses exit codes. Phase 7.4 wraps the output in a PR. Phase 7.5 adds a
post-merge smoke test against Sabiá.

Uso:
  uv run python -m scripts.refresh_corpus            # full cycle
  uv run python -m scripts.refresh_corpus --dry-run  # plan only
  uv run python -m scripts.refresh_corpus --skip-fetch   # debug from already-fetched
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from rag_leis.diff_audit import DiffEntry, append_audit_log, format_diff_summary
from rag_leis.fetch_tier import AUDIT_LOG, _fetch_one_tier
from rag_leis.corpus import TIER_1, TIER_2
from rag_leis.refresh_gate import (
    DEFAULT_NDCG_THRESHOLD,
    backup_index_files,
    discard_backups,
    is_degradation,
    load_metrics,
    metrics_now,
    restore_index_files,
    save_metrics,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "data" / "index"
METRICS_PATH = PROJECT_ROOT / "data" / "audit" / "last_eval_metrics.json"

# The pipeline's production cache key (rag.py DEFAULT_TEXT_MODE).
EMBEDDER = "voyage-3-large"
TEXT_MODE = "title+label+nav+caput+text"
INDEX_BASE = INDEX_DIR / f"{EMBEDDER}__{TEXT_MODE}.npz"


def _exit(code: int, msg: str) -> int:
    """Single exit point so logs are uniform."""
    print(f"\n[refresh_corpus] EXIT {code}: {msg}", file=sys.stderr if code else sys.stdout)
    return code


async def _fetch_all() -> list[DiffEntry]:
    """Run fetch_tier for tiers 1 and 2 (tier-3 ANPD PDFs use a separate
    pipeline; tier-4 jurisprudência is manual). Returns aggregated diffs."""
    diffs: list[DiffEntry] = []
    for tier, docs, label in [("1", TIER_1, "tier-1"), ("2", TIER_2, "tier-2")]:
        _, tier_diffs = await _fetch_one_tier(docs, label)
        diffs.extend(tier_diffs)
    return diffs


def _run(cmd: list[str], *, label: str) -> int:
    """Wrapper for shelling out. Streams output (no capture) so the operator
    sees progress in real time."""
    print(f"\n[refresh_corpus] {label}: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return proc.returncode


def _parse_eval_output(stdout: str) -> tuple[float, float, float, int] | None:
    """Extract nDCG/Recall/MRR/n_queries from run_eval stdout. Returns None
    if any field is missing (eval failed). Format is the table header lines
    from rag_leis.run_eval.

    Sample lines:
        model=voyage-3-large  text_mode=...  queries=104  k=20
          nDCG@10  : 0.7223
          Recall@20: 0.8705
          MRR@10   : 0.8040
    """
    ndcg = recall = mrr = None
    n_queries = None
    for line in stdout.splitlines():
        s = line.strip()
        if s.startswith("nDCG@10"):
            ndcg = float(s.split(":")[-1])
        elif s.startswith("Recall@20"):
            recall = float(s.split(":")[-1])
        elif s.startswith("MRR@10"):
            mrr = float(s.split(":")[-1])
        elif "queries=" in s:
            for tok in s.split():
                if tok.startswith("queries="):
                    n_queries = int(tok.split("=", 1)[1])
    if None in (ndcg, recall, mrr, n_queries):
        return None
    return ndcg, recall, mrr, n_queries  # type: ignore[return-value]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Plan only — no fetch, no parse, no embed.")
    p.add_argument("--skip-fetch", action="store_true",
                   help="Reuse existing data/raw/* (debug from a known state).")
    p.add_argument("--threshold", type=float, default=DEFAULT_NDCG_THRESHOLD,
                   help=f"nDCG@10 drop tolerance (default {DEFAULT_NDCG_THRESHOLD}).")
    args = p.parse_args()

    if args.dry_run:
        return _exit(0, "dry-run: would fetch → parse → pytest → eval → gate")

    # 1. Fetch
    if args.skip_fetch:
        print("[refresh_corpus] --skip-fetch: assuming all docs are NEW/CHANGED.")
        diffs: list[DiffEntry] = []  # caller assumes changes happened
        should_proceed = True
    else:
        print("[refresh_corpus] Step 1/6: fetching tier 1 + tier 2 ...")
        diffs = asyncio.run(_fetch_all())
        print(format_diff_summary(diffs))
        appended = append_audit_log(AUDIT_LOG, diffs)
        if appended:
            print(f"[refresh_corpus] audit log: +{appended} entries → {AUDIT_LOG.relative_to(PROJECT_ROOT)}")
        # 2. Skip if nothing changed
        should_proceed = any(d.status in ("new", "changed") for d in diffs)
        if not should_proceed:
            return _exit(0, "no diffs detected; corpus is current.")

    # 3. Parse + CC filter
    print("[refresh_corpus] Step 2/6: parsing tier 1 + tier 2 ...")
    if _run(["uv", "run", "python", "-m", "rag_leis.parse_all_tier", "--tier", "all"],
            label="parse_all_tier") != 0:
        return _exit(1, "parse_all_tier failed.")
    if _run(["uv", "run", "python", "-m", "scripts.filter_cc_personalidade"],
            label="filter_cc_personalidade") != 0:
        return _exit(1, "CC filter failed.")

    # 4. pytest gate (parser regressions, schema invariants, etc.)
    # CI compatibility: skip tests that depend on data NOT in git
    # (ANPD source PDFs are gitignored, not fetched by fetch_tier).
    # Network tests skip via @skipif when keys absent.
    print("[refresh_corpus] Step 3/6: pytest gate ...")
    if _run(
        ["uv", "run", "pytest", "-q", "-m", "not requires_anpd_pdf"],
        label="pytest",
    ) != 0:
        return _exit(1, "pytest failed; aborting BEFORE re-embed (saves $$).")

    # 5. Backup current index
    print("[refresh_corpus] Step 4/6: backing up index ...")
    backups = backup_index_files(INDEX_BASE)
    print(f"[refresh_corpus] backed up {len(backups)} cache files (.bak siblings).")

    # 6. Re-eval (Voyage rebuild triggers automatically if chunks changed)
    print("[refresh_corpus] Step 5/6: re-eval (Voyage rebuild iff chunks changed) ...")
    proc = subprocess.run(
        ["uv", "run", "python", "-m", "rag_leis.run_eval",
         "--model", EMBEDDER, "--text-mode", TEXT_MODE],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        restore_index_files(INDEX_BASE)
        return _exit(1, "run_eval failed; restored prior index.")

    parsed = _parse_eval_output(proc.stdout)
    if parsed is None:
        restore_index_files(INDEX_BASE)
        return _exit(1, "could not parse eval metrics; restored prior index.")
    ndcg, recall, mrr, n_queries = parsed
    new_metrics = metrics_now(EMBEDDER, TEXT_MODE, ndcg, recall, mrr, n_queries)

    # 7. Gate decision
    print("[refresh_corpus] Step 6/6: degradation gate ...")
    baseline = load_metrics(METRICS_PATH)
    if baseline is None:
        print("[refresh_corpus] no baseline metrics yet — seeding from this run.")
    else:
        print(f"[refresh_corpus] baseline: nDCG@10={baseline.ndcg_at_10}  "
              f"new: nDCG@10={new_metrics.ndcg_at_10}  "
              f"threshold: {args.threshold}")
    if is_degradation(baseline, new_metrics, threshold=args.threshold):
        restored = restore_index_files(INDEX_BASE)
        return _exit(
            1,
            f"DEGRADATION: nDCG@10 dropped {baseline.ndcg_at_10:.4f} → "
            f"{new_metrics.ndcg_at_10:.4f} (> {args.threshold}). "
            f"Restored {restored} cache files."
        )

    # Accept: discard backup, persist new metrics.
    discarded = discard_backups(INDEX_BASE)
    save_metrics(METRICS_PATH, new_metrics)
    print(f"[refresh_corpus] discarded {discarded} backup files.")
    print(f"[refresh_corpus] persisted new baseline → {METRICS_PATH.relative_to(PROJECT_ROOT)}")
    return _exit(0, f"refresh complete. nDCG@10={new_metrics.ndcg_at_10}  "
                    f"Recall@20={new_metrics.recall_at_20}  MRR@10={new_metrics.mrr_at_10}")


if __name__ == "__main__":
    sys.exit(main())
