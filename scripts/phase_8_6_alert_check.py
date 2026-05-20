"""Phase 8.6 — Cost ceiling + Slack alerting.

Polls Fly's structured JSON logs, computes rolling-window metrics,
and posts a Slack message when any threshold breaches.

Stateless: every run reads from `flyctl logs --no-tail`, computes
fresh metrics from the last N hours, decides PASS/ALERT. No state
carried across runs. Duplicate alerts on repeated breaches are
acceptable — they're confirmations, not noise.

Usage:
    # Production cron (called from .github/workflows/alerts.yml):
    PYTHONPATH=. uv run python -m scripts.phase_8_6_alert_check

    # Local dry-run against captured logs file:
    PYTHONPATH=. uv run python -m scripts.phase_8_6_alert_check \\
        --logs-file fixture.jsonl --no-post

    # Force a test alert to Slack (verifies plumbing):
    PYTHONPATH=. uv run python -m scripts.phase_8_6_alert_check --test

Secrets required (env vars):
    FLY_API_TOKEN       — read by `flyctl logs`
    SLACK_WEBHOOK_URL   — incoming webhook for the alert channel
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# -------------------------------------------------------------------
# Thresholds — recalibrated from Phase 8.5.1, then again from
# Phase 10.0 + 10b smoke tests against the deployed SSE endpoint.
#
# Original Phase 8.5.1 measurement (no relevance gate timing
# included): warm p95 ~13s. Original thresholds (p50=15s, p95=20s)
# were calibrated against that.
#
# Phase 10.0 smoke test added the relevance_judge stage to the
# end-to-end measurement: ~8.6s for that stage alone, pushing
# warm end-to-end p95 to ~20s. The original p95=20s threshold
# was sitting exactly at the warm-state ceiling — guaranteed
# false positives on routine traffic.
#
# New thresholds give ~50% headroom over measured warm p95 so
# normal traffic doesn't trip the alert, while still catching
# real degradation. Reviewed again after 30 days of real traffic.
# -------------------------------------------------------------------
P50_LATENCY_MS_5MIN = 20_000.0       # > 20s sustained 5 min  → alert (warm p50 ~10-13s)
P95_LATENCY_MS_5MIN = 30_000.0       # > 30s sustained 5 min  → alert (warm p95 ~20s)
P99_LATENCY_MS_5MIN = 40_000.0       # > 40s sustained 5 min  → alert (cold p99 ~20-34s; min_machines_running=1 reduces frequency)
COST_MEAN_USD_1H    = 0.015          # > $0.015/query rolling 1h  → alert
ERROR_RATE_5MIN     = 0.02           # > 2% error over 5 min  → alert
AUTH_FAILURE_PER_HR = 10             # > 10 auth.failed/hr same IP  → alert

# Minimum sample size before we'll fire a latency/error alert.
# A single bad request in a low-traffic 5-min window shouldn't page.
MIN_REQUESTS_FOR_RATE = 5
MIN_REQUESTS_FOR_PERCENTILE = 10


# -------------------------------------------------------------------
# Log fetching
# -------------------------------------------------------------------


def fetch_fly_logs(app: str, hours: float) -> list[str]:
    """Call `flyctl logs --no-tail` and return raw log lines.

    `--no-tail` exits after dumping recent lines instead of streaming.
    Fly's default lookback is a few hours of recent activity.
    """
    cmd = ["flyctl", "logs", "--no-tail", "--app", app]
    flyctl_path = os.environ.get("FLYCTL_BIN", "flyctl")
    cmd[0] = flyctl_path
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except FileNotFoundError as e:
        print(f"ERROR: flyctl binary not found at {flyctl_path!r}", file=sys.stderr)
        raise SystemExit(2) from e
    if result.returncode != 0:
        print(f"flyctl exit {result.returncode}: {result.stderr[:300]}", file=sys.stderr)
        raise SystemExit(result.returncode)
    return result.stdout.splitlines()


def extract_json_events(lines: list[str]) -> list[dict[str, Any]]:
    """Pull our app's structured JSON events out of the Fly log lines.

    Each Fly log line looks like:
        2026-05-20T16:16:24Z app[d8946d...] gru [info]{"event":...}

    We slice from the first `{` to the end and json-load. Lines that
    aren't our JSON (Fly platform messages, uvicorn startup, etc.)
    are skipped silently.
    """
    events: list[dict[str, Any]] = []
    for line in lines:
        i = line.find("{")
        if i < 0:
            continue
        try:
            obj = json.loads(line[i:])
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or "event" not in obj:
            continue
        events.append(obj)
    return events


# -------------------------------------------------------------------
# Metric computation
# -------------------------------------------------------------------


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = max(1, min(len(sorted_values), round(p / 100.0 * len(sorted_values))))
    return sorted_values[k - 1]


def parse_ts(ts: str) -> datetime | None:
    """Parse the ISO-8601 timestamps structlog emits."""
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts[:-1]).replace(tzinfo=UTC)
        return datetime.fromisoformat(ts)
    except (ValueError, AttributeError):
        return None


def compute_metrics(events: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Return all metrics relevant to the threshold table."""
    five_min_ago = now - timedelta(minutes=5)
    one_hour_ago = now - timedelta(hours=1)

    completed_5m: list[dict[str, Any]] = []
    answered_1h: list[dict[str, Any]] = []
    auth_failed_1h: list[dict[str, Any]] = []
    pipeline_errors_5m: list[dict[str, Any]] = []

    for e in events:
        ts = parse_ts(e.get("timestamp", ""))
        if ts is None:
            continue
        evt = e.get("event")
        if ts >= five_min_ago:
            if evt == "request.completed" and e.get("path") == "/v1/ask":
                completed_5m.append(e)
            if evt == "pipeline.error":
                pipeline_errors_5m.append(e)
        if ts >= one_hour_ago:
            if evt == "pipeline.answered":
                answered_1h.append(e)
            if evt == "auth.failed":
                auth_failed_1h.append(e)

    # Latency from request.completed (last 5 min)
    latencies = sorted(float(e.get("latency_ms", 0.0)) for e in completed_5m)
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)

    # Error rate (last 5 min)
    n_completed = len(completed_5m)
    n_errors = sum(1 for e in completed_5m if int(e.get("status_code", 0)) >= 500)
    n_errors += len(pipeline_errors_5m)
    error_rate = (n_errors / n_completed) if n_completed > 0 else 0.0

    # Cost rolling 1h mean
    costs = [float(e.get("cost_estimate_usd", 0.0)) for e in answered_1h]
    cost_mean_1h = statistics.mean(costs) if costs else 0.0
    cost_total_1h = sum(costs)

    # Auth-failure rate per IP, last 1h
    auth_by_ip: dict[str, int] = Counter(
        e.get("client_ip") or "unknown" for e in auth_failed_1h
    )
    auth_top_ip, auth_top_count = (
        max(auth_by_ip.items(), key=lambda kv: kv[1]) if auth_by_ip else ("none", 0)
    )

    return {
        "n_completed_5m": n_completed,
        "n_pipeline_answered_1h": len(answered_1h),
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "latency_p99_ms": p99,
        "error_rate_5m": error_rate,
        "n_errors_5m": n_errors,
        "cost_mean_usd_1h": cost_mean_1h,
        "cost_total_usd_1h": cost_total_1h,
        "auth_failed_total_1h": len(auth_failed_1h),
        "auth_failed_top_ip": auth_top_ip,
        "auth_failed_top_count": auth_top_count,
    }


