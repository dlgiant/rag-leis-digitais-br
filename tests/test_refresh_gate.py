"""Tests for rag_leis.refresh_gate — gate logic for Phase 7.2 orchestrator."""

from __future__ import annotations

import json

import pytest

from rag_leis.refresh_gate import (
    DEFAULT_NDCG_THRESHOLD,
    EvalMetrics,
    backup_index_files,
    discard_backups,
    is_degradation,
    load_metrics,
    metrics_now,
    restore_index_files,
    save_metrics,
)


# ---------------------------------------------------------------------------
# Backup / restore — file lifecycle
# ---------------------------------------------------------------------------


def _seed_cache(dir_: object, stem: str = "voyage__title+text") -> object:
    """Create a fake cache family (.npz + .meta.json) with known content
    so backup/restore can roundtrip it."""
    npz = dir_ / f"{stem}.npz"
    meta = dir_ / f"{stem}.meta.json"
    npz.write_bytes(b"INDEX_v1")
    meta.write_text(json.dumps({"content_hash": "abc", "n_chunks": 10}))
    return npz


def test_backup_creates_bak_siblings(tmp_path):
    npz = _seed_cache(tmp_path)
    backups = backup_index_files(npz)
    assert len(backups) == 2  # .npz + .meta.json
    assert (tmp_path / "voyage__title+text.npz.bak").exists()
    assert (tmp_path / "voyage__title+text.meta.json.bak").exists()


def test_backup_returns_empty_when_no_cache(tmp_path):
    """First-run case: nothing to back up. Must not crash."""
    npz = tmp_path / "missing.npz"
    backups = backup_index_files(npz)
    assert backups == []


def test_restore_overwrites_corrupted_with_bak(tmp_path):
    """Simulate: backed up, then re-embed wrote garbage, then we restore."""
    npz = _seed_cache(tmp_path)
    backup_index_files(npz)
    # Re-embed wrote new (worse) content
    npz.write_bytes(b"INDEX_v2_BAD")
    (tmp_path / "voyage__title+text.meta.json").write_text(json.dumps({"content_hash": "def"}))
    # Restore
    n = restore_index_files(npz)
    assert n == 2
    assert npz.read_bytes() == b"INDEX_v1"
    # .bak should be GONE after restore (move, not copy)
    assert not (tmp_path / "voyage__title+text.npz.bak").exists()


def test_restore_is_noop_when_no_backups(tmp_path):
    npz = tmp_path / "missing.npz"
    assert restore_index_files(npz) == 0


def test_discard_backups_removes_them(tmp_path):
    npz = _seed_cache(tmp_path)
    backup_index_files(npz)
    n = discard_backups(npz)
    assert n == 2
    assert not (tmp_path / "voyage__title+text.npz.bak").exists()
    # Original cache files still intact
    assert npz.exists()


# ---------------------------------------------------------------------------
# Metrics persistence
# ---------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "sub" / "metrics.json"
    m = metrics_now("voyage-3-large", "title+x", 0.71, 0.87, 0.80, 104)
    save_metrics(p, m)
    loaded = load_metrics(p)
    assert loaded == m


def test_load_missing_returns_none(tmp_path):
    assert load_metrics(tmp_path / "absent.json") is None


def test_load_malformed_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert load_metrics(p) is None


def test_load_legacy_payload_returns_none(tmp_path):
    """Older payload without required fields → None (gate treats as
    first-run, seeds new baseline)."""
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({"ndcg_at_10": 0.7}))  # missing fields
    assert load_metrics(p) is None


# ---------------------------------------------------------------------------
# is_degradation — gate decision logic
# ---------------------------------------------------------------------------


def _make_metrics(ndcg: float, *, model: str = "voyage-3-large", mode: str = "title+x") -> EvalMetrics:
    return EvalMetrics(
        timestamp="2026-05-16T00:00:00Z",
        model=model,
        text_mode=mode,
        ndcg_at_10=ndcg,
        recall_at_20=0.87,
        mrr_at_10=0.80,
        n_queries=104,
    )


def test_first_run_is_never_degradation():
    new = _make_metrics(0.50)  # low metric, but no baseline → accept
    assert is_degradation(None, new) is False


def test_within_threshold_is_ok():
    old = _make_metrics(0.72)
    new = _make_metrics(0.71)  # -0.01 < 0.02 threshold
    assert is_degradation(old, new) is False


def test_exactly_at_threshold_is_ok():
    """Boundary: 0.72 - 0.02 = 0.70 is the cutoff. 0.70 must pass."""
    old = _make_metrics(0.72)
    new = _make_metrics(0.70)
    assert is_degradation(old, new) is False


def test_just_past_threshold_triggers():
    old = _make_metrics(0.72)
    new = _make_metrics(0.6999)
    assert is_degradation(old, new) is True


def test_improvement_is_never_degradation():
    old = _make_metrics(0.70)
    new = _make_metrics(0.85)
    assert is_degradation(old, new) is False


def test_model_change_skips_gate():
    """Different model → caches are not comparable; accept as fresh baseline.
    Prevents accidental rollback when an operator deliberately changes the
    embedder."""
    old = _make_metrics(0.72, model="voyage-3-large")
    new = _make_metrics(0.50, model="bge-m3")
    assert is_degradation(old, new) is False


def test_text_mode_change_skips_gate():
    """Same logic for text-mode change."""
    old = _make_metrics(0.72, mode="label+nav+caput+text")
    new = _make_metrics(0.50, mode="title+label+nav+caput+text")
    assert is_degradation(old, new) is False


def test_custom_threshold_respected():
    old = _make_metrics(0.72)
    new = _make_metrics(0.69)  # -0.03
    assert is_degradation(old, new, threshold=0.05) is False  # tolerates wider
    assert is_degradation(old, new, threshold=0.01) is True   # tighter trips


def test_default_threshold_is_002():
    assert DEFAULT_NDCG_THRESHOLD == 0.02


# ---------------------------------------------------------------------------
# metrics_now — factory with timestamp
# ---------------------------------------------------------------------------


def test_metrics_now_rounds_to_4_decimals():
    m = metrics_now("m", "mode", 0.71234567, 0.87654321, 0.80000001, 104)
    assert m.ndcg_at_10 == 0.7123
    assert m.recall_at_20 == 0.8765
    assert m.mrr_at_10 == 0.8


def test_metrics_now_stamps_iso_utc():
    m = metrics_now("m", "mode", 0.7, 0.8, 0.9, 10)
    assert m.timestamp.endswith("Z")  # UTC marker
    assert "T" in m.timestamp  # ISO-8601 separator
