"""Phase 11.2 — Proposal storage for lawyer-review workflows.

A `Proposal` is one of three kinds:

  - `review`     — a reviewer submitted a verdict (correct / incorrect /
                   needs_followup) on an existing eval row. May include
                   suggested gold URNs or a suggested classified_type.
  - `new_row`    — the operator proposed a brand-new eval row (only the
                   operator can write these; gated upstream by the
                   operator allowlist).
  - `refinement` — Phase 11.3 only. The reviewer typed an alternate
                   phrasing and ran it through the pipeline; the result
                   is captured for later promotion to the eval set.

Proposals are append-only to `data/review/proposals.jsonl`. The
operator (you) reviews them via Phase 11.4's `scripts/
phase_11_merge_proposals.py`, which writes accepted ones into
`eval/queries.yaml` and records the proposal IDs in
`data/review/merged.jsonl` so they don't show up in the pending
queue again.

The UI / admin API NEVER write to `eval/queries.yaml` directly —
that's the operator's PR-style git workflow.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROPOSALS_PATH = PROJECT_ROOT / "data" / "review" / "proposals.jsonl"
DEFAULT_MERGED_PATH = PROJECT_ROOT / "data" / "review" / "merged.jsonl"

ProposalKind = Literal["review", "new_row", "refinement"]
Verdict = Literal["correct", "incorrect", "needs_followup"]


@dataclass(frozen=True)
class Proposal:
    """A single proposal record. Fields are explicit so the JSONL is
    self-describing for the merge tool + the lawyer-review checklist."""

    # Identity
    id: str  # uuid4 hex; unique per proposal
    ts: str  # ISO-8601 with timezone offset

    # Authorship
    reviewer_email: str
    is_operator: bool

    # Discriminator
    kind: ProposalKind

    # Target — for `review` + `refinement`, references an existing eval row
    query_id: str | None = None

    # Review-specific
    verdict: Verdict | None = None
    notes: str = ""
    suggested_gold_urns: tuple[str, ...] = field(default_factory=tuple)
    suggested_classified_type: str | None = None

    # New-row-specific
    new_query_text: str | None = None
    new_qtype: str | None = None
    new_core_urns: tuple[str, ...] = field(default_factory=tuple)
    new_supporting_urns: tuple[str, ...] = field(default_factory=tuple)

    # Refinement-specific (Phase 11.3)
    refined_query_text: str | None = None


# ---------------------------------------------------------------------------
# Append (thread-safe)
# ---------------------------------------------------------------------------


# A single in-process lock guards append writes. JSONL is append-only +
# line-terminated, so concurrent appends from different processes can
# interleave at line boundaries safely — but within ONE process, two
# threads writing simultaneously could interleave bytes mid-line.
_append_lock = threading.Lock()


def _proposal_path() -> Path:
    """Return the active proposals path, honoring RAG_PROPOSALS_PATH env."""
    override = os.environ.get("RAG_PROPOSALS_PATH")
    return Path(override) if override else DEFAULT_PROPOSALS_PATH


def _merged_path() -> Path:
    """Return the active merged-IDs path, honoring RAG_MERGED_PATH env."""
    override = os.environ.get("RAG_MERGED_PATH")
    return Path(override) if override else DEFAULT_MERGED_PATH


def new_proposal_id() -> str:
    """uuid4 hex — short, unique, no PII."""
    return uuid.uuid4().hex


def utc_now_iso() -> str:
    """ISO-8601 timestamp with UTC offset. Used as the 'ts' field."""
    return datetime.now(UTC).isoformat()


def to_jsonable(p: Proposal) -> dict:
    """Convert a Proposal into a JSON-serializable dict.

    Tuples become lists (JSON has no tuple). None fields stay None.
    """
    d = asdict(p)
    # asdict already collapses dataclass nesting; convert tuples → lists
    for k, v in list(d.items()):
        if isinstance(v, tuple):
            d[k] = list(v)
    return d


def append_proposal(p: Proposal, *, path: Path | None = None) -> None:
    """Append one Proposal as a JSONL line. Creates parent directory
    if missing. Thread-safe via process-local lock."""
    target = path or _proposal_path()
    line = json.dumps(to_jsonable(p), ensure_ascii=False, sort_keys=True) + "\n"
    with _append_lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(line)


# ---------------------------------------------------------------------------
# Read (for the operator's queue page + merge tool)
# ---------------------------------------------------------------------------


def load_all_proposals(*, path: Path | None = None) -> list[Proposal]:
    """Load every proposal from the JSONL. Order preserved (oldest
    first). Missing file → empty list."""
    target = path or _proposal_path()
    if not target.exists():
        return []
    out: list[Proposal] = []
    with target.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as e:
                # Skip malformed lines — log to stderr in production.
                # Better to lose one corrupted proposal than fail the
                # whole queue.
                import sys
                print(
                    f"proposals: skipping malformed line {line_no} in "
                    f"{target}: {e}",
                    file=sys.stderr,
                )
                continue
            out.append(_from_dict(obj))
    return out


def load_merged_ids(*, path: Path | None = None) -> set[str]:
    """Return the set of proposal IDs already merged into eval/queries.yaml.
    Missing file → empty set."""
    target = path or _merged_path()
    if not target.exists():
        return set()
    ids: set[str] = set()
    with target.open("r", encoding="utf-8") as f:
        for raw in f:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            pid = obj.get("id")
            if isinstance(pid, str):
                ids.add(pid)
    return ids


def load_pending_proposals(
    *,
    path: Path | None = None,
    merged_path: Path | None = None,
) -> list[Proposal]:
    """Proposals not yet in `merged.jsonl`. Useful for the operator's
    queue page + the merge tool's CLI prompts."""
    all_p = load_all_proposals(path=path)
    merged = load_merged_ids(path=merged_path)
    return [p for p in all_p if p.id not in merged]


def _from_dict(obj: dict) -> Proposal:
    """Inverse of to_jsonable — reconstruct a Proposal from a JSONL row.

    Defensive: any missing optional field uses the dataclass default.
    Tuples get re-tupled from lists."""
    return Proposal(
        id=obj.get("id", ""),
        ts=obj.get("ts", ""),
        reviewer_email=obj.get("reviewer_email", ""),
        is_operator=bool(obj.get("is_operator", False)),
        kind=obj.get("kind", "review"),
        query_id=obj.get("query_id"),
        verdict=obj.get("verdict"),
        notes=obj.get("notes", ""),
        suggested_gold_urns=tuple(obj.get("suggested_gold_urns") or ()),
        suggested_classified_type=obj.get("suggested_classified_type"),
        new_query_text=obj.get("new_query_text"),
        new_qtype=obj.get("new_qtype"),
        new_core_urns=tuple(obj.get("new_core_urns") or ()),
        new_supporting_urns=tuple(obj.get("new_supporting_urns") or ()),
        refined_query_text=obj.get("refined_query_text"),
    )
