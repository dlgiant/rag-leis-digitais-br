# Phase 8.6 — Cost ceiling + Slack alerting (findings)

**Date:** 2026-05-20
**Predecessor:** [Phase 8.6 plan](phase-8.6-alerting-plan.md), drafted 2026-05-20.
**Cost:** $0. Pure stdlib + Slack's free incoming-webhook API.
**Status:** Phase 8.6 SHIPPED end-to-end. **Phase 8 is closed.** All 5 pre-locked criteria met. Provider hard caps are a one-time manual operator action; documented below.

## Pre-locked criteria — result

| # | Criterion | Status |
|---|---|:-:|
| 1 | Provider caps documented (Anthropic / Maritaca / Voyage; UI paths + recommended values) | ✅ this doc; operator-to-apply |
| 2 | `scripts/phase_8_6_alert_check.py` runs against a fixture; PASS/ALERT per rule | ✅ 17 tests in `tests/test_alert_check.py` |
| 3 | `.github/workflows/alerts.yml` triggers every 15 min on cron + workflow_dispatch | ✅ `2c2b14e` |
| 4 | Test alert delivered to Slack channel via workflow_dispatch | ✅ verified end-to-end |
| 5 | Threshold tuning documented + rationale per threshold | ✅ recalibrated from Phase 8.5.1 prod numbers; rationale in plan doc |

## What ships

- **`scripts/phase_8_6_alert_check.py`** (~270 lines, stdlib only):
  - `fetch_fly_logs(app, hours)` — calls `flyctl logs --no-tail`
  - `extract_json_events(lines)` — pulls our structured JSON out of Fly's `<ts> app[<id>] <region> [info]{...}` prefix
  - `compute_metrics(events, now)` — rolling-window aggregations: p50/p95/p99 latency (5m), error rate (5m), cost mean (1h), auth failures grouped by client_ip (1h)
  - `check_thresholds(m)` — returns list of breach dicts; each breach has `{name, value, threshold, msg}`. Min-sample requirements built in so 1 slow request doesn't page.
  - `post_to_slack(webhook_url, text)` — single POST; swallows URLError so a Slack outage doesn't crash the cron
  - `format_alert(breaches, metrics, app)` — Slack-flavored markdown
  - CLI: `--logs-file` (fixture testing), `--no-post` (dry run), `--test` (synthetic alert to verify plumbing)
- **`tests/test_alert_check.py`** (~225 lines, 17 tests):
  - extract_json_events: Fly log-prefix parsing + malformed-line skipping
  - compute_metrics: window exclusion, error rate, auth-by-IP grouping
  - check_thresholds: happy path, per-rule breaches, min-sample guards
  - format_alert + Slack mocks (no actual Slack hits during tests)
- **`.github/workflows/alerts.yml`** (~50 lines):
  - cron `*/15 * * * *` + `workflow_dispatch` (with `test_alert` input)
  - `concurrency: cancel-in-progress: true` — drops in-flight runs if a new one starts
  - 5-min timeout
  - Sets up uv (cached) + flyctl + reads `FLY_API_TOKEN` + `SLACK_WEBHOOK_URL` from GHA secrets

## Threshold table (recalibrated from Phase 8.5.1 prod)

```
P50_LATENCY_MS_5MIN = 15_000   # > 15s sustained 5 min   → alert
P95_LATENCY_MS_5MIN = 20_000   # > 20s sustained 5 min   → alert
P99_LATENCY_MS_5MIN = 30_000   # > 30s sustained 5 min   → alert
COST_MEAN_USD_1H    = 0.015    # > $0.015/query rolling 1h  → alert
ERROR_RATE_5MIN     = 0.02     # > 2% error over 5 min   → alert
AUTH_FAILURE_PER_HR = 10       # > 10 auth.failed/hr same IP → alert
```

Rationale per threshold (full version in plan doc):

