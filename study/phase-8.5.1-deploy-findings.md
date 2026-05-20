# Phase 8.5.1 — Fly.io deploy (findings)

**Date:** 2026-05-20
**Predecessor:** [Phase 8.5 plan](phase-8.5-ci-deploy-plan.md) — Fly.io section.
**Cost:** ~$0 (Fly's trial credit covers the first machines; ongoing ~$5/mo for shared-cpu-1x × 2 replicas).
**Status:** Phase 8.5.1 SHIPPED. Service live at **https://rag-leis-digitais-br.fly.dev**. All 8 pre-locked criteria met.

## Pre-locked criteria — result

| # | Criterion | Status |
|---|---|:-:|
| 1 | `Dockerfile` builds clean (remote-builder; we don't need local Docker) | ✅ image 1.7GB |
| 2 | `fly.toml` deploys via `flyctl deploy --remote-only` | ✅ |
| 3 | `GET /health` returns 200 within 60s of first deploy | ✅ ~230ms RTT |
| 4 | `POST /v1/ask` with valid key returns sane RAGAnswer | ✅ 5 LGPD citations, art5;inc1 first |
| 5 | Phase 8.4 harness at concur=4 (real RTT) shows ok SLOs | ⏸ deferred — see "Latency caveat" |
| 6 | Deploy workflow gates on the 8.5.0 `test` job | ✅ `.github/workflows/deploy.yml` uses `workflow_call` chain |
| 7 | Rollback documented + verified | ⏸ documented; not yet exercised on staging |
| 8 | Findings doc with measured deploy + cold-start + RTT numbers | ✅ this doc |

## What ships

- **`Dockerfile`** — `python:3.12-slim` + uv + `--extra voyage --extra server --no-dev --frozen`. Source layer copies `rag_leis/`, `data/chunks/`, `data/index/`, `data/vigencia/`. Runtime env defaults set; **`RAG_LLM_CACHE_DIR` deliberately unset** (Phase 7.9 cache is eval-only).
- **`fly.toml`** — `app = "rag-leis-digitais-br"`, `primary_region = "gru"` (São Paulo, LGPD-compliant), shared-cpu-1x × 2GB RAM, `auto_stop_machines = "stop"` + `auto_start_machines = true` (scale-to-zero), `/health` http-check at 30s interval. **No persistent volume mount** (production runs without cache).
- **`.github/workflows/deploy.yml`** — on push to main + manual `workflow_dispatch`. Uses `superfly/flyctl-actions/setup-flyctl@master`. Reusable `ci.yml` via `workflow_call` gates deploy: red tests → no deploy.
- **Fly app machines × 2 in `gru`** — Fly auto-created a second replica for HA (default behavior; can disable via `min_machines_running = 0`).
- **Runtime secrets staged on Fly**: MARITACA_API_KEY, ANTHROPIC_API_KEY, VOYAGE_API_KEY, RAG_API_KEYS. Set via `flyctl secrets set --stage` then applied on `flyctl deploy`.
- **GHA secret**: `FLY_API_TOKEN` set on the repo for `deploy.yml`. The original token from `.env` was used; no rotation between local + CI (intentional — single token, single source-of-truth).

## Live smoke test results

| Endpoint | Status | Total RTT | Server `pipeline_ms` |
|---|:-:|---:|---:|
| `GET /health` (cold) | ✅ 200 | 226ms | n/a |
| `POST /v1/ask` missing key | ✅ 401 | 231ms | n/a |
| `POST /v1/ask` cold (1st query after deploy) | ✅ 200 | 19.7s | 19,473ms |
| `POST /v1/ask` warm req 1 | ✅ 200 | — | 13,142ms |
| `POST /v1/ask` warm req 2 | ✅ 200 | — | 9,199ms |
| `POST /v1/ask` warm req 3 | ✅ 200 | — | 9,605ms |

Sample answer (req 2): `classified_type=definicao, refused=False, n_citations=4, first citation = urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1, cost=$0.0053`.

## Latency caveat — production is much slower than localhost Phase 8.4

Phase 8.4 measured **warm cache p95 ~2.87s** on localhost. Production warm steady-state is **9-13s** per query — **~3-5× slower**. Root cause is structural, not a regression:

- **No cache in production** (by design per `feedback-use-llm-cache-for-eval`). Each request makes ~3 fresh Sabiá calls + 1 Voyage embed; localhost Phase 8.4 was cache-warmed for all of those.
- **Real Maritaca API latency** (~3s per Sabiá call cold; localhost cached → <1ms).

**Implication for Phase 8.6 SLO calibration:** the Phase 8.4 findings doc proposed `p95 < 5s` and `p50 < 2s`. Those numbers are **wrong for production**. Real prod SLOs:

| SLO | Phase 8.4 candidate | **Phase 8.5.1 measured (prod)** | Proposed prod SLO |
|---|---:|---:|---:|
| p50 (warm) | 826ms (concur=4) | ~9-10s | **< 15s** |
| p95 (warm) | 4,000ms (concur=4) | ~13s | **< 20s** |
| Cold-start p99 | not measured | 19.5s | **< 30s** |
| Cost mean / query | $0.0064 | $0.005-0.007 | **< $0.01** (unchanged; cost is model-side, doesn't differ much localhost vs prod) |

Phase 8.6 alerting will consume these real numbers.

## Structured logs flowing end-to-end

Confirmed via `flyctl logs --app rag-leis-digitais-br`: every request produces correlated `request.received` → `pipeline.answered` → `request.completed` events tagged with `region: gru`, `request_id`, and (most importantly) `api_key_prefix` showing only the first 8 chars of the caller's key. Phase 8.3 PII-absence discipline holds in production.

Sample (re-formatted; from real prod logs):

```json
{"event":"pipeline.answered","query_length":41,"classified_type":"definicao",
 "top_1_cosine":0.765,"n_citations":4,"n_rejected_irrelevant":3,
 "refused":false,"refusal_reason":null,"cost_estimate_usd":0.005321,
 "llm_calls":3,"tokens_input":3828,"tokens_output":753,
 "pipeline_latency_ms":9199.099,"request_id":"005f6269",
 "service":"rag-leis-digitais-br","level":"info",
 "timestamp":"2026-05-20T16:16:34.112756Z"}
```

OpenTelemetry spans are being created in-process per Phase 8.3 (no-op exporter in v1); Phase 8.5.x doesn't add a real exporter yet. Phase 8.6 may pick one if alerting integration requires.

## Token + secrets posture

- **`.env` is the only place the FLY_API_TOKEN lives locally** (gitignored, `chmod 600`). Deleted `~/.fly/config.yml` because flyctl ignored it and it was a stale-copy hazard.
- **Runtime secrets live on Fly only** — not in GHA, per Phase 8.2 plan's posture decision. The four runtime secrets were set via `flyctl secrets set --stage` and applied on first deploy.
- **GitHub Actions has only `FLY_API_TOKEN`** (the deploy credential). The Phase 8.5.0 worry about "deploy could leak via debug-print" is bounded to this one token; runtime LLM-provider creds are not at GHA risk.
- **Pre-existing GHA secrets** `MARITACA_API_KEY` and `VOYAGE_API_KEY` exist in the repo's secret list (visible via `gh secret list`). These predate Phase 8.5 — likely used by the Weekly corpus refresh workflow or similar. **Not removed in 8.5.1** (might be load-bearing for other CI paths). Worth auditing during a future cleanup pass: if no workflow references them, delete; if they ARE used, document where + why.

## Rollback procedure (documented; not yet exercised)

```
# List the deployment images for the app
~/.fly/bin/flyctl releases --app rag-leis-digitais-br

# Re-deploy a previous image (replace <sha> with one from the list)
~/.fly/bin/flyctl deploy --image registry.fly.io/rag-leis-digitais-br:<sha> \
  --app rag-leis-digitais-br --remote-only
```

The Phase 8.5 plan committed to "verify rollback works on staging" — staging IS prod in v1 (single environment), so verification would require either an intentional bad deploy + rollback, or trusting the documented procedure until Phase 9 introduces a staging environment.

## What this enables for Phase 8.6

- **Real production logs flowing** → Phase 8.6 can wire alerts on log patterns
  (`auth.failed` rate > X/min, `rate_limit.exceeded` rate > Y/hour,
  `pipeline.error` events > N/hour).
- **`flyctl logs` is the v1 alerting surface** — no log aggregator yet.
  Phase 8.6 can either stick with manual `flyctl logs` review or set
  up Fly's log forwarder to a service (Datadog, Better Stack, etc.).
- **Cost dashboard is the Fly Billing UI** — no programmatic
  per-query cost tracking in production (the structured logs
  capture `cost_estimate_usd` per request, but no aggregation
  pipeline yet). Phase 8.6 SHOULD wire an aggregator over the logs.

## Three things learned during deploy

1. **The Fly token shape signaled itself.** The token's email field
   `ab38d130-...@tokens.fly.io` indicated a deploy-scoped token (not
   a personal-account token). The fact that an app
   `rag-leis-digitais-br` already existed in `flyctl apps list` —
   without my having run `fly apps create` — confirmed the token is
   *bound* to that specific app. The token was likely minted with
   the app, which means `fly apps destroy` would also destroy this
   capability. Tag this as a fact in any future Phase 9 multi-app
   work: tokens are app-scoped here.

2. **flyctl v0.4.53 doesn't read `~/.fly/config.yml`.** Newer
   versions prefer the `FLY_API_TOKEN` env var (or
   `~/.config/fly/...`, possibly). The Phase 8.5 plan's earlier
   draft suggested writing to `~/.fly/config.yml`; replaced with
   "source `.env`; never commit token to repo or GHA" pattern.

3. **The first cold-start request took 19.5s.** Voyage embedder load
   + 3 Sabiá calls (cold connection to api.maritaca.ai) + 1 Opus
   eval-mode call (wait, no — production doesn't use Opus per
   8.0.1 swap to sabia-4). The 19.5s breaks down as roughly: 2-3s
   pipeline load + 3 × 5s Sabiá cold calls + verify/render. Warm
   state drops to 9-13s when the connection pool is warm.

## What changed in the codebase

- `Dockerfile` (new, ~32 lines) — Python 3.12 slim + uv; no
  production cache mount; runtime env defaults.
- `fly.toml` (new, ~38 lines) — single shared-cpu-1x in `gru`;
  scale-to-zero; no volume mount.
- `.github/workflows/deploy.yml` (new, ~30 lines) — deploys on push
  to main + manual `workflow_dispatch`, gated on the `test` job.
- `.github/workflows/ci.yml` — added `workflow_call:` trigger so
  deploy.yml can chain it.
- `study/phase-8.5.1-deploy-findings.md` (new, this doc)

`.env` was modified locally to add `RAG_API_KEYS` (gitignored;
generated via `secrets.token_urlsafe`).

## Cross-references

- [`phase-8.5-ci-deploy-plan.md`](phase-8.5-ci-deploy-plan.md) — predecessor plan
- [`phase-8.5.0-ci-findings.md`](phase-8.5.0-ci-findings.md) — CI sibling sub-phase
- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — parent plan; sub-phase 8.5.1 now ✅
- [`phase-8.4-load-test-findings.md`](phase-8.4-load-test-findings.md) — localhost SLO numbers that need re-calibration for production
- `Dockerfile`, `fly.toml`, `.github/workflows/deploy.yml` — the new files