# -------------------------------------------------------------------
# Threshold evaluation
# -------------------------------------------------------------------


def check_thresholds(m: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of {name, value, threshold, message} per breach.

    Empty list = nothing to alert. Each breach is independent; one
    cron run can emit a single message with multiple breaches.
    """
    breaches: list[dict[str, Any]] = []

    # Latency — require minimum sample size to avoid 1-bad-request paging
    if m["n_completed_5m"] >= MIN_REQUESTS_FOR_PERCENTILE:
        if m["latency_p50_ms"] > P50_LATENCY_MS_5MIN:
            breaches.append({
                "name": "latency_p50_5m",
                "value": f"{m['latency_p50_ms']/1000:.1f}s",
                "threshold": f"> {P50_LATENCY_MS_5MIN/1000:.0f}s",
                "msg": f"p50 latency {m['latency_p50_ms']/1000:.1f}s over last 5 min ({m['n_completed_5m']} req)",
            })
        if m["latency_p95_ms"] > P95_LATENCY_MS_5MIN:
            breaches.append({
                "name": "latency_p95_5m",
                "value": f"{m['latency_p95_ms']/1000:.1f}s",
                "threshold": f"> {P95_LATENCY_MS_5MIN/1000:.0f}s",
                "msg": f"p95 latency {m['latency_p95_ms']/1000:.1f}s over last 5 min ({m['n_completed_5m']} req)",
            })
        if m["latency_p99_ms"] > P99_LATENCY_MS_5MIN:
            breaches.append({
                "name": "latency_p99_5m",
                "value": f"{m['latency_p99_ms']/1000:.1f}s",
                "threshold": f"> {P99_LATENCY_MS_5MIN/1000:.0f}s",
                "msg": f"p99 latency {m['latency_p99_ms']/1000:.1f}s over last 5 min ({m['n_completed_5m']} req)",
            })

    # Error rate — require minimum sample size
    if m["n_completed_5m"] >= MIN_REQUESTS_FOR_RATE and m["error_rate_5m"] > ERROR_RATE_5MIN:
        breaches.append({
            "name": "error_rate_5m",
            "value": f"{m['error_rate_5m']*100:.1f}%",
            "threshold": f"> {ERROR_RATE_5MIN*100:.0f}%",
            "msg": f"error rate {m['error_rate_5m']*100:.1f}% over last 5 min ({m['n_errors_5m']}/{m['n_completed_5m']})",
        })

    # Cost — no min sample; one $0.015 query in an hour with no other traffic
    # IS the signal (probably a 100x-tokens runaway), not noise.
    if m["cost_mean_usd_1h"] > COST_MEAN_USD_1H:
        breaches.append({
            "name": "cost_mean_1h",
            "value": f"${m['cost_mean_usd_1h']:.4f}",
            "threshold": f"> ${COST_MEAN_USD_1H:.4f}",
            "msg": (
                f"mean cost/query ${m['cost_mean_usd_1h']:.4f} over last 1h "
                f"({m['n_pipeline_answered_1h']} answered, total ${m['cost_total_usd_1h']:.2f})"
            ),
        })

    # Auth abuse signal — top-source-ip from last hour
    if m["auth_failed_top_count"] > AUTH_FAILURE_PER_HR:
        breaches.append({
            "name": "auth_failed_concentration",
            "value": str(m["auth_failed_top_count"]),
            "threshold": f"> {AUTH_FAILURE_PER_HR}",
            "msg": (
                f"auth.failed {m['auth_failed_top_count']} times from "
                f"`{m['auth_failed_top_ip']}` in last 1h (total {m['auth_failed_total_1h']} failures)"
            ),
        })

    return breaches


# -------------------------------------------------------------------
# Slack delivery
# -------------------------------------------------------------------


SLACK_TIMEOUT_SEC = 10


def post_to_slack(webhook_url: str, text: str) -> None:
    """POST {"text": ...} to the Slack incoming webhook URL.

    No retries; if Slack is down we'd rather drop one alert than
    block the cron job. Errors are printed for the GHA log.
    """
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=SLACK_TIMEOUT_SEC) as resp:
            if resp.status != 200:
                print(f"Slack POST returned {resp.status}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"Slack POST failed: {e}", file=sys.stderr)


def format_alert(breaches: list[dict[str, Any]], metrics: dict[str, Any], app: str) -> str:
    """Slack-flavored markdown. Single message per cron run."""
    lines = ["🚨 *rag-leis 8.6 alert*"]
    for b in breaches:
        lines.append(f"• *{b['name']}*: {b['msg']}")
    lines.append("")
    lines.append(
        f"_Last 5 min: {metrics['n_completed_5m']} `/v1/ask` requests; "
        f"last 1h: {metrics['n_pipeline_answered_1h']} answered._"
    )
    lines.append(f"<https://fly.io/apps/{app}/monitoring|Inspect Fly monitoring>")
    lines.append(f"Logs: `flyctl logs --app {app}`")
    return "\n".join(lines)


# -------------------------------------------------------------------
# CLI entry point
# -------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app", default="rag-leis-digitais-br",
                   help="Fly app name (default: %(default)s)")
    p.add_argument("--hours", type=float, default=1.0,
                   help="How many hours of logs to fetch (default: %(default)s)")
    p.add_argument("--logs-file", default=None,
                   help="Read logs from a file instead of `flyctl logs` (for testing)")
    p.add_argument("--no-post", action="store_true",
                   help="Print the alert payload but don't POST to Slack")
    p.add_argument("--test", action="store_true",
                   help="Force a synthetic alert to verify the Slack plumbing")
    args = p.parse_args()

    # Test mode: bypass log fetching, send a known message.
    if args.test:
        webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if not webhook:
            print("ERROR: SLACK_WEBHOOK_URL not set; can't deliver test alert", file=sys.stderr)
            return 1
        msg = (
            "🧪 *rag-leis 8.6 test alert*\n"
            "This is a synthetic message verifying the alert pipeline.\n"
            "_Cron path: `.github/workflows/alerts.yml`; script: `scripts/phase_8_6_alert_check.py`_"
        )
        if args.no_post:
            print(msg)
        else:
            post_to_slack(webhook, msg)
            print("Test alert posted to Slack.")
        return 0

    # Fetch logs
    if args.logs_file:
        lines = Path(args.logs_file).read_text(encoding="utf-8").splitlines()
    else:
        lines = fetch_fly_logs(app=args.app, hours=args.hours)

    events = extract_json_events(lines)
    if not events:
        print("No structured events found in the fetched logs.", file=sys.stderr)
        return 0  # nothing to alert on; not an error

    now = datetime.now(UTC)
    metrics = compute_metrics(events, now=now)
    breaches = check_thresholds(metrics)

    # Always print a one-line metrics summary for the GHA log
    print(
        f"n_completed_5m={metrics['n_completed_5m']}  "
        f"p50={metrics['latency_p50_ms']:.0f}ms  "
        f"p95={metrics['latency_p95_ms']:.0f}ms  "
        f"err_rate={metrics['error_rate_5m']*100:.1f}%  "
        f"cost_mean_1h=${metrics['cost_mean_usd_1h']:.4f}  "
        f"auth_top={metrics['auth_failed_top_ip']}({metrics['auth_failed_top_count']})"
    )

    if not breaches:
        print("✓ no breaches")
        return 0

    msg = format_alert(breaches, metrics, args.app)
    print("⚠️ breaches detected:")
    print(msg)

    if args.no_post:
        return 0
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        print("ERROR: SLACK_WEBHOOK_URL not set; alert would have fired but can't deliver",
              file=sys.stderr)
        return 2
    post_to_slack(webhook, msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
