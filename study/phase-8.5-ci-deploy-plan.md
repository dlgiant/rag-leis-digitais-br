# Phase 8.5 — CI + deploy pipeline (planning, NOT YET BUILT)

**Date:** 2026-05-20
**Status:** Planning. No code yet; no pre-locked criteria committed yet.
**Predecessors:**
- [Phase 8.1](phase-8-entry-plan.md#81--http-harness-1-session) HTTP harness (`213e0b4`)
- [Phase 8.2](phase-8.2-auth-rate-limit-findings.md) auth + rate limit (`4e7e51f`)
- [Phase 8.3](phase-8.3-structured-observability-findings.md) structured logs + OTel (`465720b`)
- [Phase 8.4](phase-8.4-load-test-findings.md) load test (`80e0aa7`) — calibrated SLOs the CI gate will assert against
- [Phase 8 entry plan](phase-8-entry-plan.md) 8.5 line-item: "GitHub Actions workflow … if suite green and fast eval shows no SLO regression vs. previous baseline, deploy to staging … manual promote-to-prod"

## Why this sub-phase blocks 8.6

Phase 8.6 (alerting) needs a deployed instance to alert ABOUT. Without
8.5's deploy pipeline, there's no production telemetry, no rolling
metrics window, no place for `cost-per-query > $0.05` to fire.
**8.5 must land before 8.6 can produce meaningful work.**

8.5 also picks up the methodology baton from 8.4: the load-test
harness produced calibrated SLO numbers, and the CI gate is how
those numbers stop being numbers in a doc and become **mechanical
checks** that block merge if violated.

## Two-stage decomposition

The Phase 8 entry plan groups CI + deploy into one sub-phase, but
they're separable. The plan recommends shipping **8.5.0** first
(pure CI, no platform commitment) and **8.5.1** after (deploy
pipeline to a chosen platform).

### 8.5.0 — Continuous Integration (½ session, $0)
- GitHub Actions workflow on every PR + push to main
- Runs `pytest` (current 468 tests)
- Runs `ruff` (linter — already a dev dep)
- Caches `uv` install for fast subsequent runs
- **Outputs**: green check on PR; merge button stays gray until checks pass
- **No deploy** — separate concern; pure quality gate

### 8.5.1 — Deploy pipeline (1 session, ~$0)
- Pick platform (recommend **Fly.io**, Brazilian region `gru`)
- `Dockerfile` for the server image
- `fly.toml` for app config (1 shared-cpu-1x instance, env vars
  wired; **no persistent volume** — Phase 7.9 LLM cache is
  eval-only, never enabled in production)
- GitHub Actions workflow: on merge to main → deploy to staging
- Manual promote-to-prod via `release` git tag or `gh` CLI
- Rollback: re-deploy previous tag

The split lets 8.5.0 land in half a session with zero platform
risk; 8.5.1 can wait if other priorities surface.

## 8.5.0 design — CI workflow

### Triggers

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
```

PRs to main get checked before merge; pushes to main re-check to
catch anything that slipped (e.g., bypass-merge or revert).

### Job: `test`

```yaml
- uses: actions/checkout@v4
- uses: astral-sh/setup-uv@v3
  with:
    enable-cache: true
- name: Install
  run: uv sync --extra voyage --extra server
- name: Lint
  run: uv run ruff check rag_leis/ tests/ scripts/
- name: Tests
  run: uv run pytest -q
```

**Why `--extra voyage --extra server`**: matches local dev install.
Cached uv install means subsequent CI runs reuse the resolved lock,
typically <1min vs ~3-5min fresh.

### Live-API test handling

`tests/test_llm.py::test_complete_returns_text` and similar call
Anthropic for real (we saw a 529 Overloaded earlier this session).
Three options:

| Option | Trade-off |
|---|---|
| **A. `pytest -m "not live"` (Recommended)** | Mark live-API tests with `@pytest.mark.live`; CI excludes them. Devs run them locally with credentials. Skips ~3-5 tests; covers the other 463. |
| B. Provide API keys via GitHub secrets | Adds secret-management burden + flakiness from upstream provider outages. |
| C. Mock the live calls | Loses the integration-test value of those tests. |

**Recommendation: A.** Mark the existing live-API tests with
`pytest.mark.live`; CI runs `pytest -m "not live"`. The marked
tests stay runnable locally (`uv run pytest -m live`).

### Pre-locked criteria for 8.5.0

> Phase 8.5.0 ships iff:
> 1. **`.github/workflows/ci.yml`** runs on every PR + push to main
> 2. **`pytest -m "not live"`** runs and passes (~463 tests; 5 live-API tests skipped)
> 3. **`ruff check`** runs and passes
> 4. Workflow wall time **< 5 min** on a cold runner; < 2 min with uv cache hit
> 5. PR cannot merge until both checks pass (branch protection rule applied to main)
> 6. Existing 468 tests + tested-locally 5 live-API tests still pass

### Branch protection rule

Configure via repo Settings → Branches → "Require status checks
before merging" → require the `test` job. **Not in the workflow
file itself** — it's a one-time repo setting. The findings doc will
document the exact config + steps.

## 8.5.1 design — Deploy pipeline

### Platform comparison (cost, latency, CLI)

Pricing snapshot 2026-05; verify before committing. Comparison
target: single instance, 1 vCPU / 2GB RAM, ~3 QPS sustained per
the Phase 8.4 measurement, persistent disk for the Phase 7.9 LLM
cache.

#### Cost (1 vCPU / 2GB RAM, light traffic v1)

| Platform | Compute / mo | Persistent disk (1GB) | Bandwidth | Free tier? | Effective v1 cost/mo |
|---|---:|---:|---:|---|---:|
| **Fly.io** shared-cpu-1x 2GB | ~$5.00 | $0.15 | 100GB free, then $0.02/GB | Trial credit; no perpetual free | **~$5** |
| **Railway** Hobby plan | $5 base + usage (~$5-10) | included | included up to plan | $5/mo free credit | **~$5-10** |
| **Render** Starter | $7.00 | $0.25 | included | Free tier (sleeps 15 min) | **$7** ($0 if sleeping OK) |
| **Hetzner CX22** bare VM | ~$4 (€3.79) | included (~40GB SSD) | 20TB free | None | **~$4** |
| **GCP Cloud Run** 1 vCPU, scale-to-zero | $0 idle + ~$0.0024/req-sec | needs GCS (~$0.02/GB-mo) | 1GB/mo free, then $0.12/GB | Yes (2M req/mo, 360k GB-sec) | **~$0-3** (light traffic) |
| **DigitalOcean App Platform** | $10 (1GB) or $25 (2GB) | $0.10/GB extra | 100GB included | None | **$10-25** |
| **AWS App Runner** | ~$7-15 | needs EFS (~$0.30/GB-mo) | included | None | **$7-15** |
| **Heroku** Basic | $7.00 | ephemeral; needs add-on | included | None | **$7+** (no persistent disk without add-on) |

For our workload all v1 differences are noise (<$15/mo). What
actually matters is the next two axes.

#### Latency (Brazilian users are the audience)

| Platform | Brazilian region? | Cold-start | Steady-state overhead vs localhost |
|---|---|---|---|
| **Fly.io** | ✅ `gru` São Paulo | ~3s with auto-stop; ~0s warm | + ~10-30ms RTT |
| **GCP Cloud Run** | ✅ `southamerica-east1` São Paulo | ~1-3s | + ~10-30ms RTT |
| **AWS App Runner** | ✅ `sa-east-1` São Paulo | ~30s-2min (known issue) | + ~10-30ms RTT |
| **AWS Lambda** | ✅ `sa-east-1` | ~3-10s Python container cold | + ~10-30ms RTT |
| **Railway** | ⚠️ added São Paulo in 2025 (verify) | ~5-15s | + ~10-30ms if BR; +~100ms otherwise |
| **Render** | ❌ closest is US-east | ~30-60s on free; ~1s paid | **+ ~100-200ms RTT** |
| **Heroku** | ❌ US/EU only | ~5-10s wake from Eco | **+ ~100-200ms RTT** |
| **DigitalOcean App** | ❌ closest is NYC | ~1-2s | **+ ~100-200ms RTT** |
| **Hetzner / OVH** | ❌ none in BR | none (always-on) | **+ ~150-200ms RTT** |

Phase 8.4 measured warm p95 = 2.87s on localhost. Adding 150-200ms
RTT pushes p95 to ~3.1s on non-BR providers — still under the
proposed Phase 8.6 SLO (`p95 < 5s`), but the headroom shrinks
meaningfully.

#### CLI tools

| Platform | CLI binary | Maturity | Notable strengths/weaknesses |
|---|---|---|---|
| **Fly.io** | `flyctl` | Excellent (5+ years) | Single binary, fast; `flyctl deploy --remote-only` builds on Fly's infra (no local Docker); clean secrets management |
| **Railway** | `railway` | Good (3+ years) | `railway up` clean; `railway logs` excellent; some weirdness around env-vars vs secrets terminology |
| **Render** | `render` | Newer (2024+) | Many ops still through web UI; CLI lags features |
| **Heroku** | `heroku` | Excellent (mature) | Original dev-friendly CLI; set the standard for `ps`/`logs --tail` |
| **DigitalOcean** | `doctl` | Excellent (mature) | Verbose; covers everything DO offers |
| **AWS App Runner** | `aws apprunner` | Verbose (typical AWS) | JSON config files; unpleasant for iterative work |
| **GCP Cloud Run** | `gcloud run` | Good | `gcloud run deploy --source .` is one-shot |
| **Hetzner** | `hcloud` | Good | Covers VMs/networks/firewalls; no PaaS layer — you build that |

#### Top-3 decision

| Criterion | Weight | Best fit |
|---|---|---|
| BR region available + LGPD compliance | **Hard filter** ([memory](../../../.claude/projects/-home-ricardo-rag-leis-digitais-br/memory/project_lgpd_brazil_residency.md)) | Fly.io, GCP Cloud Run, AWS App Runner, Railway |
| Cold-start under 5s | High (Phase 8.6 SLO `p95 < 5s`) | Fly.io, GCP Cloud Run, Hetzner, DO |
| CLI quality (iteration speed) | High (v1 iteration) | Fly.io, Heroku, DO |
| Cost under $10/mo | Medium | All except DO ($10-25) |
| Scale-to-zero option | Medium (personal traffic v1) | Fly.io (`auto_stop`), GCP Cloud Run, Render free |

(Persistent disk is intentionally NOT a criterion — the Phase 7.9 LLM cache is eval-only and never enabled in production; see memory `feedback-use-llm-cache-for-eval`.)

1. **Fly.io** — hits every box: BR region, fast cold-start,
   persistent volume, mature CLI, $5/mo. Trade-offs: scale-to-zero
   adds ~3s cold-start (acceptable for v1); single-provider risk
   (mitigated by tagged releases for easy migration).

2. **GCP Cloud Run** — real challenger. Same BR region, faster
   cold-start (1-3s), pay-per-invocation could be cheaper at light
   traffic. But needs GCS for persistent cache state (more glue
   code), `gcloud` CLI is verbose, Google posture is more
   "enterprise" than dev-iterative.

3. **Hetzner bare VM** — cheapest, most control. $4/mo,
   always-on, no platform lock-in. But no BR region (200ms RTT
   hit), no PaaS conveniences, you build TLS / systemd / deploy
   automation yourself. Worth it only at higher scale or if
   avoiding US-cloud dependencies is a goal.

### Platform choice — Fly.io

The comparison above validates the original recommendation:
**Fly.io**. It's not the cheapest by $1/mo, but it wins decisively
on (a) BR-region availability (a hard LGPD-compliance filter for a
Brazilian-law audience) and (b) the `flyctl` CLI's
iteration-friendliness (matters while 8.x is still in active
sub-phase work).

The two real fallback paths if Fly becomes unsuitable later:

- **GCP Cloud Run** — closest like-for-like swap. Same BR region;
  rewrite the Dockerfile entrypoint. No persistent-volume rewrite
  needed since the production deploy doesn't use one (cache is
  eval-only). Reasonable migration surface.
- **Hetzner bare VM** — strategic fallback if cost or sovereignty
  matters more than BR latency. Substantial rework (systemd unit,
  caddy/nginx for TLS, custom deploy automation). Defer until
  forced.

### `Dockerfile` (minimal)

```dockerfile
FROM python:3.12-slim
WORKDIR /app

# uv for fast installs; system deps minimal
RUN pip install uv

# Copy lockfile + project metadata first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --extra voyage --extra server --no-dev --frozen

# Copy source last (changes most often)
COPY rag_leis/ ./rag_leis/
COPY data/chunks/ ./data/chunks/
COPY data/index/ ./data/index/

# NOTE: do NOT set RAG_LLM_CACHE_DIR in production.
# The Phase 7.9 LLM cache is for eval re-runs only — production queries
# are unique (cache miss every time) AND a cache hit would serve stale
# responses. See memory `feedback-use-llm-cache-for-eval`.
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "rag_leis.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `fly.toml`

```toml
app = "rag-leis-digitais-br"
primary_region = "gru"

[build]

[env]
  RAG_LLM_PROVIDER = "maritaca"
  RAG_RATE_LIMIT_PER_MINUTE = "60"
  RAG_LOG_LEVEL = "INFO"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true        # scale to zero when idle
  auto_start_machines = true        # cold-start on first request
  min_machines_running = 0          # v1: no warm replicas
  [http_service.checks]
    interval = "30s"
    timeout = "5s"
    grace_period = "30s"
    method = "GET"
    path = "/health"

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory = "2gb"
```

**Notes:**
- `auto_stop_machines = true` → scales to zero when idle; cold-start
  ~3s when traffic returns. Cheap for v1 personal-traffic; revisit
  if production demands warm instances.
- **No persistent volume.** The Phase 7.9 LLM cache stays eval-only
  (see memory `feedback-use-llm-cache-for-eval`). Production runs
  with `RAG_LLM_CACHE_DIR` unset; every query goes through a fresh
  LLM call. Removing the volume mount also keeps cold-start simpler
  (nothing to attach/detach across machine moves).
- Health check at `/health` uses Phase 8.1's endpoint.

### Secrets

Set via `fly secrets set` (NOT committed to repo):

- `MARITACA_API_KEY`
- `ANTHROPIC_API_KEY`
- `VOYAGE_API_KEY`
- `RAG_API_KEYS` — comma-separated list of valid keys (Phase 8.2)

### CI deploy workflow

```yaml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    needs: test  # from 8.5.0 ci.yml
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

**Important**: depends on the 8.5.0 `test` job — if tests fail,
no deploy. This is the gate.

### Promote-to-prod

For v1: **staging IS prod** on Fly's `*.fly.dev` URL. Custom domain
(`rag.nunes.work`?) + multi-environment is Phase 9.

For a clean rollback path: tag releases (`v0.1.0`, `v0.1.1`, ...);
rollback = `fly deploy --image registry.fly.io/rag-leis-digitais-br:<sha>`
of a previous successful image.

### Pre-locked criteria for 8.5.1

> Phase 8.5.1 ships iff:
> 1. `Dockerfile` builds clean (`docker build .` succeeds locally)
> 2. `fly.toml` deploys to Fly (`fly launch` + `fly deploy`)
> 3. `GET /health` returns 200 within 60s of first deploy
> 4. `POST /v1/ask` with a valid API key returns 200 with sane
>    response (smoke-test via curl against the *.fly.dev URL)
> 5. Phase 8.4 harness run against the deployed URL at concur=4
>    shows: error_rate=0, p95<5s (real-network RTT will exceed
>    localhost; tighten only if measurement allows)
> 6. Deploy workflow gates on the `test` job from 8.5.0
> 7. Rollback to previous tag via documented `fly deploy --image`
>    command works (verified on staging)
> 8. Findings doc captures the actual deploy + cold-start + RTT
>    numbers

## Out of scope (explicit non-goals)

### Out of 8.5.0
- Coverage reporting (codecov)
- Mutation testing
- Type-check enforcement (mypy) — codebase has mixed types; gating
  would surface a large backlog. Defer to Phase 9 cleanup.
- Auto-merge on green checks
- Required reviewers (1+ reviewer rule) — solo project; revisit
  if collaborators join

### Out of 8.5.1
- Multi-region (single `gru` region for v1)
- CDN / edge caching
- Custom domain + TLS (uses Fly's *.fly.dev with auto-TLS)
- Multi-tenant / per-user accounts (Phase 9)
- Blue-green deploys (Fly's default rolling deploy is fine for 1 instance)
- Database (no DB; everything in-memory or on persistent volume)
- Multi-environment (staging + prod separately) — single environment for v1
- Cost dashboards (just check Fly billing UI manually for v1)
- Automated rollback on metric regression (Phase 9; for v1 it's manual)

## Open design questions to resolve at sub-phase start

1. **Should the CI gate include a load-test smoke (Phase 8.4 harness
   at concur=4)?** Recommendation: **YES, but only after 8.5.1
   deploys staging**. Pre-deploy gate is just `pytest`. Post-deploy
   verification runs the harness against the *.fly.dev URL and
   asserts SLOs. Splits "code quality" from "deployment health"
   into separate workflows.

2. **Should secrets be in GitHub Actions or in Fly?** Recommendation:
   **Fly only**. The deploy workflow needs `FLY_API_TOKEN` to push;
   Fly itself holds the runtime secrets. No `MARITACA_API_KEY` in
   GitHub Actions = smaller blast radius if a workflow leaks.

3. **8.5.0 lint enforcement: warn or fail?** Recommendation: **fail**.
   Codebase is already ruff-clean (verified by running locally);
   no migration burden. CI failure on new lint errors is the right
   default.

4. **What happens to `test_complete_returns_text` in CI?** Mark with
   `@pytest.mark.live` and skip via `pytest -m "not live"`. Findings
   doc captures the list of marked tests + how to run them locally.

5. **(Resolved)** Earlier drafts of this plan considered warming a
   production LLM cache. **Decision: production runs WITHOUT cache.**
   Phase 7.9 cache is eval-only — see memory
   `feedback-use-llm-cache-for-eval`. Reasons: production queries
   are unique (no cache benefit), cache hits would risk serving
   stale responses, and `cost_estimate_usd` reports theoretical
   (token-based) cost even on cache hits — production telemetry
   would silently lie about real LLM spend if cache were on.

## Risk + tradeoff analysis

| Risk | Severity | Mitigation |
|---|---|---|
| CI takes > 5 min, slows dev velocity | Low | uv cache + `pytest -m "not live"` keeps wall < 2 min hot |
| Secrets leak via GitHub Actions log | Medium | Don't put runtime secrets in GHA; Fly holds them; only `FLY_API_TOKEN` lives in GHA |
| Single-instance Fly deploy → outage during deploy | Low | Fly's default rolling deploy waits for new instance healthy before killing old; ~30s of mixed-version traffic acceptable for v1 |
| Cold-start latency > acceptable | Medium | `auto_stop_machines = true` saves cost but adds ~3s cold-start. Measure on Fly; adjust to `min_machines_running = 1` if UX requires |
| Fly outage takes down service | Low | Single-region, single-provider risk. Multi-region is Phase 9 |

## Cost estimate

- **8.5.0**: $0 (GitHub Actions free tier is generous for solo projects)
- **8.5.1**: $0-$2/mo
  - Fly shared-cpu-1x = $1.94/mo
  - 1GB persistent volume = $0.15/mo
  - Bandwidth on the free tier — should fit easily for v1 personal traffic
- **Wall time**: ~1.5 sessions total (½ for 8.5.0, 1 for 8.5.1)
- **No new Python deps**

## Sequencing

### 8.5.0 (first session)
1. Mark 5 live-API tests with `@pytest.mark.live` (lightweight grep + decorator add)
2. Add `[tool.pytest.ini_options]` to `pyproject.toml` registering the `live` marker
3. Write `.github/workflows/ci.yml`
4. Push branch, watch CI run, iterate until green
5. Apply branch protection rule (manual repo setting)
6. Findings doc: `phase-8.5.0-ci-findings.md`

### 8.5.1 (second session)
1. Write `Dockerfile`; verify `docker build .` succeeds locally
2. `fly launch` to scaffold; tweak `fly.toml` per design above
3. `fly secrets set` for API keys + `RAG_API_KEYS`
4. `fly deploy` first time; smoke-test via curl
5. Run Phase 8.4 harness against *.fly.dev URL at concur=4; capture numbers
6. Write `.github/workflows/deploy.yml`; push to verify automatic deploy works
7. Document rollback procedure; test it on staging
8. Findings doc: `phase-8.5.1-deploy-findings.md`

## What we'll learn that's not in this plan

- Real-network RTT impact on p95 latency (localhost: 2.87s → Fly+RTT: ?ms)
- Cold-start time on Fly's shared-cpu-1x (pipeline load + first request)
- Whether persistent volume mount adds measurable IO latency
- How Fly handles deploy-time blips (rolling deploy + health checks)
- Free-tier limits we'll bump into (bandwidth, build minutes, etc.)
- Whether `uvloop` (installed by `uvicorn[standard]`) plays well with Fly's runtime

## Cross-references

- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — parent plan
- [`phase-8.4-load-test-findings.md`](phase-8.4-load-test-findings.md) — SLO numbers the CI gate will assert
- [`phase-8.2-auth-rate-limit-findings.md`](phase-8.2-auth-rate-limit-findings.md) — `RAG_API_KEYS` env var that fly secrets needs to set
- `.github/workflows/ci.yml` — file we'll create (8.5.0)
- `.github/workflows/deploy.yml` — file we'll create (8.5.1)
- `Dockerfile`, `fly.toml` — files we'll create (8.5.1)
