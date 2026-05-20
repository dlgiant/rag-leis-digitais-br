"""Phase 8.6 — Tests for the Slack alert check script.

Validates that compute_metrics + check_thresholds correctly identify
each threshold breach from synthetic JSON log events. The Slack POST
is mocked so the suite doesn't hit Slack.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from scripts.phase_8_6_alert_check import (
    AUTH_FAILURE_PER_HR,
    COST_MEAN_USD_1H,
    MIN_REQUESTS_FOR_PERCENTILE,
    P95_LATENCY_MS_5MIN,
    check_thresholds,
    compute_metrics,
    extract_json_events,
    format_alert,
    post_to_slack,
)

NOW = datetime(2026, 5, 20, 16, 0, 0, tzinfo=UTC)


def _ts(minutes_ago: float) -> str:
    """Build an ISO timestamp `minutes_ago` minutes before NOW."""
    t = NOW - timedelta(minutes=minutes_ago)
    return t.isoformat().replace("+00:00", "Z")


def _request_completed(minutes_ago: float, latency_ms: float, status: int = 200) -> dict:
    return {
        "event": "request.completed",
        "method": "POST",
        "path": "/v1/ask",
        "status_code": status,
        "latency_ms": latency_ms,
        "request_id": f"req-{minutes_ago}",
        "timestamp": _ts(minutes_ago),
    }


def _pipeline_answered(minutes_ago: float, cost: float) -> dict:
    return {
        "event": "pipeline.answered",
        "query_length": 41,
        "classified_type": "definicao",
        "n_citations": 4,
        "refused": False,
        "cost_estimate_usd": cost,
        "llm_calls": 3,
        "pipeline_latency_ms": 9200.0,
        "request_id": f"ans-{minutes_ago}",
        "timestamp": _ts(minutes_ago),
    }


def _auth_failed(minutes_ago: float, ip: str = "203.0.113.42") -> dict:
    return {
        "event": "auth.failed",
        "reason": "invalid-key",
        "api_key_prefix": "rag_bad1",
        "client_ip": ip,
        "request_id": f"auth-{minutes_ago}",
        "timestamp": _ts(minutes_ago),
    }


# ---------------------------------------------------------------------
# extract_json_events
# ---------------------------------------------------------------------


def test_extract_json_events_finds_app_lines():
    """Fly log lines look like '<timestamp> app[<id>] <region> [info]{...}'.
    The function should pull out only the {...} portion."""
    fly_lines = [
        '2026-05-20T16:00:00Z app[d8946d] gru [info]{"event":"request.received","request_id":"abc","timestamp":"2026-05-20T16:00:00Z"}',
        "Fly platform message that's not JSON",
        '2026-05-20T16:00:01Z app[d8946d] gru [info]{"event":"request.completed","status_code":200,"latency_ms":250.0,"timestamp":"2026-05-20T16:00:01Z","path":"/v1/ask"}',
        "uvicorn: Started server process",
    ]
    events = extract_json_events(fly_lines)
    assert len(events) == 2
    assert events[0]["event"] == "request.received"
    assert events[1]["event"] == "request.completed"


def test_extract_json_events_skips_malformed():
    """Lines with { but unparseable JSON should be silently dropped."""
    fly_lines = [
        '2026-05-20T16:00:00Z app[x] gru [info]{not valid json',
        '2026-05-20T16:00:01Z app[x] gru [info]"just a string"',
        '2026-05-20T16:00:02Z app[x] gru [info]{"event":"ok","timestamp":"t"}',
    ]
    events = extract_json_events(fly_lines)
    assert len(events) == 1
    assert events[0]["event"] == "ok"


# ---------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------


def test_compute_metrics_empty():
    m = compute_metrics([], now=NOW)
    assert m["n_completed_5m"] == 0
    assert m["latency_p50_ms"] == 0.0
    assert m["error_rate_5m"] == 0.0
    assert m["cost_mean_usd_1h"] == 0.0


def test_compute_metrics_excludes_old_events():
    """Events outside the 5min/1h windows should not be counted."""
    events = [
        _request_completed(minutes_ago=3, latency_ms=200),   # in 5m window
        _request_completed(minutes_ago=10, latency_ms=99999),  # outside 5m
        _pipeline_answered(minutes_ago=30, cost=0.005),       # in 1h window
        _pipeline_answered(minutes_ago=90, cost=999.0),       # outside 1h
    ]
    m = compute_metrics(events, now=NOW)
    assert m["n_completed_5m"] == 1
    assert m["latency_p50_ms"] == 200.0   # the only sample
    assert m["n_pipeline_answered_1h"] == 1
    assert m["cost_mean_usd_1h"] == 0.005


def test_compute_metrics_error_rate():
    events = [
        _request_completed(minutes_ago=1, latency_ms=200, status=200),
        _request_completed(minutes_ago=2, latency_ms=200, status=200),
        _request_completed(minutes_ago=3, latency_ms=200, status=500),
        _request_completed(minutes_ago=4, latency_ms=200, status=503),
    ]
    m = compute_metrics(events, now=NOW)
    assert m["n_completed_5m"] == 4
    assert m["n_errors_5m"] == 2
    assert m["error_rate_5m"] == 0.5


def test_compute_metrics_auth_failures_grouped_by_ip():
    events = [
        _auth_failed(minutes_ago=5, ip="203.0.113.1"),
        _auth_failed(minutes_ago=10, ip="203.0.113.1"),
        _auth_failed(minutes_ago=15, ip="203.0.113.1"),
        _auth_failed(minutes_ago=20, ip="198.51.100.7"),
    ]
    m = compute_metrics(events, now=NOW)
    assert m["auth_failed_total_1h"] == 4
    assert m["auth_failed_top_ip"] == "203.0.113.1"
    assert m["auth_failed_top_count"] == 3


# ---------------------------------------------------------------------
# check_thresholds — happy path
# ---------------------------------------------------------------------


def test_no_breach_returns_empty():
    """Sane metrics → empty breaches list."""
    events = [_request_completed(minutes_ago=i * 0.1, latency_ms=500) for i in range(20)]
    events += [_pipeline_answered(minutes_ago=i, cost=0.005) for i in range(60)]
    m = compute_metrics(events, now=NOW)
    breaches = check_thresholds(m)
    assert breaches == []


# ---------------------------------------------------------------------
# check_thresholds — per-rule breach
# ---------------------------------------------------------------------


def test_p95_latency_breach_fires():
    """≥ MIN_REQUESTS_FOR_PERCENTILE slow requests in last 5 min → p95 alert."""
    n = MIN_REQUESTS_FOR_PERCENTILE
    events = [
        _request_completed(minutes_ago=i * 0.1, latency_ms=P95_LATENCY_MS_5MIN + 5_000)
        for i in range(n)
    ]
    m = compute_metrics(events, now=NOW)
    breaches = check_thresholds(m)
    assert any(b["name"] == "latency_p95_5m" for b in breaches)
    assert any(b["name"] == "latency_p50_5m" for b in breaches)  # also fires since p50 = p95 here


def test_p95_latency_under_min_sample_does_NOT_fire():
    """Only one slow request → don't alert (noisy)."""
    events = [_request_completed(minutes_ago=1, latency_ms=999_999)]
    m = compute_metrics(events, now=NOW)
    breaches = check_thresholds(m)
    assert not any(b["name"].startswith("latency_") for b in breaches)


def test_error_rate_breach_fires():
    """5+ requests with > 2% errors → alert."""
    # 10 requests, 3 errors → 30% error rate, well above 2% threshold.
    events = [_request_completed(minutes_ago=i * 0.1, latency_ms=500, status=200) for i in range(7)]
    events += [_request_completed(minutes_ago=i * 0.1, latency_ms=500, status=500) for i in range(3)]
    m = compute_metrics(events, now=NOW)
    breaches = check_thresholds(m)
    assert any(b["name"] == "error_rate_5m" for b in breaches)


def test_error_rate_under_min_sample_does_NOT_fire():
    """Single error in 4-request window → don't alert."""
    events = [_request_completed(minutes_ago=1, latency_ms=500, status=200) for _ in range(3)]
    events += [_request_completed(minutes_ago=1, latency_ms=500, status=500)]
    m = compute_metrics(events, now=NOW)
    breaches = check_thresholds(m)
    assert not any(b["name"] == "error_rate_5m" for b in breaches)


def test_cost_breach_fires():
    """Mean cost per query > $0.015 in last hour → alert.
    No min-sample requirement — one runaway query IS the signal."""
    events = [
        _pipeline_answered(minutes_ago=i, cost=COST_MEAN_USD_1H + 0.01) for i in range(5)
    ]
    m = compute_metrics(events, now=NOW)
    breaches = check_thresholds(m)
    assert any(b["name"] == "cost_mean_1h" for b in breaches)


def test_auth_failure_breach_fires():
    """> 10 auth.failed from one IP in last hour → alert."""
    events = [_auth_failed(minutes_ago=i, ip="203.0.113.42") for i in range(AUTH_FAILURE_PER_HR + 1)]
    m = compute_metrics(events, now=NOW)
    breaches = check_thresholds(m)
    assert any(b["name"] == "auth_failed_concentration" for b in breaches)


def test_auth_failure_concentration_top_ip_only():
    """If failures are spread across many IPs, no single IP crosses
    the threshold → no alert. The signal is concentration, not volume."""
    events = []
    for ip_num in range(20):
        events.append(_auth_failed(minutes_ago=10, ip=f"203.0.113.{ip_num}"))
    m = compute_metrics(events, now=NOW)
    breaches = check_thresholds(m)
    assert not any(b["name"] == "auth_failed_concentration" for b in breaches)


# ---------------------------------------------------------------------
# format_alert + Slack mock
# ---------------------------------------------------------------------


def test_format_alert_includes_all_breaches():
    breaches = [
        {"name": "latency_p95_5m", "value": "22.4s", "threshold": "> 20s",
         "msg": "p95 latency 22.4s over last 5 min (12 req)"},
        {"name": "cost_mean_1h", "value": "$0.025", "threshold": "> $0.015",
         "msg": "mean cost/query $0.025 over last 1h (50 answered, total $1.25)"},
    ]
    metrics = {"n_completed_5m": 12, "n_pipeline_answered_1h": 50}
    text = format_alert(breaches, metrics, app="rag-leis-digitais-br")
    assert "rag-leis 8.6 alert" in text
    assert "latency_p95_5m" in text
    assert "cost_mean_1h" in text
    assert "fly.io/apps/rag-leis-digitais-br/monitoring" in text


@patch("scripts.phase_8_6_alert_check.urllib.request.urlopen")
def test_post_to_slack_sends_json_body(mock_urlopen):
    """The Slack POST must send JSON content-type and a `text` field."""
    mock_urlopen.return_value.__enter__.return_value.status = 200
    post_to_slack("https://hooks.slack.com/services/T/B/xxx", "test message")
    # Verify the request that was passed to urlopen
    req = mock_urlopen.call_args[0][0]
    assert req.get_method() == "POST"
    assert req.get_header("Content-type") == "application/json"
    import json
    body = json.loads(req.data.decode("utf-8"))
    assert body == {"text": "test message"}


@patch("scripts.phase_8_6_alert_check.urllib.request.urlopen")
def test_post_to_slack_swallows_errors(mock_urlopen):
    """Slack outage shouldn't crash the cron — drop the alert quietly."""
    import urllib.error
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")
    # Should NOT raise:
    post_to_slack("https://hooks.slack.com/services/T/B/xxx", "test")
