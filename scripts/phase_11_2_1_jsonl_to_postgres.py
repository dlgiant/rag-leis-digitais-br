"""Phase 11.2.1 — one-shot migration: legacy JSONL files → Postgres.

Reads the gitignored JSONL files from `data/review/` and
`data/audit/` and INSERTs them into the new Postgres tables.
Idempotent: `ON CONFLICT DO NOTHING` on `proposals.id` and
`merged_proposals.proposal_id`; pii_audit_log uses its own
SERIAL primary key but is keyed by (timestamp, original_hash)
internally so we use that as a dedup check.

Usage:
    DATABASE_URL=postgresql://... uv run python scripts/phase_11_2_1_jsonl_to_postgres.py [--dry-run]

The script:
  1. Runs `alembic upgrade head` to ensure tables exist
  2. Imports `data/review/proposals.jsonl` → proposals table
  3. Imports `data/review/merged.jsonl` → merged_proposals table
  4. Imports `data/audit/pii-redactions.jsonl` → pii_audit_log table
  5. Reports row counts before/after

Run this once after Phase 11.2.1 deploys + the DATABASE_URL secret is
set on Fly. After successful import the operator can also delete the
local JSONL files (they're gitignored anyway).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rag_leis import db

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROPOSALS_JSONL = PROJECT_ROOT / "data" / "review" / "proposals.jsonl"
MERGED_JSONL = PROJECT_ROOT / "data" / "review" / "merged.jsonl"
PII_AUDIT_JSONL = PROJECT_ROOT / "data" / "audit" / "pii-redactions.jsonl"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                out.append(json.loads(stripped))
    return out


def _parse_ts(ts_str: str | None) -> datetime | None:
    """Forgive Z-suffix UTC marker that older JSONL used."""
    if not ts_str:
        return None
    s = ts_str.replace("Z", "+00:00") if ts_str.endswith("Z") else ts_str
    return datetime.fromisoformat(s)


def import_proposals(dry_run: bool) -> tuple[int, int]:
    rows = _load_jsonl(PROPOSALS_JSONL)
    if not rows:
        return 0, 0
    if dry_run:
        return len(rows), 0
    inserted = 0
    with db.get_conn() as conn, conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                    INSERT INTO proposals (
                        id, ts, reviewer_email, is_operator, kind,
                        query_id, verdict, notes, suggested_gold_urns, suggested_classified_type,
                        new_query_text, new_qtype, new_core_urns, new_supporting_urns,
                        refined_query_text
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s
                    )
                    ON CONFLICT (id) DO NOTHING
                    """,
                (
                    r.get("id"),
                    _parse_ts(r.get("ts")),
                    r.get("reviewer_email", ""),
                    bool(r.get("is_operator", False)),
                    r.get("kind", "review"),
                    r.get("query_id"),
                    r.get("verdict"),
                    r.get("notes", ""),
                    list(r.get("suggested_gold_urns") or []),
                    r.get("suggested_classified_type"),
                    r.get("new_query_text"),
                    r.get("new_qtype"),
                    list(r.get("new_core_urns") or []),
                    list(r.get("new_supporting_urns") or []),
                    r.get("refined_query_text"),
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
    return len(rows), inserted


def import_merged(dry_run: bool) -> tuple[int, int]:
    rows = _load_jsonl(MERGED_JSONL)
    if not rows:
        return 0, 0
    if dry_run:
        return len(rows), 0
    inserted = 0
    with db.get_conn() as conn, conn.cursor() as cur:
        for r in rows:
            pid = r.get("id")
            if not pid:
                continue
            cur.execute(
                """
                    INSERT INTO merged_proposals (proposal_id, merged_by, commit_sha)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (proposal_id) DO NOTHING
                    """,
                (pid, r.get("merged_by", "import"), r.get("commit_sha")),
            )
            if cur.rowcount > 0:
                inserted += 1
    return len(rows), inserted


def import_pii_audit(dry_run: bool) -> tuple[int, int]:
    rows = _load_jsonl(PII_AUDIT_JSONL)
    if not rows:
        return 0, 0
    if dry_run:
        return len(rows), 0
    inserted = 0
    with db.get_conn() as conn, conn.cursor() as cur:
        for r in rows:
            # No natural unique key for PII audit lines; rely on
            # (timestamp, original_hash) for dedup. Add a guard
            # subquery — INSERT only if not already present.
            cur.execute(
                """
                    INSERT INTO pii_audit_log (
                        ts, schema_version, original_hash, redacted_text,
                        pii_types_found, n_matches
                    )
                    SELECT %s, %s, %s, %s, %s, %s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pii_audit_log
                        WHERE ts = %s AND original_hash = %s
                    )
                    """,
                (
                    _parse_ts(r.get("timestamp")),
                    r.get("schema_version", 1),
                    r.get("original_hash", ""),
                    r.get("redacted_text", ""),
                    list(r.get("pii_types_found") or []),
                    r.get("n_matches", 0),
                    _parse_ts(r.get("timestamp")),
                    r.get("original_hash", ""),
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
    return len(rows), inserted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Read the JSONL files + report row counts; don't INSERT.",
    )
    args = parser.parse_args()

    if not db.database_url():
        print("ERROR: DATABASE_URL is not set. Set it via .env or env var.", file=sys.stderr)
        return 2

    db.init_pool()

    if not args.dry_run:
        # Ensure schema exists
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        command.upgrade(cfg, "head")
        print("✓ Schema up-to-date")

    p_total, p_new = import_proposals(args.dry_run)
    m_total, m_new = import_merged(args.dry_run)
    a_total, a_new = import_pii_audit(args.dry_run)

    label = "would import" if args.dry_run else "imported"
    print(f"  proposals     : {p_new}/{p_total} {label} (from {PROPOSALS_JSONL.name})")
    print(f"  merged        : {m_new}/{m_total} {label} (from {MERGED_JSONL.name})")
    print(f"  pii_audit_log : {a_new}/{a_total} {label} (from {PII_AUDIT_JSONL.name})")

    if not args.dry_run:
        print("\n✓ Import complete. The local JSONL files can be deleted")
        print("  (they're gitignored anyway; Postgres is now source of truth).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
