"""Tests for the PII audit log — JSONL append behavior + record schema.

Critical invariants:
  - Record never contains the original PII (only hash + redacted text)
  - JSONL append-only (never truncates)
  - Multiple writes accumulate
  - Schema version present (forward-compat)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from rag_leis.pii import redact
from rag_leis.pii_audit import (
    SCHEMA_VERSION,
    audit_record,
    read_audit,
    write_audit,
)


def test_audit_record_schema():
    rq = redact("CPF 123.456.789-00 do João")
    rec = audit_record(rq, when=datetime(2026, 5, 15, tzinfo=UTC))
    assert rec["schema_version"] == SCHEMA_VERSION
    assert rec["timestamp"] == "2026-05-15T00:00:00+00:00"
    assert rec["original_hash"] == rq.original_hash
    assert rec["redacted_text"] == rq.redacted_text
    assert rec["pii_types_found"] == ["cpf"]
    assert rec["n_matches"] == 1


def test_audit_record_no_pii_leak():
    """The record MUST NOT contain the original PII tokens.

    This is the load-bearing test: if it ever fails, the audit log
    itself becomes an LGPD violation."""
    rq = redact("CPF 123.456.789-00 e email joao@x.com")
    rec = audit_record(rq)
    rec_json = json.dumps(rec, ensure_ascii=False)
    assert "123.456.789-00" not in rec_json
    assert "joao@x.com" not in rec_json
    # But redacted_text WITH placeholders IS allowed (and present)
    assert "[CPF#1]" in rec_json
    assert "[EMAIL#1]" in rec_json


def test_write_audit_creates_jsonl(tmp_path):
    log = tmp_path / "audit.jsonl"
    rq = redact("CPF 111.111.111-11")
    write_audit(rq, log)
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    # Single line
    assert content.count("\n") == 1
    record = json.loads(content.strip())
    assert record["original_hash"] == rq.original_hash


def test_write_audit_appends_not_truncates(tmp_path):
    log = tmp_path / "audit.jsonl"
    write_audit(redact("CPF 111.111.111-11"), log)
    write_audit(redact("email a@b.com"), log)
    write_audit(redact("plain legal query"), log)
    records = read_audit(log)
    assert len(records) == 3
    # Different hashes → records preserved in order
    hashes = [r["original_hash"] for r in records]
    assert len(set(hashes)) == 3


def test_write_audit_creates_parent_dir(tmp_path):
    """Defensive: log_path's parent might not exist on first run."""
    log = tmp_path / "deep" / "nested" / "audit.jsonl"
    assert not log.parent.exists()
    write_audit(redact("test"), log)
    assert log.exists()


def test_read_audit_handles_missing_file(tmp_path):
    """Fresh checkout, no log yet."""
    log = tmp_path / "never-existed.jsonl"
    assert read_audit(log) == []


def test_read_audit_skips_blank_lines(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text(
        '{"schema_version":1,"timestamp":"2026-05-15T00:00:00+00:00","original_hash":"abc","redacted_text":"x","pii_types_found":[],"n_matches":0}\n'
        '\n'
        '{"schema_version":1,"timestamp":"2026-05-15T00:01:00+00:00","original_hash":"def","redacted_text":"y","pii_types_found":[],"n_matches":0}\n',
        encoding="utf-8",
    )
    assert len(read_audit(log)) == 2


def test_audit_record_with_no_pii():
    """Clean legal query — record still emits (for telemetry on coverage)."""
    rq = redact("o que é dado pessoal?")
    rec = audit_record(rq)
    assert rec["n_matches"] == 0
    assert rec["pii_types_found"] == []
    assert rec["redacted_text"] == "o que é dado pessoal?"


def test_record_pii_types_sorted_deterministic():
    """Sorted list for stable diffs in `git log`-style log inspection."""
    rq = redact("email a@b.com CPF 111.111.111-11 fone (11) 99999-8888")
    rec = audit_record(rq)
    # Sorted alphabetically: cpf, email, phone
    assert rec["pii_types_found"] == sorted(rec["pii_types_found"])
    assert "cpf" in rec["pii_types_found"]
    assert "email" in rec["pii_types_found"]
    assert "phone" in rec["pii_types_found"]
