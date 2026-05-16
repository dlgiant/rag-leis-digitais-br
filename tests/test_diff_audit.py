"""Tests for rag_leis.diff_audit — corpus diff detection + audit log.

Pure-logic. No network, no fetcher. SHA-256, status classification,
JSONL serialization, summary formatting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_leis.diff_audit import (
    DiffEntry,
    append_audit_log,
    compute_html_sha256,
    format_diff_summary,
    make_diff_entry,
    read_prior_sha256,
)


# ---------------------------------------------------------------------------
# compute_html_sha256 — deterministic, UTF-8 based
# ---------------------------------------------------------------------------


def test_sha256_is_deterministic():
    h1 = compute_html_sha256("<html>oi</html>")
    h2 = compute_html_sha256("<html>oi</html>")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest length


def test_sha256_changes_with_content():
    assert compute_html_sha256("a") != compute_html_sha256("b")


def test_sha256_handles_unicode():
    # Brazilian legal text is full of acentos; UTF-8 encoding must be
    # stable (not OS-dependent).
    h = compute_html_sha256("São Paulo — § 2º-A")
    assert len(h) == 64


def test_sha256_strips_f5_waf_block():
    """Planalto sits behind F5 Big-IP. Every response injects a
    per-request anti-bot fingerprint:

        <script id="f5_cspm">(function(){var f5_cspm={f5_p:'<RANDOM>'...})();</script>

    Two responses with identical legal content but different f5_p tokens
    MUST produce the same SHA — otherwise the diff system fires false
    'changed' on every weekly cron run.
    """
    base = "<html><body>LGPD art.7</body>"
    f5_a = '<script id="f5_cspm">(function(){var f5_cspm={f5_p:\'ABCDEF\'};})();</script>'
    f5_b = '<script id="f5_cspm">(function(){var f5_cspm={f5_p:\'ZYXWVU\'};})();</script>'
    suffix = "</html>"
    h_a = compute_html_sha256(base + f5_a + suffix)
    h_b = compute_html_sha256(base + f5_b + suffix)
    assert h_a == h_b, "F5 block must be stripped before hashing"

    # Without F5, also produces the same hash
    h_clean = compute_html_sha256(base + suffix)
    assert h_a == h_clean


def test_sha256_still_changes_on_real_content_edit():
    """The F5 strip must NOT mask actual content changes."""
    f5_block = '<script id="f5_cspm">(function(){var f5_cspm={f5_p:\'X\'};})();</script>'
    h_v1 = compute_html_sha256("<p>Art.7 original</p>" + f5_block)
    h_v2 = compute_html_sha256("<p>Art.7 com nova redação</p>" + f5_block)
    assert h_v1 != h_v2


# ---------------------------------------------------------------------------
# read_prior_sha256 — graceful absence
# ---------------------------------------------------------------------------


def test_read_prior_sha_missing_file(tmp_path):
    assert read_prior_sha256(tmp_path / "nonexistent.json") is None


def test_read_prior_sha_malformed_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert read_prior_sha256(p) is None


def test_read_prior_sha_legacy_metadata_without_sha(tmp_path):
    """Metadata written before Phase 7.1 doesn't have html.sha256.
    Returns None so the first diff entry classifies as `new`."""
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({"html": {"size_bytes": 1000}}), encoding="utf-8")
    assert read_prior_sha256(p) is None


def test_read_prior_sha_present(tmp_path):
    p = tmp_path / "ok.json"
    p.write_text(
        json.dumps({"html": {"sha256": "abc123", "size_bytes": 1000}}),
        encoding="utf-8",
    )
    assert read_prior_sha256(p) == "abc123"


# ---------------------------------------------------------------------------
# make_diff_entry — status classification + byte_delta
# ---------------------------------------------------------------------------


def test_make_diff_entry_new_no_prior():
    e = make_diff_entry("urn:test", "<html>x</html>", prior_sha=None, timestamp="2026-05-16T00:00:00Z")
    assert e.status == "new"
    assert e.old_sha is None
    assert e.old_bytes is None
    assert e.byte_delta is None
    assert e.new_sha == compute_html_sha256("<html>x</html>")


def test_make_diff_entry_unchanged_when_sha_matches():
    html = "<html>same</html>"
    sha = compute_html_sha256(html)
    e = make_diff_entry("urn:test", html, prior_sha=sha, prior_bytes=17, timestamp="2026-05-16T00:00:00Z")
    assert e.status == "unchanged"
    # When unchanged we don't carry old_bytes (it's redundant + would clutter the log)
    assert e.old_bytes is None


def test_make_diff_entry_changed_with_byte_delta():
    old_html = "<html>old</html>"
    new_html = "<html>new content here</html>"
    old_sha = compute_html_sha256(old_html)
    old_bytes = len(old_html.encode("utf-8"))
    e = make_diff_entry(
        "urn:test", new_html, prior_sha=old_sha, prior_bytes=old_bytes,
        timestamp="2026-05-16T00:00:00Z",
    )
    assert e.status == "changed"
    assert e.old_sha == old_sha
    assert e.old_bytes == old_bytes
    assert e.byte_delta == len(new_html.encode("utf-8")) - old_bytes
    assert e.byte_delta > 0  # added content


# ---------------------------------------------------------------------------
# append_audit_log — append-only JSONL, skips unchanged, creates parent dir
# ---------------------------------------------------------------------------


def test_append_audit_log_creates_parent_dir_and_file(tmp_path):
    audit = tmp_path / "nested" / "deeper" / "audit.jsonl"
    e = make_diff_entry("urn:test", "<x/>", prior_sha=None, timestamp="2026-05-16T00:00:00Z")
    n = append_audit_log(audit, [e])
    assert n == 1
    assert audit.exists()


def test_append_audit_log_skips_unchanged(tmp_path):
    audit = tmp_path / "audit.jsonl"
    html = "<x/>"
    sha = compute_html_sha256(html)
    e = make_diff_entry("urn:test", html, prior_sha=sha, prior_bytes=4, timestamp="2026-05-16T00:00:00Z")
    assert e.status == "unchanged"
    n = append_audit_log(audit, [e])
    assert n == 0
    assert not audit.exists()  # no file created when nothing to log


def test_append_audit_log_is_append_not_overwrite(tmp_path):
    audit = tmp_path / "audit.jsonl"
    e1 = make_diff_entry("urn:a", "<x/>", prior_sha=None, timestamp="2026-05-16T00:00:00Z")
    e2 = make_diff_entry("urn:b", "<y/>", prior_sha=None, timestamp="2026-05-16T00:00:01Z")
    append_audit_log(audit, [e1])
    append_audit_log(audit, [e2])
    lines = audit.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["urn"] == "urn:a"
    assert json.loads(lines[1])["urn"] == "urn:b"


def test_append_audit_log_filters_to_changed_and_new(tmp_path):
    audit = tmp_path / "audit.jsonl"
    html = "<x/>"
    sha = compute_html_sha256(html)
    new_entry = make_diff_entry("urn:new", "<n/>", prior_sha=None, timestamp="2026-05-16T00:00:00Z")
    changed_entry = make_diff_entry("urn:c", "<changed/>", prior_sha="oldsha", prior_bytes=10, timestamp="2026-05-16T00:00:00Z")
    unchanged_entry = make_diff_entry("urn:u", html, prior_sha=sha, prior_bytes=4, timestamp="2026-05-16T00:00:00Z")
    n = append_audit_log(audit, [new_entry, changed_entry, unchanged_entry])
    assert n == 2  # unchanged excluded
    lines = audit.read_text(encoding="utf-8").strip().split("\n")
    urns = {json.loads(line)["urn"] for line in lines}
    assert urns == {"urn:new", "urn:c"}


# ---------------------------------------------------------------------------
# format_diff_summary — CLI output
# ---------------------------------------------------------------------------


def test_format_summary_no_changes():
    html = "<x/>"
    sha = compute_html_sha256(html)
    entries = [make_diff_entry(f"urn:{i}", html, prior_sha=sha, prior_bytes=4) for i in range(3)]
    out = format_diff_summary(entries)
    assert "UNCHANGED: 3" in out
    assert "(no changes detected)" in out


def test_format_summary_mixed():
    entries = [
        make_diff_entry("urn:new1", "<n/>", prior_sha=None),
        make_diff_entry("urn:c1", "<new-body/>", prior_sha="oldsha", prior_bytes=10),
        make_diff_entry("urn:u1", "<x/>", prior_sha=compute_html_sha256("<x/>"), prior_bytes=4),
    ]
    out = format_diff_summary(entries)
    assert "NEW (1)" in out
    assert "CHANGED (1)" in out
    assert "UNCHANGED: 1" in out
    assert "urn:new1" in out
    assert "urn:c1" in out


def test_format_summary_shows_byte_delta_sign():
    """Negative deltas (shrinking content) get no '+' prefix."""
    e_grew = make_diff_entry("urn:grew", "<longer/>" * 10, prior_sha="x", prior_bytes=10)
    e_shrunk = make_diff_entry("urn:shrunk", "x", prior_sha="x", prior_bytes=1000)
    out_grew = format_diff_summary([e_grew])
    out_shrunk = format_diff_summary([e_shrunk])
    assert "(+" in out_grew  # positive delta has + sign
    assert "(-" in out_shrunk  # negative delta has - (from the int itself)


# ---------------------------------------------------------------------------
# DiffEntry — dataclass invariants
# ---------------------------------------------------------------------------


def test_diff_entry_is_frozen_dataclass():
    e = DiffEntry(
        timestamp="2026-05-16T00:00:00Z",
        urn="urn:x",
        status="new",
        new_sha="abc",
        new_bytes=1,
    )
    with pytest.raises(Exception):  # frozen dataclass raises FrozenInstanceError
        e.urn = "mutated"  # type: ignore[misc]