| Threshold | Prod measured | Headroom | Why |
|---|---|---|---|
| p50 > 15s | ~9-10s | 1.5× | warm steady state; alert when slipping toward cold-call territory |
| p95 > 20s | ~13s | 1.5× | catches sustained degradation; doesn't fire on single slow request |
| p99 > 30s | ~19.5s cold | 1.5× | catches sustained cold-start-equivalent; transient cold-start single requests get absorbed |
| cost mean > $0.015 | $0.005-0.007 | 2-3× | catches token-runaway; rolling 1h smooths spikes |
| err rate > 2% | 0% steady | infinite | any sustained error pattern is signal |
| auth/hr > 10 same IP | n/a baseline | n/a | credential-stuffing / abuse signal |

## Min-sample guards (anti-paging discipline)

```
MIN_REQUESTS_FOR_RATE       = 5     # error rate needs ≥5 requests in window
MIN_REQUESTS_FOR_PERCENTILE = 10    # latency p* needs ≥10 requests in window
```

Cost has NO min-sample requirement — a single $0.05/query event in a
quiet hour IS the runaway signal (probably token-explosion), not noise.

## Live verification

Triggered `gh workflow run alerts.yml -f test_alert=true` after commit
`2c2b14e`. Run `26177519415` completed `success`. The synthetic message
shape:

```
🧪 *rag-leis 8.6 test alert*
This is a synthetic message verifying the alert pipeline.
_Cron path: `.github/workflows/alerts.yml`; script: `scripts/phase_8_6_alert_check.py`_
```

Operator confirmed visual delivery in the Slack `#rag-leis-alerts`
channel. End-to-end pipeline (GitHub Actions → script → Slack webhook
→ message rendered) works.

## Slack transport choice — current Slack-App Incoming Webhooks (NOT the deprecated form)

Documented in detail in the plan doc. Short version:

| Variant | Status (2025) |
|---|---|
| **Custom Integrations Incoming Webhooks** (legacy) | ❌ deprecated since 2019 |
| **Slack App Incoming Webhooks** (used here) | ✅ current, recommended by Slack |
| **Web API `chat.postMessage`** | ✅ current alternative; richer features |

Both legacy and current share the `hooks.slack.com/services/...` URL
shape, which is why they're easy to confuse. The form we're using is
created at `api.slack.com/apps` → Create New App → Incoming Webhooks
feature → Add to Workspace.

## Provider hard caps (operator action; not in code)

These are **dashboard-only** configurations. Apply once; they survive
all application-side alerting failures.

| Provider | UI path | Recommended cap | Notes |
|---|---|---:|---|
| **Anthropic** | `console.anthropic.com` → Plans & Billing → Usage Limits | **$20/mo hard cap + $10/mo budget alert** | Used by Phase 7.x eval (Opus answer-judge); not on production hot path. The cap protects against an eval misconfiguration. |
| **Maritaca** | `maritaca.ai` → Faturamento | **$20/mo hard cap** (verify "hard cap" exists; if not, budget alert only) | Used on the production hot path (generator + self-judging relevance gate). Cap = ~4000 queries/mo at current $0.005/query, well above realistic personal-traffic v1 ceiling. |
| **Voyage AI** | `voyageai.com` → Account → Usage | **$10/mo hard cap + $5/mo budget alert** | Used on every retrieval. ~5000 queries/mo at current rates. |

**These caps are below the application-side alert thresholds** (which
operate on per-query mean). The two layers complement each other:
- Application alerts fire on **per-query anomalies** (single
  expensive request → loud signal within minutes)
- Provider caps fire on **monthly cumulative spend** (e.g., abuse
  pattern that stays under per-query threshold but compounds)

## What's NOT in this sub-phase (explicit non-goals)

Per the plan, all deferred to Phase 9 or removed entirely:

- Real-time (<1 min) alerting
- Public status page / uptime widget
- Anomaly detection / ML-driven alerting
- Multi-recipient escalation
- Incident response runbook (the alert payload itself is the runbook
  for v1)
- Cost forecasting / budget projection
- Refusal-accuracy auto-drift detection (operator runs a weekly
  offline check)
- Stateful alerting (cross-run deduplication, trend tracking)

## What this enables for Phase 9+

- **30-day production traffic** will calibrate the threshold values.
  Currently they're best-guesses from Phase 8.5.1's n=4 prod queries.
  After ~30 days, compute the actual production p50/p95/p99 distribution
  and tune.
