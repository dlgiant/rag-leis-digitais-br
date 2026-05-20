# Phase 8.6 — Cost ceiling + alerting (planning, NOT YET BUILT)

**Date:** 2026-05-20
**Status:** Planning. No code yet; no pre-locked criteria committed yet.
**Predecessors:**
- [Phase 8.5.1](phase-8.5.1-deploy-findings.md) — service live at `https://rag-leis-digitais-br.fly.dev`. Real prod-measured numbers replace the localhost-derived Phase 8.4 SLO candidates.
- [Phase 8.4](phase-8.4-load-test-findings.md) — original (localhost) capacity table. SLOs proposed there need re-calibration; this plan does it.
- [Phase 8 entry plan](phase-8-entry-plan.md) 8.6 line-item: "daily spend cap; alert when cost > X, latency p95 > Y, error rate > Z, refusal accuracy drops; single channel — Telegram or email; not paging."

## Why this sub-phase closes Phase 8

Phase 8.6 is the **last sub-phase** in the entry-plan decomposition.
After it, Phase 8 is done — production is hosted, gated by CI,
observable via structured logs, AND has alerts that catch regressions
without manual log-watching. The remaining Phase 9 work (eval set
expansion, multi-tenant, custom domain, multi-region) doesn't depend
on alerting; it stands on its own.

## What 8.6 ships

Three layers, in order of dependency:

1. **Provider-side daily spend caps** (no code; dashboard config).
   The cheapest, most defense-in-depth move. If the application-
   side alerting misses a cost runaway, the providers themselves
   stop billing.
2. **Application-side threshold alerts** (small code + cron). Polls
   recent Fly structured logs, computes rolling-window metrics,
   posts to an alert channel when thresholds cross.
3. **Alert sink** — single channel for v1. Decision below.

## Recalibrated SLOs (from Phase 8.5.1 prod measurements)

Phase 8.4 proposed SLOs anchored to **localhost warm-cache** numbers.
Phase 8.5.1 measured **production warm steady-state** for the same
queries and got 3-5× slower latencies (no cache, real Maritaca RTT).
Phase 8.6 alert thresholds use the prod-mode numbers as the anchor:

| SLO | Phase 8.4 proposed | Phase 8.5.1 measured (prod) | **Phase 8.6 alert threshold** |
|---|---:|---:|---:|
| Latency p50 (warm) | < 1s | ~9-10s | **> 15s sustained 5 min** |
| Latency p95 (warm) | < 5s | ~13s | **> 20s sustained 5 min** |
| Cold-start p99 | not defined | ~19.5s | **> 30s sustained 5 min** |
| Cost mean / query | < $0.01 | $0.005-0.007 | **> $0.015 rolling 1h** (~3× normal) |
| Cost total / day | not defined | n/a yet | **> $5 / day** (cap; provider-enforced) |
| Error rate | < 1% | 0.0% steady | **> 2% over 5 min** |
| Refusal accuracy | ≥ 0.85 | not yet measured prod-side | **< 0.80 weekly** (offline check) |
| Auth failure rate | not defined | n/a baseline | **> 10 / hour from single IP** (abuse signal) |
| Rate-limit hits | not defined | n/a baseline | **informational** (count, no alert) |

## Layer 1 — Provider-side spend caps

| Provider | Current monthly limit | Recommended cap | How to set |
|---|---:|---:|---|
| **Anthropic** | (account-level; check) | **$10/mo budget alert + $20/mo hard cap** | console.anthropic.com → Plans & Billing → Usage Limits |
| **Maritaca** | (account-level; check) | **$10/mo budget alert + $20/mo hard cap** | maritaca.ai dashboard → Faturamento (verify available) |
| **Voyage AI** | (account-level; check) | **$5/mo budget alert + $10/mo hard cap** | voyageai.com dashboard → Account → Usage |

**Rationale:** for a personal project at the Phase 8.5.1-measured cost
(~$0.005/query × 100 queries/day = $15/mo worst case), $20/mo per
provider gives ~25% headroom over realistic spend AND firmly catches
runaway scenarios (e.g., key leaked, abuse pattern, infinite-loop
client). Hard cap is the floor that survives ALL application-side
alerting failures.

