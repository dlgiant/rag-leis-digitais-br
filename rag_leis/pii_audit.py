"""PII redaction audit log — append-only, no PII stored.

LGPD compliance for the system itself: when the redactor processes a
query, write a single record so the operations team can later audit
"how many queries had PII?", "which types?", "did the redactor ever
crash?" without retaining the original query content.

Phase 11.2.1 storage refactor — the audit log was previously a JSONL
file at `data/audit/pii-redactions.jsonl`. On Fly's ephemeral disk
that meant the log was silently wiped on every redeploy. Now:

  - If `rag_leis.db` pool is initialized (production w/ DATABASE_URL):
    INSERT into `pii_audit_log` table.
  - Else (eval CLI / tests / dev w/o DB): fall back to JSONL append
    at the `log_path` Path argument (legacy behavior).

The dispatch keeps existing call sites (`rag.py`, tests using
`tmp_path`) working unchanged. Production gains durability.

Storing ONLY the hash + counts satisfies LGPD art. 6, III (data
minimization). The audit log is the artifact LGPD art. 37 mentions —
registro das operações de tratamento.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rag_leis import db
from rag_leis.pii import RedactedQuery

SCHEMA_VERSION = 1


def audit_record(rq: RedactedQuery, when: datetime | None = None) -> dict:
    """Build the dict that gets serialized — exposed for tests + introspection.

    `when=None` uses datetime.now(UTC); callers can inject a
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
    """Persist a single audit record.

    Dispatches based on DB availability:
      - DB pool configured  → INSERT into pii_audit_log table
      - Otherwise           → append a JSON line to `log_path`

    `log_path` is still required for backwards compatibility with
    callers that don't know about the DB layer (`rag.py`, eval CLI).
    """
    record = audit_record(rq, when=when)
    if db.is_configured():
        _write_audit_to_db(record)
    else:
        _write_audit_to_file(record, log_path)


def read_audit(log_path: Path) -> list[dict]:
    """Load all records. Dispatches the same way as write_audit:
    DB if configured, file otherwise. Returns empty list if neither
    source has data.
    """
    if db.is_configured():
        return _read_audit_from_db()
    return _read_audit_from_file(log_path)


# ---------------------------------------------------------------------------
# Postgres backend (Phase 11.2.1)
# ---------------------------------------------------------------------------


def _write_audit_to_db(record: dict) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                INSERT INTO pii_audit_log (
                    ts, schema_version, original_hash, redacted_text,
                    pii_types_found, n_matches
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
            (
                record["timestamp"],
                record["schema_version"],
                record["original_hash"],
                record["redacted_text"],
                list(record["pii_types_found"]),
                record["n_matches"],
            ),
        )


def _read_audit_from_db() -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT ts, schema_version, original_hash, redacted_text,
                       pii_types_found, n_matches
                FROM pii_audit_log
                ORDER BY ts ASC, id ASC
                """
        )
        rows = cur.fetchall()
    out: list[dict] = []
    for ts, schema_version, original_hash, redacted_text, pii_types, n_matches in rows:
        out.append({
            "schema_version": schema_version,
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "original_hash": original_hash,
            "redacted_text": redacted_text,
            "pii_types_found": list(pii_types or []),
            "n_matches": n_matches,
        })
    return out


# ---------------------------------------------------------------------------
# Legacy file backend (eval CLI / tests / dev-without-DB)
# ---------------------------------------------------------------------------


def _write_audit_to_file(record: dict, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


def _read_audit_from_file(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    out: list[dict] = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            out.append(json.loads(stripped))
    return out
