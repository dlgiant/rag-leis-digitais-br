"""Gate logic for the corpus refresh orchestrator (Phase 7.2).

The orchestrator (`scripts/refresh_corpus.py`) calls these functions to
decide whether a newly re-embedded index is safe to keep or should be
rolled back. Pure logic + filesystem helpers; no network, no embedder.

Design contract (per study/phase-7-production-infra-plan.md §7.2):

1. **Backup before re-embed.** If anything goes wrong (pytest fail,
   eval degrade, crash mid-embed) restore the previous index from
   `.npz.bak` so production keeps serving from a known-good cache.

2. **Eval threshold.** After re-embed, compare nDCG@10 against the
   last-known baseline. If new < baseline - threshold (default 0.02),
   that's a degradation — abort and restore.

3. **Persistence.** Save accepted metrics to
   `data/audit/last_eval_metrics.json` for the next cycle's comparison.
   Schema is intentionally minimal (timestamp + model + mode + 3
   metrics). Extending is non-breaking.

NOTE: A first-run scenario has no baseline metrics file. In that case
we accept any metrics and create the baseline (callers see
`is_first_run=True`).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

# Default tolerance: an absolute drop of 0.02 in nDCG@10 is the line.
# Empirical justification: in the Phase 6.6 audit cycle, intentional gold
# cleanups + new (harder) queries produced ±0.015 swings without any model
# regression; 0.02 is just outside that natural variance band, so violations
# almost certainly indicate a real degradation rather than noise.
DEFAULT_NDCG_THRESHOLD = 0.02


@dataclass(frozen=True)
class EvalMetrics:
    """The metrics tuple the gate compares against. Stored as JSON in
    data/audit/last_eval_metrics.json after each accepted refresh."""

    timestamp: str  # ISO-8601 UTC
    model: str
    text_mode: str
    ndcg_at_10: float
    recall_at_20: float
    mrr_at_10: float
    n_queries: int


# ---------------------------------------------------------------------------
# Backup / restore — .npz + .meta.json + .sparse.pkl + .colbert.npz siblings
# ---------------------------------------------------------------------------

# The cache files for one embedder × text-mode form a small family. Backing
# up just the .npz isn't enough — the .meta.json sidecar carries the
# content-hash gate, and missing it triggers a redundant rebuild on the
# next run_eval. List sibling extensions explicitly to make this safe.
_CACHE_SIBLING_SUFFIXES = (".npz", ".meta.json", ".sparse.pkl", ".colbert.npz")


def _cache_family(base_path: Path) -> list[Path]:
    """All sibling files for one cache key (model × text-mode).

    `base_path` is the .npz path; siblings share its stem.
    """
    stem = base_path.with_suffix("")  # strip .npz
    out: list[Path] = []
    for suffix in _CACHE_SIBLING_SUFFIXES:
        p = stem.with_suffix(suffix)
        if p.exists():
            out.append(p)
    return out


def backup_index_files(base_path: Path) -> list[Path]:
    """Copy the cache family to `<file>.bak` siblings. Returns the list of
    backup paths created (empty if the cache didn't exist yet — first run)."""
    backups: list[Path] = []
    for src in _cache_family(base_path):
        dst = src.with_suffix(src.suffix + ".bak")
        shutil.copy2(src, dst)
        backups.append(dst)
    return backups


def restore_index_files(base_path: Path) -> int:
    """Move `.bak` siblings back into place, overwriting any new files.
    Returns the number of files restored. Idempotent (no-op if no .bak)."""
    count = 0
    stem = base_path.with_suffix("")
    for suffix in _CACHE_SIBLING_SUFFIXES:
        src = stem.with_suffix(suffix + ".bak")
        if src.exists():
            dst = stem.with_suffix(suffix)
            shutil.move(str(src), str(dst))
            count += 1
    return count


def discard_backups(base_path: Path) -> int:
    """Delete `.bak` siblings after a successful refresh. Returns count
    deleted."""
    count = 0
    stem = base_path.with_suffix("")
    for suffix in _CACHE_SIBLING_SUFFIXES:
        p = stem.with_suffix(suffix + ".bak")
        if p.exists():
            p.unlink()
            count += 1
    return count


# ---------------------------------------------------------------------------
# Metrics persistence + gate decision
# ---------------------------------------------------------------------------


def save_metrics(metrics_path: Path, metrics: EvalMetrics) -> None:
    """Write the accepted metrics to disk. Overwrites the previous baseline.
    Parent dir created if missing."""
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(asdict(metrics), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_metrics(metrics_path: Path) -> EvalMetrics | None:
    """Return the prior baseline or None (first run, missing file, or
    malformed payload). Caller treats None as 'accept any metrics this
    time and seed the baseline'."""
    if not metrics_path.exists():
        return None
    try:
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        return EvalMetrics(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def is_degradation(
    old: EvalMetrics | None,
    new: EvalMetrics,
    threshold: float = DEFAULT_NDCG_THRESHOLD,
) -> bool:
    """True if the new metrics are degraded enough to warrant rollback.

    First-run case (`old is None`) → always False; accept and seed
    baseline. Model/text-mode mismatch → False (different cache key,
    incomparable; treat as first run for that key).
    """
    if old is None:
        return False
    if old.model != new.model or old.text_mode != new.text_mode:
        return False
    return new.ndcg_at_10 < (old.ndcg_at_10 - threshold)


def metrics_now(
    model: str,
    text_mode: str,
    ndcg: float,
    recall: float,
    mrr: float,
    n_queries: int,
) -> EvalMetrics:
    """Build a metrics record stamped with current UTC time. Factory so
    the timestamp isn't passed at every call site."""
    return EvalMetrics(
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        model=model,
        text_mode=text_mode,
        ndcg_at_10=round(ndcg, 4),
        recall_at_20=round(recall, 4),
        mrr_at_10=round(mrr, 4),
        n_queries=n_queries,
    )