**Documentation, not code:** the findings doc captures exact UI
paths for each provider. Operator (you) sets these once.

## Layer 2 — Application-side threshold alerts

### Data source

Fly's structured JSON logs (Phase 8.3 output). Fetched via
`flyctl logs --no-tail` (one-shot recent logs) or Fly's log-shipping
feature (continuous stream to external service).

For v1 simplicity: poll-based via `flyctl logs --no-tail` from a
cron job. Continuous streaming via NATS / log-drain → external
service is Phase 9+ if traffic warrants.

### Check script

`scripts/phase_8_6_alert_check.py` (new):

1. `flyctl logs --no-tail --machine <id>` for last hour (limit
   ~5000 lines)
2. Parse each JSON log line; extract event + relevant fields
3. Compute:
   - Last-hour cost mean (mean of `cost_estimate_usd` in
     `pipeline.answered` events)
   - Last-5-min p95 latency (95th percentile of `latency_ms` in
     `request.completed` events)
   - Last-5-min error rate (count of `request.completed` with
     `status_code >= 500` / total)
   - Last-1h auth failure rate (count of `auth.failed` events
     grouped by `api_key_prefix` then by `client_ip`)
4. Compare each against threshold table
5. If ANY threshold crossed: POST to alert webhook with JSON body
   describing the breach
6. If nothing crossed: exit 0 silently

### Schedule

GitHub Actions cron in `.github/workflows/alerts.yml`:

```yaml
on:
  schedule:
    - cron: "*/15 * * * *"  # every 15 minutes
  workflow_dispatch:
```

15 minutes is the sweet spot:
- Latency outages catch within window
- Cost runaway catches within 1-hour mean (so 15min poll = 4 chances per hour)
- GitHub Actions cron has ~5 min jitter ('schedule' is best-effort
  per Actions docs); 15min cadence with 5min jitter still gives
  4-5 checks per hour worst case

## Layer 3 — Alert sink (channel choice)

| Option | Trade-off |
|---|---|
| **A. Slack incoming webhook (Recommended)** | Free for personal workspaces; single secret (the webhook URL) — no separate token + chat-ID split; HTTP POST with JSON body; markdown-flavored text rendering; threading and reactions available for ack workflow if desired later. |
| B. Telegram bot | Equally simple HTTP POST, but needs two secrets (bot token + chat_id). Bot setup via @BotFather is also 5 min. Trade-off vs Slack is mostly recipient preference. |
| C. Email via Mailgun / SendGrid | Requires account + API key + DNS verification. More friction for v1. |
| D. Discord webhook | Free; equally simple to Slack. Choose based on where operator already lives. |
| E. GitHub Issue auto-create | `gh issue create` from the workflow. Has audit trail; integrates with project tracking. Slower (issue notification lag); not appropriate for true outages. |
| F. SMS via Twilio | Costs money; needs phone-number SID + auth. Overkill for non-paging v1. |

**Recommendation: Slack.** One secret in GHA (`SLACK_WEBHOOK_URL`),
no library needed (`curl` or `urllib.request`), workspace-scoped
integration via @workspace admin or self-service if the operator owns
their workspace.

