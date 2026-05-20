"""Diff detection + audit log for corpus updates (Phase 7.1).

When `fetch_tier` re-runs against a doc that was previously fetched, this
module decides whether the HTML actually changed. Two artifacts:

  1. SHA-256 stored in `data/metadata/<tier>/<urn>.json` under `html.sha256`
     — the canonical "current state" of each tracked doc.
  2. Append-only JSONL log at `data/audit/corpus_updates.jsonl` recording
     only doc-level *changes* (not unchanged docs — those would dominate
     the log).

The audit log is local-ephemeral (`data/audit/` is gitignored, by project
convention for PII separation from telemetry). Reproducible from
metadata SHAs + a fresh fetch. Useful for "when did MCI art.19 last
change?" debugging and for Phase 7.3 scheduler diff reports.

Pure-logic functions only — no I/O against networks, just SHA-256 over
in-memory strings and JSON/JSONL serialization.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

DiffStatus = Literal["new", "changed", "unchanged"]


# Planalto sits behind F5 Big-IP WAF, which injects a `<script id="f5_cspm">`
# anti-bot fingerprint block on every response. The script body contains a
# per-response random `f5_p` token + a timestamp-based cookie name
# (`f5avr<digits>aaaa..._cspm_`). Bytes identical, content random.
# Without stripping this before hashing, every fetch shows status="changed"
# and the diff system is useless. We strip ONLY for hashing; the raw HTML on
# disk keeps the F5 block (it's harmless at parse time — parser skips <script>).
_F5_CSPM_RE = re.compile(
    r'<script\s+id="f5_cspm">.*?</script>',
    re.IGNORECASE | re.DOTALL,
)


def _normalize_for_hash(html: str) -> str:
    """Strip non-content noise (WAF anti-bot fingerprints, etc.) so the hash
    reflects the LEGAL content, not server-side cosmetic injections.
    """
    return _F5_CSPM_RE.sub("", html)


def compute_html_sha256(html: str) -> str:
    """SHA-256 hex digest of the HTML body (UTF-8 bytes), after stripping
    known non-deterministic WAF injections.

    Hash the decoded string's UTF-8 representation, not the raw fetch
    bytes — keeps the hash stable across Planalto's mixed-encoding
    quirks (some pages declare ISO-8859-1 but the same content).

    NOTE: this hash does NOT round-trip with the file on disk
    (`data/raw/<tier>/*.html`) — the disk file keeps the F5 block, but the
    SHA reflects the normalized form. That's the right trade: hash = stable
    identity of legal content; disk file = exact server response.
    """
    return hashlib.sha256(_normalize_for_hash(html).encode("utf-8")).hexdigest()


def read_prior_sha256(meta_path: Path) -> str | None:
    """Return the SHA-256 previously recorded for this URN, or None.

    None means either (a) the doc was never fetched before, or (b) the
    metadata exists but lacks the `html.sha256` field (older metadata
    written before Phase 7.1). Both cases → status="new" for the next
    diff computation.
    """
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    html = data.get("html") or {}
    sha = html.get("sha256")
    return sha if isinstance(sha, str) else None


@dataclass(frozen=True)
class DiffEntry:
    """One row in the audit log. Captures the transition for a doc."""

    timestamp: str  # ISO-8601 UTC, e.g. "2026-05-16T15:30:00Z"
    urn: str
    status: DiffStatus
    new_sha: str
    new_bytes: int
    old_sha: str | None = None  # None when status="new"
    old_bytes: int | None = None  # None when status="new"

    @property
    def byte_delta(self) -> int | None:
        if self.old_bytes is None:
            return None
        return self.new_bytes - self.old_bytes


def make_diff_entry(
    urn: str,
    new_html: str,
    prior_sha: str | None,
    prior_bytes: int | None = None,
    *,
    timestamp: str | None = None,
) -> DiffEntry:
    """Build a DiffEntry from a freshly fetched HTML + the prior SHA."""
    new_sha = compute_html_sha256(new_html)
    new_bytes = len(new_html.encode("utf-8"))
    ts = timestamp or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if prior_sha is None:
        status: DiffStatus = "new"
    elif prior_sha == new_sha:
        status = "unchanged"
    else:
        status = "changed"
    return DiffEntry(
        timestamp=ts,
        urn=urn,
        status=status,
        new_sha=new_sha,
        new_bytes=new_bytes,
        old_sha=prior_sha,
        old_bytes=prior_bytes if status == "changed" else None,
    )


def append_audit_log(audit_path: Path, entries: list[DiffEntry]) -> int:
    """Append CHANGED + NEW entries to the JSONL audit log. Returns count
    actually written (unchanged entries are skipped to keep the log
    signal-only).

    Creates parent dir + the file if missing. Atomic per-line writes; if
    the process is killed mid-write only the not-yet-flushed lines are
    lost, never a partial line.
    """
    changes = [e for e in entries if e.status != "unchanged"]
    if not changes:
        return 0
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as f:
        for entry in changes:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    return len(changes)


def format_diff_summary(entries: list[DiffEntry]) -> str:
    """Human-readable summary of a batch of diff entries, for CLI output.

    Format:
        Diff summary (vs prior fetch):
          NEW (2):     <urn>  <new_bytes> bytes
          CHANGED (1): <urn>  <old_bytes> → <new_bytes> (+<delta>)
                       sha:   <old8>... → <new8>...
          UNCHANGED:   <N> docs
    """
    new = [e for e in entries if e.status == "new"]
    changed = [e for e in entries if e.status == "changed"]
    unchanged = [e for e in entries if e.status == "unchanged"]

    lines = ["Diff summary (vs prior fetch):"]
    if new:
        lines.append(f"  NEW ({len(new)}):")
        for e in new:
            lines.append(f"    {e.urn}  {e.new_bytes} bytes")
    if changed:
        lines.append(f"  CHANGED ({len(changed)}):")
        for e in changed:
            delta = e.byte_delta
            sign = "+" if delta and delta > 0 else ""
            lines.append(f"    {e.urn}")
            lines.append(f"      bytes: {e.old_bytes} → {e.new_bytes} ({sign}{delta})")
            old8 = (e.old_sha or "")[:8]
            new8 = e.new_sha[:8]
            lines.append(f"      sha:   {old8}... → {new8}...")
    if unchanged:
        lines.append(f"  UNCHANGED: {len(unchanged)} docs")
    if not (new or changed):
        lines.append("  (no changes detected)")
    return "\n".join(lines)
