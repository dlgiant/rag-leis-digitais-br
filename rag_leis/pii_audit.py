"""PII redaction audit log — append-only, no PII stored.

LGPD compliance for the system itself: when the redactor processes a
query, write a single-line JSON record so the operations team can
later audit "how many queries had PII?", "which types?", "did the
redactor ever crash?" without retaining the original query content.

Design:
  - Append-only JSONL at `data/audit/pii-redactions.jsonl` (gitignored)
  - One record per `redact()` call (caller invokes `write_audit(rq)`)
  - Record schema (forward-compatible):
        timestamp           ISO 8601 with timezone
        original_hash       SHA-256 of original (NOT recoverable to PII)
        redacted_text       the placeholder-substituted text
        pii_types_found     sorted list
        n_matches           total matches across all types
        schema_version      1   (bump when adding fields)
  - Production add: SQLite with indexed timestamp is faster for query but
    JSONL keeps the operations story simple (just `grep` + `jq`).

The audit log is the artifact LGPD art. 37 mentions — registro das
operações de tratamento. Storing ONLY the hash + counts satisfies
data minimization (art. 6, III).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rag_leis.pii import RedactedQuery

SCHEMA_VERSION = 1


def audit_record(rq: RedactedQuery, when: datetime | None = None) -> dict:
    """Build the dict that gets serialized — exposed for tests + introspection.

    `when=None` uses datetime.now(timezone.utc); callers can inject a
    fixed timestamp for deterministic tests."""
    ts = (when or datetime.now(UTC)).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": ts,
        "original_hash": rq.original_hash,
        "redacted_text": rq.redacted_text,
        "pii_types_found": sorted(rq.pii_types_found),
        "n_matches": len(rq.matches),
    }


def write_audit(rq: RedactedQuery, log_path: Path, when: datetime | None = None) -> None:
    """Append a JSON line to `log_path`. Creates the parent dir if missing.

    Atomic enough for single-writer use (CPython open() with append mode
    on Linux/POSIX writes single-line-sized payloads atomically). For
    multi-writer production deploys (Phase 7+), this should move to a
    proper logging backend (syslog, fluent-bit, etc.); for v0 a JSONL
    file is correct.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = audit_record(rq, when=when)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


def read_audit(log_path: Path) -> list[dict]:
    """Load all records from a JSONL file. For analysis / reporting.
    Returns empty list if the file doesn't exist."""
    if not log_path.exists():
        return []
    out: list[dict] = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out