**Setup** (5 min, one-time):
1. Visit `api.slack.com/apps` → "Create New App" → "From scratch"
2. Name: `rag-leis-alerts`. Pick the destination workspace.
3. Sidebar → "Incoming Webhooks" → toggle ON.
4. Click "Add New Webhook to Workspace" → pick the channel (e.g.,
   `#rag-leis-alerts` — create one first if it doesn't exist).
5. Copy the webhook URL (shape:
   `https://hooks.slack.com/services/T.../B.../xxx`)
6. `gh secret set SLACK_WEBHOOK_URL --repo dlgiant/rag-leis-digitais-br`

**Phase 9 escalation path:** if alerting fatigue or multi-recipient
becomes a concern, swap to PagerDuty / Opsgenie / Better Stack.
Slack → those tools is a one-line webhook URL swap.

## Pre-locked criteria

> Phase 8.6 ships iff:
> 1. **Provider caps documented**: findings doc captures the exact
>    UI paths + recommended values for Anthropic / Maritaca / Voyage.
>    Operator commits to setting them (we cannot programmatically
>    verify they're set on each provider).
> 2. **`scripts/phase_8_6_alert_check.py`** exists and runs locally
>    against a fixture log dump. Produces correct PASS/ALERT output
>    for each threshold case (latency, cost, error, auth-failure).
> 3. **`.github/workflows/alerts.yml`** triggers every 15 min on
>    cron + on `workflow_dispatch`. Calls the script with
>    `FLY_API_TOKEN` + `SLACK_WEBHOOK_URL` secrets.
> 4. **Test alert delivered** to the Slack channel via
>    `workflow_dispatch` ("send a test alert" manual trigger).
> 5. **Threshold tuning documented**: findings doc explains how
>    each threshold was chosen (recalibrated from Phase 8.5.1 prod
>    measurements; rationale per threshold).

## Out of scope (explicit non-goals)

- **Real-time alerting** (sub-1-minute latency). 15-min cron is
  acceptable for personal-traffic v1. PagerDuty-style real-time
  is Phase 9 if SaaS-grade SLOs ever apply.
- **Status page / public uptime widget.** No public users to inform.
- **Anomaly detection / ML-driven alerting.** Threshold-based is
  enough for v1. Sophisticated drift detection is Phase 9.
- **Multi-recipient escalation.** Single channel; you alone are the
  recipient. Multi-recipient is Phase 9 if you bring on a team.
- **Incident response runbook.** Out of 8.6's scope. The alert
  itself says what's wrong; the runbook is "look at Fly logs,
  redeploy or rollback" for v1.
- **Cost forecasting / budget projection.** Cap-based, not
  prediction-based. Phase 9 if needed.
- **Refusal-accuracy drift detection on live traffic.** Requires
  human gold labels or an LLM judge; both cost more than the alert
  saves at v1 traffic. The "weekly offline check" mentioned in
  the SLO table is operator-initiated, not automated in 8.6.

## Open design questions to resolve at sub-phase start

1. **15-min cron vs 5-min cron?** Recommendation: **15 min**.
   GitHub Actions free-tier minutes are bounded; 5-min cron =
   8,640 runs/month = 1,500+ minutes if each run takes 10s. 15-min
   = 2,880 runs/month = 500 minutes — comfortable in the free tier
   (~2,000 min/mo). Phase 9 can tighten if needed.

2. **State across cron invocations?** Each cron run is stateless
   by default — it reads logs from "last N minutes" each time.
   Two cases this matters for: (a) preventing duplicate alerts
   (same breach detected in two consecutive runs), (b) tracking
   trends (cost trending up across multiple windows). For v1
   (personal traffic, infrequent alerts), **accept duplicate
   alerts** — they're confirmations, not noise. Phase 9 can add
   state via GitHub Actions cache.

3. **Threshold tuning over time.** Initial thresholds are derived
   from Phase 8.5.1 (n=4 warm queries). They're load-bearing
   guesses. Recommendation: **review thresholds after 30 days of
   real traffic** — adjust based on observed p95/cost distribution.
   This is a Phase 8.6.1 calibration follow-up, not 8.6's
   responsibility to perfect now.

4. **Alert format / content.** Recommendation: Slack message
   format (markdown rendered by incoming webhook):
   ```
   🚨 *rag-leis 8.6 alert*
   • p95 latency = 22.4s (> 20s threshold) [last 5 min]
   • Sample request_ids: `47e42a7c`, `d52f1840`
   • <https://fly.io/apps/rag-leis-digitais-br/monitoring|Inspect monitoring>
   • Logs: `flyctl logs --app rag-leis-digitais-br`
   ```
   One alert per breach; multiple breaches in one cron run = one
   message with all breaches listed. The Slack incoming-webhook
   payload is `{"text": "..."}`; threads/reactions optional later
   if ack workflows ever matter.

5. **What about the daemon `data/cache/llm/` (eval-only) growing
   unbounded?** Not a production concern (production has no cache).
   For dev machines, manual `rm -rf` is fine. Phase 9 could add a
   `cache_dump --prune` helper.

## Risk + tradeoff analysis

| Risk | Severity | Mitigation |
|---|---|---|
| Cron job rate-limited by Fly (`flyctl logs` quota) | Low | Fly's API limits are generous; 96 runs/day × ~5000 log lines fetched ≈ within normal use |
| GitHub Actions cron missed / delayed | Low | Documented as "best-effort"; 15-min cadence absorbs ~10min delay; missing a check window doesn't break next one |
| Slack webhook URL leak (in GHA secrets) | Low | Webhook is scoped to one channel + can only POST messages (read-only on Slack side). Rotate via Slack app management if leaked. |
| False-positive alerts during deploy windows | Medium | Provider rolling-deploys to new image cause brief latency spikes. Documented as expected; can suppress via `alerts.yml` skipping when a `deploy.yml` run is in-progress |
| Provider hard-cap kicks in mid-traffic → outage | Medium | Hard cap is at $20/mo per provider — well above realistic spend. Budget alert at $10 fires first to give warning |
| Refusal-accuracy drift not auto-detected | Medium | Acknowledged as out-of-scope for 8.6; operator runs the weekly offline check manually |

## Cost estimate

- **API spend**: $0 (alert script reads existing Fly logs; sends
  Slack messages over their free incoming-webhook API).
- **Wall time**: ~½ session (~2-3h) including:
  - script (~100 lines)
  - alerts.yml workflow (~20 lines)
  - Slack webhook setup (5 min)
  - threshold tuning + findings doc
- **New deps**: none (use stdlib `urllib.request` for the Slack POST;
  `subprocess.run` for `flyctl logs`).
- **Recurring**: GitHub Actions minutes (~500/mo well within free
  tier).

## Sequencing within 8.6

1. **Set up Slack incoming webhook** (one-time manual, ~5 min):
   - `api.slack.com/apps` → "Create New App" → "From scratch" → name `rag-leis-alerts`
   - Sidebar → "Incoming Webhooks" → toggle ON
   - "Add New Webhook to Workspace" → pick channel (e.g. `#rag-leis-alerts`)
   - Copy webhook URL
   - `gh secret set SLACK_WEBHOOK_URL --repo dlgiant/rag-leis-digitais-br`
2. **Write `scripts/phase_8_6_alert_check.py`**:
   - argparse: `--logs-from-stdin` (for testing) | `--hours N`
   - Threshold table (constants at top; easy to tune)
   - Parse loop + aggregations
   - Slack POST helper (single function: POST `{"text": ...}` to `SLACK_WEBHOOK_URL`)
3. **Unit tests** (`tests/test_alert_check.py`):
   - Synthetic log lines that trigger each threshold
   - Assert PASS vs ALERT verdict per case
   - Mock Slack POST (so test doesn't spam)
4. **Write `.github/workflows/alerts.yml`**:
   - cron `*/15 * * * *` + `workflow_dispatch`
   - Step: install uv (cached), checkout, run the script with secrets
5. **Test alert dispatch** via `gh workflow run alerts.yml`:
   - Manual trigger with a `--test` flag that forces one alert
   - Verify it lands in the Slack channel
6. **Set provider caps** (manual, document in findings):
   - Anthropic console → Plans & Billing → set $20 hard cap
   - Maritaca dashboard → similar
   - Voyage → similar
7. **Findings doc** with thresholds, rationale, test screenshots,
   provider-cap UI paths.

## What we'll learn that's not in this plan

- Whether 15-min cron is too noisy or too sparse in practice.
- Whether the threshold tuning needs adjustment after a few days
  of real traffic (initial values are based on n=4 prod queries).
- Whether Fly's log-shipping (NATS) would be a smoother integration
  for Phase 9 than periodic polling.
- Whether refusal-accuracy weekly check is operator-feasible (probably
  yes; a `scripts/phase_8_6_weekly_refusal_check.py` helper would make
  this easier — but defer to first time the operator forgets).

## Cross-references

- [`phase-8.5.1-deploy-findings.md`](phase-8.5.1-deploy-findings.md) — production measurements that recalibrated the SLO thresholds
- [`phase-8.4-load-test-findings.md`](phase-8.4-load-test-findings.md) — original localhost numbers (now superseded for alerting purposes by the prod measurements)
- [`phase-8.3-structured-observability-findings.md`](phase-8.3-structured-observability-findings.md) — the log schema the alert script consumes
- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — parent plan; 8.6 is the LAST sub-phase
- `scripts/phase_8_6_alert_check.py` — file we'll create
- `.github/workflows/alerts.yml` — file we'll create
