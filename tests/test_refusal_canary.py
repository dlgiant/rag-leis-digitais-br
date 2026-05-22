"""Phase 17.1 — tests for the refusal-discipline canary script.

Pure unit tests on the pure-Python helpers (subset loading, metric
computation, gate logic, Slack message formatting). No pipeline
construction, no LLM calls — the live behavior is covered by the
GHA workflow itself, which acts as its own integration test.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CANARY_PATH = PROJECT_ROOT / "scripts" / "phase_17_1_refusal_canary.py"


@pytest.fixture(scope="module")
def canary():
    """Import the canary script as a module. It's under `scripts/`
    which isn't a Python package, so we load it directly via spec."""
    spec = importlib.util.spec_from_file_location("phase_17_1_refusal_canary", _CANARY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase_17_1_refusal_canary"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Subset loading — deterministic + bounded
# ---------------------------------------------------------------------------


def test_oos_subset_is_sorted_and_capped(canary):
    """Same N rows every night → drift attributable to model, not sampling."""
    rows_3 = canary._load_oos_subset(3)
    rows_5 = canary._load_oos_subset(5)
    assert len(rows_3) == 3
    assert len(rows_5) == 5
    # The 3-row selection must be a prefix of the 5-row selection.
    assert [r["source_id"] for r in rows_3] == [r["source_id"] for r in rows_5[:3]]
    # Sorted ascending by source_id.
    ids = [r["source_id"] for r in rows_5]
    assert ids == sorted(ids)


def test_inscope_subset_normalizes_heterogeneous_rows(canary):
    """eval/queries.yaml rows use multiple shapes (`id`, no `id`, …);
    the helper must return uniform {source_id, query} dicts."""
    rows = canary._load_inscope_subset(5)
    assert len(rows) <= 5
    for r in rows:
        assert "source_id" in r and r["source_id"]
        assert "query" in r and isinstance(r["query"], str) and r["query"]


# ---------------------------------------------------------------------------
# Report computation
# ---------------------------------------------------------------------------


def _r(canary, sid, cat, refused, err=None):
    return canary.RowResult(
        source_id=sid, category=cat, query="…",
        refused=refused, refusal_reason="cosine fast-path" if refused else None,
        error=err,
    )


def test_compute_report_happy_path(canary):
    """20 OOS, 11 refused = 0.55 recall; 10 in-scope, 0 refused = 0.0 fr."""
    rows = (
        [_r(canary, f"oos-{i}", "oos", refused=(i < 11)) for i in range(20)]
        + [_r(canary, f"in-{i}", "inscope", refused=False) for i in range(10)]
    )
    rep = canary._compute_report(rows)
    assert rep.n_oos == 20
    assert rep.n_inscope == 10
    assert rep.oos_refused_n == 11
    assert rep.inscope_refused_n == 0
    assert rep.oos_refusal_recall == pytest.approx(0.55)
    assert rep.false_refusal_rate == 0.0
    assert rep.passes_gates is True


def test_compute_report_fails_on_low_oos_recall(canary):
    """20 OOS, 10 refused = 0.50 < 0.55 → FAIL."""
    rows = (
        [_r(canary, f"oos-{i}", "oos", refused=(i < 10)) for i in range(20)]
        + [_r(canary, f"in-{i}", "inscope", refused=False) for i in range(10)]
    )
    rep = canary._compute_report(rows)
    assert rep.oos_refusal_recall == 0.5
    assert rep.passes_gates is False


def test_compute_report_fails_on_high_false_refusal(canary):
    """In-scope refusals above 2% → FAIL even if OOS recall is great."""
    rows = (
        [_r(canary, f"oos-{i}", "oos", refused=True) for i in range(20)]  # 100% recall
        + [_r(canary, "in-1", "inscope", refused=True)]  # 1/10 = 10% fr
        + [_r(canary, f"in-{i}", "inscope", refused=False) for i in range(2, 11)]
    )
    rep = canary._compute_report(rows)
    assert rep.oos_refusal_recall == 1.0
    assert rep.false_refusal_rate == pytest.approx(0.1)
    assert rep.passes_gates is False


def test_compute_report_counts_errors(canary):
    """Pipeline errors are surfaced separately + still count toward
    the OOS refusal (defensive — errored OOS rows are PASS-like)."""
    rows = (
        [_r(canary, f"oos-err-{i}", "oos", refused=True, err="OOM") for i in range(2)]
        + [_r(canary, f"oos-ok-{i}", "oos", refused=True) for i in range(18)]
        + [_r(canary, f"in-{i}", "inscope", refused=False) for i in range(10)]
    )
    rep = canary._compute_report(rows)
    assert rep.n_errors == 2
    assert rep.oos_refused_n == 20
    assert rep.passes_gates is True


# ---------------------------------------------------------------------------
# Gate constants — guard against accidental drift from the roadmap
# ---------------------------------------------------------------------------


def test_gate_constants_match_roadmap(canary):
    """Phase 16-19 roadmap line 48 pins these values. Drifting them
    silently would mean the canary measures something other than the
    documented contract — this test catches the drift."""
    assert canary.GATE_OOS_REFUSAL_RECALL_MIN == 0.55
    assert canary.GATE_FALSE_REFUSAL_RATE_MAX == 0.02


# ---------------------------------------------------------------------------
# Slack alert formatting
# ---------------------------------------------------------------------------


def test_slack_message_lists_failing_gates(canary):
    rows = (
        [_r(canary, f"oos-{i}", "oos", refused=(i < 5)) for i in range(20)]  # 25% recall
        + [_r(canary, f"in-{i}", "inscope", refused=True)
           for i in range(3)]  # 30% false-refusal
        + [_r(canary, f"in-ok-{i}", "inscope", refused=False)
           for i in range(7)]
    )
    rep = canary._compute_report(rows)
    msg = canary._format_slack_alert(rep)
    # Both failure modes called out.
    assert "oos_refusal_recall" in msg
    assert "false_refusal_rate" in msg
    # Sample-size signal included so an on-call can sanity-check the
    # alert vs the corpus state before chasing a non-issue.
    assert "20 OOS" in msg
    assert "10 in-scope" in msg


def test_slack_message_only_lists_failing_gates(canary):
    """If only OOS recall fails, the message should NOT call out the
    false-refusal gate as a failure (it's passing)."""
    rows = (
        [_r(canary, f"oos-{i}", "oos", refused=(i < 5)) for i in range(20)]  # 25%
        + [_r(canary, f"in-{i}", "inscope", refused=False) for i in range(10)]
    )
    rep = canary._compute_report(rows)
    msg = canary._format_slack_alert(rep)
    assert "oos_refusal_recall" in msg
    # Only one bullet — the false-refusal gate passed.
    assert msg.count("•") == 1