- **Refusal-accuracy weekly check** is operator-initiated for now.
  A small `scripts/phase_8_6_weekly_refusal_check.py` helper could
  automate it against a held-out replay subset; first time the
  operator forgets is the trigger to build it.
- **Alert fatigue tracking** — if duplicates-across-runs becomes
  annoying, GHA cache can hold last-alert state and suppress repeats.
- **Multi-instance scaling** — when a second Fly machine is added
  (Phase 9 horizontal scale), `flyctl logs` already aggregates
  across all machines; alert script works unchanged.

## Three things learned during 8.6

1. **"Incoming Webhooks" is two distinct surfaces at Slack.** The
   Slack-App-scoped form (used here) is current and supported. The
   "Custom Integrations" form (predating Slack Apps) is the
   deprecated one. They share the URL shape, which made the
   distinction non-obvious. Slack's own docs at
   `api.slack.com/messaging/webhooks` open with a clarifying note.

2. **Min-sample guards are load-bearing for anti-paging discipline.**
   Without them, a single 30s cold-start request in a quiet hour
   would alert as "p95 > 20s." With `MIN_REQUESTS_FOR_PERCENTILE = 10`,
   the same request gets absorbed — alerts only fire when the
   degradation is sustained across multiple requests. Trade-off:
   misses the first 10 requests of a degradation cycle. Acceptable
   at v1; documented.

3. **Stateless alerting accepts duplicates as confirmations.** Each
   15-min cron run independently re-evaluates the same thresholds.
   If a breach persists across 4 runs (= 1 hour), the operator sees
   4 alerts. That's intentional UX — silent re-alerting is the
   "if you're not fixing it, the alert is still valid" signal.

## What changed in the codebase

- `scripts/phase_8_6_alert_check.py` (new, ~270 lines)
- `tests/test_alert_check.py` (new, ~225 lines)
- `.github/workflows/alerts.yml` (new, ~50 lines)
- `study/phase-8.6-alerting-plan.md` (updated to clarify legacy
  vs current Incoming Webhooks)
- `study/phase-8.6-alerting-findings.md` (this doc)
- `BACKLOG.md` — Phase 8.6 marked ✅; Phase 8 marked ✅ overall

## Cross-references

- [`phase-8.6-alerting-plan.md`](phase-8.6-alerting-plan.md) — the plan this closes
- [`phase-8.5.1-deploy-findings.md`](phase-8.5.1-deploy-findings.md) — production latency measurements that recalibrated 8.6 thresholds
- [`phase-8.4-load-test-findings.md`](phase-8.4-load-test-findings.md) — original localhost numbers (now superseded for alerting purposes)
- [`phase-8.3-structured-observability-findings.md`](phase-8.3-structured-observability-findings.md) — the log schema this consumes
- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — parent plan; **Phase 8 is now ✅ closed**

## Phase 8 closing summary

| Sub-phase | Status | Commit / Merge |
|---|:-:|:-:|
| 8.0 — Prod cost baseline | ✅ | `1d1e9d8` |
| 8.0.1 — sabia-3.1 vs sabia-4 swap | ✅ | `1d1e9d8` |
| 8.1 — HTTP harness | ✅ | `213e0b4` |
| 8.2 — Auth + rate limit | ✅ | `4e7e51f` |
| 8.3 — Structured observability | ✅ | `465720b` |
| 8.4 — Load test + capacity | ✅ | `80e0aa7` |
| 8.5.0 — CI workflow | ✅ | `cbaca87` + cleanup commits |
| 8.5.1 — Fly.io deploy | ✅ | `d0b811e` + cleanup commits |
| **8.6 — Cost ceiling + Slack alerting** | ✅ | `2c2b14e` |

**Phase 8 = hosted production service with full auth, observability,
load-tested capacity, CI-gated deploys, and threshold-based Slack
alerting.** End-to-end: clone repo → push to main → CI gate → if
green, deploy to Fly's `gru` region → structured logs → cron scrapes
and pages on threshold breach.

The next phase (Phase 9) is open scope: eval expansion, multi-tenant,
custom domain, multi-region, anomaly detection, refusal-accuracy
drift, etc.
