# Backlog

Itens identificados mas não-aplicados — pra retomar quando for prioridade.

## 📌 State snapshot (2026-05-17, post-Phase 7.5)

**Phases completed:**
- ✅ Phase 0 (parser foundations, dedup logging, cache)
- ✅ Phase 1 (TIER_1+TIER_2 corpus)
- ✅ Phase 2 (RAGPipeline + cite-and-verify + answer-eval v0)
- ✅ Phase 3 (vigência overlay + Lei 9.507 + Decreto cross-test)
- ✅ Phase 4 (LLM provider abstraction; Sabiá-3.1 vs Sonnet-4-5 cross-validation; PII redactor; query-type classifier; ANPD pdfplumber parser; Tier-3)
- ✅ Phase 5 (legal_rank + hierarchy_warning; prose-citation check + retry; source-as-of-date; EC linkage; OOS subtype taxonomy a-e)
- ✅ Phase 6 (Tier-4 jurisprudência v0: 7 chunks; URN spec §9.5)
- ✅ Phase 7 (production infra: SHA-256 diff + F5 WAF strip + parser §-suffix/inc-suffix fixes + title-prefix default + orchestrator with gate+rollback + GitHub Actions weekly cron + smoke + runbook)
- ✅ **Phase 7.5 (eval expansion — closed 2026-05-17)** — see [`study/phase-7.5-findings.md`](study/phase-7.5-findings.md). 6 of 7 sub-steps shipped (7.5.6 LGPD manual deferred to D7 lawyer engagement). Eval surface grew 45 → 139 rows (+209%). Headline finding: **internal OOS refusal accuracy of 93.8% overstated external measurement (12.2%) by 6.7×** — selection bias quantified.

**Phases pending (large blocks):**
- ⏸ Phase 8 — hosting/API/observability ([entry plan](study/phase-8-entry-plan.md), drafted 2026-05-19). **Refusal-discipline prerequisite met** (Phase 7.8 gate cleared at 0.633 = 5.2× lift); SRE Golden Signals already instrumented (Phase 7.5.7). Plan decomposes into 7 sub-phases (8.0 → 8.6).
  - ✅ **8.0 prod cost baseline** ([findings](study/phase-8-0-prod-cost-baseline.md)) — measured: cost mean $0.0064/query answered, latency p95 ~2.87s fresh, error rate 0.0%. SLO candidates re-anchored from eval-mode estimates.
  - ✅ **8.0.1 sabia-3.1 vs sabia-4 A/B** ([findings](study/phase-8-0-1-sabia-3.1-vs-4-findings.md)) — sabia-4 wins on all 3 pre-locked criteria. **Production default swapped to sabia-4** (rag_leis/maritaca.py:48, 2026-05-19). Key fix: row 12 / Decreto 8.771 false-refusal that sonnet-4-5 AND sabia-3.1 both missed; sabia-4 joins opus on the right side. +5 net OOS catches (6 wins, 1 leak — "Patrícia tax" row).
  - ✅ **8.1 HTTP harness** ([commit `921f58a`](../../../commit/921f58a)) — `POST /v1/ask` + `GET /health` + OpenAPI; 10 new tests; smoke-tested live server.
  - ✅ **8.2 auth + rate limit** ([plan](study/phase-8.2-auth-rate-limit-plan.md), [findings](study/phase-8.2-auth-rate-limit-findings.md)) — `X-API-Key` against `RAG_API_KEYS` env-var (multi-key for rotation), constant-time compare, fail-closed. `slowapi` token bucket, 60 req/min/key default (configurable). 429 emits `Retry-After` + `X-RateLimit-*` headers. Health + OpenAPI exempt. 10 new tests; 458 total passing. Known limitation: 200 responses lack `X-RateLimit-*` headers due to slowapi/FastAPI response_model interaction — tracked as Phase 8.3 follow-up.
  - ✅ **8.3 structured observability** ([plan](study/phase-8.3-structured-observability-plan.md), [findings](study/phase-8.3-structured-observability-findings.md)) — `structlog` JSON logs (`request.received` → `pipeline.answered` → `request.completed`); `X-Request-ID` correlates them; OpenTelemetry spans at request boundary + 5 inner pipeline phases (no-op exporter for v1; real exporter is 8.5 deploy work). Auth/rate-limit events emit `auth.failed` and `rate_limit.exceeded` with key prefixes (never full keys). 200 responses now carry `X-RateLimit-*` headers via new `RateLimitHeadersMiddleware` (resolves Phase 8.2 known limitation). 10 new tests including PII-absence assertions. 468 total passing.
  - ✅ **8.4 load test + capacity** ([plan](study/phase-8.4-load-test-plan.md), [findings](study/phase-8.4-load-test-findings.md)) — asyncio + httpx harness; full sweep 1→64 concurrency completed; **0% error rate at every level through 64 concurrent**. p50 scales ~linearly with concurrency (204ms → 20.9s); QPS plateaus at ~3-4 (per-request work is the bottleneck, not handler capacity). No catastrophic knee — degrades gracefully. Calibrated SLO numbers for Phase 8.6: alert if p95 > 5s, p50 > 2s, error rate > 1% (5min windows). Two sweep archives capture cold-cache (cache-warming-during-test) AND warm-cache (server-only capacity).
  - ⏳ **8.5 CI + deploy pipeline** ([plan](study/phase-8.5-ci-deploy-plan.md))
    - ✅ **8.5.0 CI workflow** ([findings](study/phase-8.5.0-ci-findings.md)) — `.github/workflows/ci.yml`: pytest (446/468 tests, excludes `network` + `requires_anpd_pdf`) + ruff on every PR/push to main. Used the codebase's existing `@pytest.mark.network` marker rather than introducing a new one. Concurrency cancellation on same-ref. **Branch protection rule still requires one-time manual setup** via repo Settings.
    - ✅ **8.5.1 Fly.io deploy** ([findings](study/phase-8.5.1-deploy-findings.md)) — service live at **https://rag-leis-digitais-br.fly.dev** in region `gru` (São Paulo, LGPD-compliant). Shared-cpu-1x × 2 replicas (Fly's default HA), scale-to-zero via `auto_stop_machines`. No production LLM cache mount (cache memory rule). Runtime secrets staged on Fly via `flyctl secrets set`; only FLY_API_TOKEN in GHA. `.github/workflows/deploy.yml` gates on `ci.yml` via `workflow_call`. **Latency caveat:** production warm steady-state is 9-13s (vs 2.87s localhost Phase 8.4 measurement) — Phase 8.6 SLOs need re-calibration against real prod numbers.
  - ✅ **8.6 cost ceiling + Slack alerting** ([plan](study/phase-8.6-alerting-plan.md), [findings](study/phase-8.6-alerting-findings.md)) — three-layer design implemented: (1) provider-side hard caps on Anthropic/Maritaca/Voyage (operator dashboard config; recommended values in findings), (2) `scripts/phase_8_6_alert_check.py` polls Fly structured logs every 15 min via GHA cron (`.github/workflows/alerts.yml`), computes rolling p50/p95/p99 + error rate + cost-mean + auth-by-IP, POSTs to Slack on breach, (3) Slack App Incoming Webhook (NOT the deprecated custom-integrations form). Min-sample guards (≥10 req for percentiles, ≥5 for rate) prevent single-request paging. Stateless — duplicates across runs are intentional. 17 tests; verified end-to-end via `workflow_dispatch -f test_alert=true` → message landed in Slack channel. **Phase 8 fully closed.**
- ⏸ Phase 9 — compliance / lawyer review (depends on D7 contracting); Phase 7.5.6 (LGPD manual curation) folded into D7 scope. **Runs in parallel with Phase 10**; gates only Phase 10c.
- ⏳ **Phase 10 — User-facing UI** ([entry plan](study/phase-10-ui-entry-plan.md))
  - ✅ **10.0 streaming endpoint** ([findings](study/phase-10.0-streaming-endpoint-findings.md)) — `POST /v1/ask/stream` ships SSE with stage events. Pipeline `answer()` gains optional `on_event` callable; backwards-compatible. Same auth + rate limit as `/v1/ask`. 5 new tests. Smoke-verified against deployed instance: warm path streams in real-time, first event in 0.2s. **Cold-start adds ~19s to first-of-day traffic** (auto-stopped machine wakeup). **Phase 8.6 p95 alert threshold needs relaxing to 25-30s** — including `relevance_judge`, true warm p95 is ~20s, calibrated almost exactly at the alert threshold. **10.0.1** (token-by-token within `generate`) deferred — ships if 10a/b shows the 8s `generate` gap is the load-bearing UX issue.
  - ✅ **10a/10b — public demo** ([findings](study/phase-10b-public-demo-findings.md)) — UI live at **https://rag-leis-ui.fly.dev**. 10a implemented in-line with 10b (built locally → smoke → deploy as 10b). Astro 5 + Node SSR adapter, separate Fly app `rag-leis-ui` in `gru`, `min_machines_running=1`. Server-side proxy at `/api/ask/stream` holds the demo API key (never reaches browser). Single chat page, BR-Portuguese, stage progress indicator, citations as LexML URN links, refusal handling with sympathetic copy, mobile-responsive, dark-mode-aware, no tracking. **Backend `fly.toml` also updated to `min_machines_running=1`** — a warm UI doesn't help if the backend is cold. Cost ~$19/mo total.
  - ✅ **10c v1 — per-user conversation history** — Shipped 2026-05-22. JWT-authenticated `/v1/ask` persists each turn into the Phase 11.2.1 schema (`users` + `conversations` + `conversation_messages`). New endpoints `GET /v1/conversations` + `GET /v1/conversations/{id}` (Clerk-session-gated, owner-scoped — 404 on owner mismatch, no leak). Hostile-supplied `conversation_id` from another user is silently rotated server-side, never bled into the owner's history. UI: sidebar grouped by recency (Hoje / Ontem / Esta semana / Este mês / Antes) on `rag.nunes.work`; `?c=<uuid>` SSR-renders past Q+A inline; "+ Nova conversa" → `/`. API-key callers (CI smoke tests, MCP) keep working with no persistence (no users row to scope under). 8 backend tests (repo + endpoints, skip cleanly without DATABASE_URL_TEST). Closes `study/lawyer-review-checklist.md` item that's deferred to Phase 9 lawyer review for retention/LGPD blessing.
  - ⏸ **10c.1 — conversation deletion + retention** — User-facing DELETE endpoint + auto-delete after N days. Hard-gated on Phase 9 lawyer review (retention policy is theirs to set). Drop after operator hears back from D7.
  - ⏸ **10c.2 — LLM-generated conversation titles** — Replace the naïve "first-60-chars-of-redacted-query" title with a 1-LLM-call summary. Skipped in v1 to avoid the cost+latency overhead before product-market-fit signal warrants it.
  - ✅ **10d — multi-turn RAG** — Shipped 2026-05-23. Implementation chose rewrite-then-classify (per Phase 17.2 contract). `rewrite_for_classification` in `rag_leis/query_type.py` is now an LLM-backed function (Maritaca sabia-4, ~$0.0003 + ~250ms per non-first turn; first turn short-circuits with zero cost). Pipeline integration: `RAGPipeline.answer(query, prior_turns=...)` accepts optional context; rewriter fires before classifier, original-redacted query stays on `RAGAnswer.pii_redacted_query`, rewritten form on new `RAGAnswer.rewritten_query` field. Server: `/v1/ask` + `/v1/ask/stream` load prior turns from Postgres when `conversation_id` is supplied + caller is Clerk-authed (silent rotation on foreign id; defensive fallback to empty on DB hiccup). Log lines stamp `was_rewritten` + `n_prior_turns` for observability. Eval: `scripts/phase_10d_conversation_eval.py` against `eval/conversation_queries.yaml` — **10/10 pass on first prod-equivalent run** (sabia-4 rewriter) covering classify-match + OOS-shape-preservation + topic-shift-drop. 21 unit tests in `tests/test_query_rewriter.py`. UI unchanged (Phase 10c already sends `conversation_id`).
  - ⏸ **14.1 — pii_audit_id cross-reference** — `conversation_messages.pii_audit_id` FK currently NULL in v1. Wire it to the matching `pii_audit_log.id` so per-turn redaction events are joinable from history. Schema already supports it; needs returning the inserted audit-log id from `pii_audit.write_audit` + threading it through `RAGAnswer`.
  - ⏸ **10b.1** (optional) — CI-based deploy workflow for `rag-leis-ui`. Needs new app-scoped deploy token via `flyctl tokens create deploy --app rag-leis-ui` → GHA secret `FLY_API_TOKEN_UI`. Currently UI redeploys are manual.
  - ✅ **11.2.1 — Postgres-backed persistence** — Neon Postgres in BR region (`sa-east-1`, São Paulo) replaces ephemeral JSONL writes. Migrated `proposals` + `merged_proposals` + `pii_audit_log` (the latter was a silent ephemeral-storage bug). Added `users` / `conversations` / `conversation_messages` tables as schema-only stubs for Phase 10c. Stack: `psycopg v3` + `psycopg_pool` + `alembic` for migrations (run from FastAPI lifespan). Backwards-compatible: legacy JSONL backends kept for eval CLI + tests. Tests skip cleanly if `DATABASE_URL_TEST` isn't set. Shipped 2026-05-21 in `04a73bd` + `0f9670d` (Dockerfile fix for missing `migrations/` COPY) + `85e183c` (psycopg-v3 driver fix in alembic env).
  - ✅ **11.4 — operator merge tool** — `scripts/phase_11_4_merge_proposals.py` reads pending proposals from Postgres, prompts the operator [a]ccept/[r]eject/[s]kip/[q]uit, applies accepts to `eval/queries.yaml` via ruamel.yaml (preserves comments + structure), marks merged via `proposals.mark_merged()`. Supports `kind=review` + `kind=new_row` + `kind=refinement` (promotes refinements to new eval rows reusing the captured retrieval URNs). Operator-only CLI runs locally with DATABASE_URL pointing at Neon prod. 16 unit tests cover the YAML-edit logic without DB hit. Shipped 2026-05-21.
  - ✅ **11.3 — inline query refinement** — Lawyer reviewing a row can open a refinement panel, type an alternate phrasing, and see which top-k chunks the retriever returns (with gold-URN matches highlighted in green). New endpoint `POST /v1/admin/eval/queries/{id}/refine` runs retrieval-only (no full pipeline, no LLM spend — ~$0.0001 per call with Voyage). Optionally writes a `kind=refinement` Proposal; the Phase 11.4 merge tool promotes accepted refinements to new eval rows. UI: collapsible section on `/queries/[id]` with side-by-side compare (gold URNs vs retrieved URNs, color-coded by match). 7 new endpoint tests (4 auth/validation, 3 happy-path skip-if-no-db). Shipped 2026-05-21.
  - ⏸ **10.0.1** (optional) — token-by-token streaming WITHIN `generate` (shrinks the worst ~7s blank gap). Only if 10b feedback says the gap is the load-bearing UX issue.

  Stack picks: **Astro on Fly `gru`** (LGPD region-pinning works; Vercel default-region doesn't honor BR). Auth: single-key (10a) → ephemeral (10b) → magic-link/OAuth (10c).

- ⏸ **Phase 11 — Internal review UI** ([plan](../../.claude/plans/curried-humming-hellman.md)) — Astro app at `review.nunes.work`, Clerk + GitHub OAuth, region `gru1`. Lawyer audits the 139 eval queries + gold URNs; operator promotes refined queries into the eval set. Proposals land in `data/review/proposals.jsonl` (append-only, gitignored); operator merges via `scripts/phase_11_merge_proposals.py` into `eval/queries.yaml` (PR-style). Backend gains `/v1/admin/*` endpoints with Clerk JWT verification + email allowlist. **Five sub-phases (11.0-11.4); ship order 11.0 → 11.1 → 11.2 → 11.4 → 11.3.** Cost ~$5-10 in API spend + $0 infra (existing Vercel Pro + Fly cover it) + Clerk free tier.
- ✅ **Phase 12 — Vigência review UI** — corpus-browser surface for the lawyer to fill `data/vigencia/overlays.yaml` gaps. Shipped 2026-05-21 in a single vertical slice: schema migration (Alembic 0002 adds `kind="vigencia"` + 5 vigencia_* columns to `proposals`), four backend endpoints (corpus/documents listing, corpus chunks paginated walker, vigencia/overlays read, vigencia annotation submit), 9 new tests, UI (`/vigencia` document picker sorted by coverage % ascending + `/vigencia/[doc]` chunk walker with inline annotation form), nav-link in Layout, merge tool (`scripts/phase_11_4_merge_proposals.py`) extended to handle `kind="vigencia"` → writes to `data/vigencia/overlays.yaml` with replace-in-place if URN already overlaid. Closes 🔴 blocker #1 from `study/lawyer-review-checklist.md` (vigência coverage was 12/15000+ chunks; now the lawyer has a UI to grow it).
- ✅ **Phase 13 — Hierarchy-masking review UI** — Shipped 2026-05-21 in a single vertical slice: alembic 0003 (kind='hierarchy' + columns hierarchy_query / hierarchy_flagged_urns / hierarchy_top_rank), one backend endpoint `POST /v1/admin/hierarchy/probe` (retrieval-only, annotates each chunk with legal_rank 1-5 + rank_name), `/hierarchy` UI page (query input + RUN PROBE button + result list with rank-colored borders + flag checkboxes + submit-as-proposal form), 6 endpoint tests, 3 merge-tool tests. Merge tool extended: `kind=hierarchy` accepts append to `data/hierarchy/flagged.yaml` (new audit-log file; informational only — nothing in the pipeline reads it). Closes 🔴 blocker #2 from `study/lawyer-review-checklist.md` (hierarchy masking). **Bonus fix**: caught pre-existing latent bug in Phase 11.3 refine endpoint where `chunk.citation` / `chunk.nav_text` referenced wrong attribute names (should be `.label` / `.nav` on ChunkSummary); fixed in the same commit. **Test infrastructure fix**: env_config fixture switched from `monkeypatch.delenv("CLERK_AUDIENCE")` to `monkeypatch.setenv("CLERK_AUDIENCE", "")` so transitive `load_dotenv(override=False)` calls (triggered by `rag_leis.llm` module-import-time) can't repopulate the audience mid-test.
- ✅ **Phase 14 — PII redactor audit UI** — Shipped 2026-05-21. Vertical slice: alembic 0004 (kind='pii_miss' + pii_audit_log_id FK + pii_missed_types TEXT[]), two backend endpoints (`GET /v1/admin/pii/audit` paginated list + `POST /v1/admin/pii/audit/{id}/flag` submit), `/pii` UI page with audit cards + categorized checklist (covered-by-regex vs gap-categories: OAB, CRM, processo SEI, processo CNJ, eleitoral, NIS, PIS, IBAN, cartão de crédito) + notes textarea, capture-phase form handler. 7 endpoint tests + 3 merge tests. Merge tool handles kind=pii_miss → `data/pii/missed.yaml` (informational; operator reviews to add regex patterns to `rag_leis/pii.py`). Closes 🟡 #6 from `study/lawyer-review-checklist.md`.
- 🔬 **Phase 15 — Brazilian-native identity (exploration)** ([breakdown](study/phase-15-br-native-identity-exploration.md)) — research integration of **gov.br** (federal citizen identity, OIDC, verified CPF, LGPD-perfect residency) and **e-OAB** (active-OAB-lawyer verification via ICP-Brasil certificate) as alternatives/complements to Clerk's Google + GitHub OAuth. Output of this phase: a go/no-go recommendation for each, with measured approval-process timelines, technical-feasibility notes, and a cost+complexity-vs-LGPD-posture tradeoff matrix. **Doesn't ship code** — exploration only. Build phase (if approved) becomes Phase 15.1+. Dependencies / consumers: Phase 10c (public user accounts), where these would actually be integrated; Phase 9 (lawyer review may bless or block).
- ⏳ **Phase 16 — Freshness + truth (post-round-3 P0)** ([roadmap](study/phase-16-19-roadmap.md)) — closes the two convergent P0 findings from `REVIEWER_NOTES_3.md` (engineering) + `REVIEWER_NOTES_4.md` (legal). Four items, ~1.5 operator-days, no lawyer dependency: (16.1) persist `fetched_at` in metadata sidecars so the production footer stops reporting the Docker build date; (16.2) extend vigência taxonomy with `alterado_por_jurisprudencia` + `proxima_revisao`, update MCI art. 19/21 entries to reflect Tema 987's 2024-06-26 julgamento; (16.3) filter Tier-4 `PENDENTE_*` stubs from retrieval + comment out the eval rows that pin them as gold; (16.4) expose `RAG_SCOPE_CHECK_ENABLED` / `RAG_RELEVANCE_GATE_ENABLED` / `RAG_RELEVANCE_JUDGE` in `_build_pipeline_from_env`. **Theme: the system was asserting currentness claims it couldn't back; this fixes the claims + installs the loop that keeps them current.**
- ✅ **Phase 17 — Multi-turn primitives (pre-10d)** ([roadmap](study/phase-16-19-roadmap.md)) — six items, all shipped 2026-05-22. (17.1) nightly refusal-discipline canary GHA at `04:30 UTC`, gates on `oos_refusal_recall ≥ 0.55` + `false_refusal_rate ≤ 0.02`, Slack-alerts on failure; (17.2) classifier contract for multi-turn — chose rewrite-then-classify; contract + stub in `rag_leis/query_type.py`, 10-row conversation eval in `eval/conversation_queries.yaml`; (17.3) `load_dotenv()` moved out of module-import in `llm.py`+`maritaca.py`, replaced by `tests/conftest.py` and the existing entry-point calls — Phase 13 `setenv("","")` workaround dropped; (17.4) provider-aware tool-use retry (n=1) via `complete()`+JSON-mode parse, `last_call_used_fallback` propagated through `RAGAnswer.tool_use_fallback_count` → AskResponse + `pipeline.answered` log lines; (17.5) `DEFAULT_OOS_THRESHOLD` calibrated 0.40 → 0.425 via sweep on legalbench_br_oos (n=49) + queries.yaml (n=102); study doc at `study/phase-17.5-oos-threshold-calibration.md`; (17.6) `regulamentation_target` registry covers Decreto 8.771/2016 + ANPD Res. 4/2023 + ANPD Res. 15/2024; SYSTEM_PROMPT rule 7 closes the orphaned-regulamento false-refusal structurally. **Phase 10d gate is now open** — multi-turn classifier contract documented, eval set committed, refusal-discipline canary watching for regression.
- ⏳ **Phase 18 — Corpus + cross-doc gold expansion** ([roadmap](study/phase-16-19-roadmap.md)) — five items, ~2.5 operator-days + 0.5 intermittent lawyer-days. **✅ (18.1) Tier-1/Tier-2 expansion — LC 105/2001 (sigilo bancário, 89 chunks, Tier-1), Lei 12.414/2011 (Cadastro Positivo, 108 chunks, Tier-1), Decreto 10.474/2020 (ANPD estrutura regimental, 269 chunks, Tier-1 + `regulamentation_target` → Lei 13.853/2019), ECA Lei 8.069/1990 scope-limited to arts 17-18/78/240-241-E (31 chunks, Tier-2 via `scripts/filter_eca_digital_arts.py`). Corpus 7201 → 7688 chunks; retrieval metrics stable (nDCG@10 0.7154→0.7143). Shipped 2026-05-22.**; **✅ (18.2) manual transcription of Res. CD/ANPD 1/2021 + 2/2022 arts 1-15 (the operative core) — gov.br HTML source (cleaner than the 274-917pg SEI PDF bundle the Phase 4.3 path required), 64 + 48 chunks via `scripts/phase_18_2_transcribe_anpd_res.py`, source=`manual-transcription-anpd-html-v1`. Both added to TIER_3 + `regulamentation_targets.json` (both regulamentam LGPD via art. 55-J). Side fix: corrected the Phase 17.6 evidence field for Res. 15/2024 which incorrectly described it as public-sector treatment — re-reading the chunk text proved it's the incident-notification regulamento (art. 1 verbatim). Shipped 2026-05-22.**; **✅ (18.3) habeas data gold expansion — verified 2026-05-22 that Lei 9.507 arts. 2/4/7/7~inc{1,2,3}/8 are already in `eval/answer_queries.yaml:108-114` `alternative_acceptable_urns` (shipped in Phase 3.2 originally). Roadmap entry was stale.**; **⏳ (18.4) cross-doc gold drafts ready — `eval/answer_queries_cross_doc_drafts.yaml` carries the 5 scenarios (vazamento de consumidor / direito ao esquecimento / dados de crianças / notificação de incidente / dosimetria de sanções); `AnswerQuery` schema extended with `companion_urns: tuple[tuple[str, str], ...]` + validated `relationship` ∈ {regulamenta, integra, contradiz, complementa}. Drafts loaded by the loader (not by default eval run — separate file). Per-row review checklist at `study/phase-18.4-cross-doc-gold-drafts.md`. Awaiting intermittent lawyer attention to bless rows + merge into `answer_queries.yaml`. Operator-side prep shipped 2026-05-22.**; **✅ (18.5) PII redactor regex for OAB / CRM / processo CNJ / título eleitor — `rag_leis/pii.py` gains 4 patterns (anchored on prefix tokens or distinctive punctuation so zero bare-digit overmatch); 14 new tests in `tests/test_pii.py`. Drains Phase 14 audit findings for the 4 highest-frequency lawyer-query identifier shapes. Shipped 2026-05-22.**.
- ⏸ **Phase 19 — D7 lawyer-gated work** ([roadmap](study/phase-16-19-roadmap.md)) — gated on D7 lawyer engagement. (19.1) verbatim STF Tema 987 tese transcription + un-flag from Phase 16.3's exclusion list; same for 533/815 if/when teses fix; (19.2) "judicial-acceptable" precision tier (`judicial_acceptable_urns` annotation + eval re-run) — the headline metric for any production claim; (19.3) quarterly vigência overlay audit cadence (pass 1 over existing 12 entries via Phase 12 UI); (19.4) hierarquia warning suppression when `kind=jurisprudencia` merely supports a higher-rank cite. ~1.5 operator-days + ~2 lawyer-days. Don't start before D7 contracting — produces rework otherwise.

**Corpus current:** ~7800 chunks across 4 tiers (16 Tier-1 + 5 Tier-2 + 4 Tier-3 + 7 Tier-4). Phase 18.1 (2026-05-22) added LC 105/2001 + Lei 12.414/2011 + Decreto 10.474/2020 (full, Tier-1) and ECA Lei 8.069/1990 (scope-limited to arts 17-18/78/240-241-E, Tier-2 via `scripts/filter_eca_digital_arts.py`). Phase 18.2 (2026-05-22) added Res. CD/ANPD 1/2021 + 2/2022 arts 1-15 (Tier-3 via `scripts/phase_18_2_transcribe_anpd_res.py`).

**Eval current (post-Phase 7.5):** 104 retrieval queries + 29 internal answer queries + 16 concurso pilot + **49 legalbench OOS + 40 legalbench rule recall + 5 oab-bench discursive** = 243 total eval rows.
- Production retrieval: nDCG@10=0.7235, MRR@10=0.7996 (unchanged from pre-7.5 — no corpus/embedder change)
- **External rule recall (citation precision):** 97.5% (40 rows)
- **External OOS refusal:** 12.2% (49 rows) — **the headline refusal-discipline gap**
- **External discursive (OAB 2ª fase):** 54% mean (5 rows, bimodal — confirms gap)
- **Latency p50/p95:** 6.8s / 13.5s (first instrumented 7.5.7)
- **Cost per query:** $0.075 discursive / ~$0.002 short-answer (judge cost now correctly attributed)

**Gold-standard metrics audit** (full at `study/rag-eval-metrics-audit.md`, post-Phase 7.5):
- **22** ✅ Covered (was 17; +4 from 7.5.7 SRE; +1 rule recall external; +1 from 7.5.1 false_refusal_rate row-20 reconciliation; +1 from 7.6.1 Answer Relevance via judge_explanation_quality)
- **8** 🟡 Partial
- **9** ❌ Missing (claim-level Context Recall, provider availability/fallback, throughput QPS, jailbreak resistance, cache hit rate first-class, citation entailment, MAP, Recall@100, LegalBench external anchor)
- Top remaining ROI gaps: (1) RAGAS Answer Relevance ~1d; (2) refusal-discipline SYSTEM_PROMPT iteration (NEW priority from 7.5 findings); (3) LegalBench US adaptation (future external anchor).

---

## 🎯 Query expansion (post-pilot, post-audit) — ✅ MOSTLY COMPLETE via Phase 7.5

**Full plan:** [`study/query-expansion-plan.md`](study/query-expansion-plan.md).
**Findings:** [`study/phase-7.5-findings.md`](study/phase-7.5-findings.md).

**Status:** Sub-phases A (legalbench OOS), B (rule recall), C (oab-bench discursive) all shipped via Phase 7.5.3/4/5. Sub-phase D (OAB 39-44 LGPD manual) deferred to D7 lawyer engagement per Phase 7.5 closure rationale.

**Why:** Concurso pilot (2026-05-17) exposed that internal answer-eval refusal_accuracy (93.8%) overstates production behavior by ~31pp — real external queries hit 62.5%. Plus our OOS coverage is too small (15 internal + 9 pilot = 24) for tight CI. Plus no LGPD-rich queries despite LGPD being core to our corpus pitch.

**Datasets identified** (web search 2026-05-17, all post-2020 except eduagarcia):

| Dataset | Records | License | Use case |
|---|---|---|---|
| `eduagarcia/oab_exams` | 2210 MCQ 2010-2018 | public OAB | ✅ already used |
| `maritaca-ai/oab-bench` v2 | 105 discursive 2023-2024 | Apache-2.0 | ✅ post-LGPD, has ≥1 explicit LGPD |
| `celsowm/legalbench.br` | 1000, 4 task types | CC BY-SA 4.0 | ✅ BR-native, 72 rule-recall + 285 classification |
| `celsowm/simulado_oab` | 1010 MCQ 2025 | unspec | ❌ grok3-generated, discard |
| Rabula (FGV) | 1201 criteria | TBD | ⏸ paper at CEUR-WS Vol-4089, dataset URL not yet located |

**4 sub-phases ordered by ROI (detail in study doc):**

- **A. legalbench.br OOS expansion** (~2h eng + ~$1.50 API) — sample 30-50 from `text_classification` task, areas outside our corpus. Tightens refusal accuracy CI from ±15pp to ±5pp.
- **B. legalbench.br rule recall as external citation eval** (~3h + ~$1.50) — 30-50 rows where `answer="Art. N, CF/88"` mapped to our URN scheme. Adds defensible external `rule_recall_precision` metric.
- **C. oab-bench discursive subset** (~4-5h + ~$3-5) — 10 questions including the LGPD one. First discursive measurement; needs new LLM-judge against external rubric (RAGAS-extension style).
- **D. OAB 39-44 manual LGPD curation** (~4-6h human + ~$1 API, deferred) — only path to LGPD-rich eval; manual extraction from official OAB PDFs. Defer until A-C signal warrants.

**Expected outcome:** OOS test surface grows ~24 → ~60-75 rows; new external citation metric exists; first discursive eval baseline; LGPD coverage starts being measured separately.

---

## 🧪 Graph RAG concepts — Phase 7.6 closure (2026-05-19)

**Source:** [`study/paper-evaluation-graph-rag-2025.md`](study/paper-evaluation-graph-rag-2025.md) evaluating Springer 2025 ["A Graph RAG Approach to Enhance Explainability in Dataset Discovery"](https://link.springer.com/article/10.1007/s41019-025-00313-x). Three 🟢 GO concepts entered the BACKLOG; Phase 7.6 shipped two of them.

**Phase 7.6 outcomes:**

- ✅ **#3 — Explanation-quality eval dimension** (Phase 7.6.1, [findings](study/phase-7.6.1-explanation-quality-findings.md)) — shipped 2026-05-19. Closes audit Gap #4 (RAGAS Answer Relevance, now ✅). Headline: on internal eval, coherence=4.93/5 and quality=5.00/5 are nearly saturated; **compactness=3.57/5 is the discriminating axis** — answers are faithful but bloated. New diagnostic the project didn't have.
- ✅ **#2 — Per-document scope tags** (Phase 7.6.2, [findings](study/phase-7.6.2-scope-tags-findings.md)) — shipped 2026-05-19. Production-default-on (`RAGPipeline.scope_check_enabled=True`). **Negative gate result:** moved oos_a_refusal_rate from 0.122 → 0.184 (+0.062pp); gate threshold was +0.10pp. Real but underpowered signal. false_refusal_rate stayed at 0.000 — mechanism is conservative + correct. Kept in production because it adds +0.04 attributable refusal lift with no regression cost.
- ❌ **#1 — Static legal concept KG** — **PARKED in [EXPERIMENTS.md](EXPERIMENTS.md)** per D3 decision (negative gate result). The cheap version (#2) is underpowered for the same reason the expensive version would be — vocabulary needs D7 lawyer-reviewed depth, which makes #1 a Phase 9 project, not Phase 7.6.

**Net signal change from Phase 7.6:** audit Gap #4 closed; eval surface gained a new dimension (compactness); production pipeline gained a conservative scope-check that adds +2/49 OOS refusal cases.

**Phase 8 entry priority unchanged:** refusal-discipline SYSTEM_PROMPT iteration vs `eval/legalbench_br_oos.yaml` remains the load-bearing path. The 7.6.2 scope-check is a complementary +0.04 contribution; SYSTEM_PROMPT iteration is the path to the remaining 0.66 of the gap.

---

## ⚠️ Pre-launch dependency: lawyer review

Antes de Phase 9 (compliance) acontecer, há trabalho de validação
jurídica externa acumulando. Lista priorizada está em
**`study/lawyer-review-checklist.md`** — referência canônica desse
escopo. Inclui:

- 🔴 Bloqueadores: hierarquia normativa quando fontes secundárias
  mascaram primárias (ex: row 7 sanções), vigência overlay
  insuficiente, cross-doc gold incompleto
- 🟡 Importantes: 3rd precision tier, OOS adversariais, PII coverage
- 🟢 Refinamentos: citation prose check, source-as-of-date

D7 do `study/post-review-plan.md`: "vou conseguir antes de Phase 9 mas
não agora". Quando contratar, esse doc é o handoff list.

## Eval / gold

- **Revisar gold da query Tier-2 [T8] cross-doc** — "interação digital com o governo: proteção de dados e princípios". Proposta original em `eval/tier-2-queries-proposal.md` listava core = `14129 art.3 inc17` + `LGPD art.6` + `LGPD art.6;inc7`, supporting = `LGPD art.46` + `14063 art.5`. Cross-doc Tier-1×Tier-2 precisa validação manual: a query é abrangente e o gold pode estar incompleto (mesma classe de queries onde [13] foi corrigido em sessão anterior). Aplicar T1-T7 sem este, voltar com revisão dedicada.

- ✅ **DONE 2026-05-16** — ~~Investigar 597 dedups silenciosos no parser CF~~ — `_dedup_keep_last` warning era sintoma de dois bugs: **§-suffix** (Lei 14.155/21 §2-A/§4-B do CP perdidos) e **inciso-suffix** (CF art.92 inc I-A=CNJ, II-A=TST + art.93 VIII/VIII-A/VIII-B + LGPD art.55-C V-A/V-B perdidos). Ambos fixados via regex extension `(?:[-–]([A-Z])(?=[.\s,;:]|$))?` + alternation com mandatory separator. Ver memória `project-parser-bug-dedup` + commits `0effdc8` (§-suffix) + `796b179` (inc-suffix).

## Parser

- **Refatorar parser.py** — atualmente monolítico, regex-heavy. Quebrar em estágios menores testáveis (extract paragraphs → classify partition → assign parents → strip notes). Fazer junto com 0.2 Parser protocol pra Tier-3 PDFs.

## Tier-3 (✅ Phase 4.3 done)

- ✅ **DONE Phase 4.3.a-b** — ~~AnpdPdfParser~~ — Res 15/2024 (manual transcription) + Res 4/2023 (pdfplumber-extracted). 286 chunks total.
- ✅ **DONE** — ~~Documentar synthetic URN scheme da ANPD~~ — em `study/lexml-urn-spec-resumo.md` §9 (ANPD `resolucao.cd`).
- ⏸ Res 1/2021 + Res 2/2022 gated por (i) PDF cleanup OCR para a Res 2/2022 (`(cid:XXX)` font issue), (ii) page_range curation para Res 1/2021.

## Tier-4 jurisprudência (✅ Phase 6 done)

- ✅ **DONE Phase 6.1** — 7 chunks manualmente curados: 3 STJ Súmulas (227/403/479) + 4 STF Temas (786 verbatim, 987/533/815 stubs)
- ⏸ **D7 lawyer review** — substituir 3 stubs por tese verbatim + expandir curadoria. Ver `study/lawyer-review-checklist.md` item 5.
- ⏸ Phase 6.3 real scrapers (STF/STJ) — gated em D7 (precisa whitelist canônica) + Phase 7 infra (cron) — Phase 7 já feita; gate restante é só D7.

## LLM stage (Phase 2-5 done)

Most items below superseded by subsequent phases. Status updates:

- ✅ **DONE Phase 4.1** — query-type classifier + adaptive top_k (TOP_K_PER_TYPE). The "sonnet refuses row 7 inconsistently" item should be re-tested with the adaptive top_k; if still flipping, escalate.
- 🟡 **PARTIAL** — Lenient precision sweep: `alternative_acceptable_urns` set on more rows now (post Phase 5.1+ gold audits). Continued sweep is valid maintenance work.
- ✅ **SUPERSEDED Phase 5.1 + query expansion plan** — "OOS test set is tiny (3 rows)" — now 15 internal + 9 concurso pilot = 24 OOS, with subtype taxonomy a-e. Query expansion plan above grows to ~60-75 with legalbench.br.
- ⏸ **Cosine fast-path threshold (0.40) calibration** — still uncalibrated; LLM self-refusal is primary signal but cosine gate worth a synthetic adversarial test.
- ⏸ **Phase 3 candidates** (most superseded): retry policy ✅ via prose_check_retry; per-query latency/cost reporting ❌ (audit doc §4 gap #1+#2); hybrid generator (route enumeração to opus) ❌ still open.

## OOS hardening (refusal-discipline) — Phase 8 entry UNBLOCKED post-7.8

Phase 7.5.3+4+5 converged on the same diagnosis across 3 eval surfaces: pipeline is excellent at finding in-corpus content (97.5% rule recall) and bad at refusing out-of-corpus content (12.2% OOS refusal). Four phases of structural interventions (7.6.2 → 7.7 → 7.8) raised this to **0.633 = 5.2× lift**. Phase 8 hosting is no longer blocked by refusal discipline.

**Shipped:**

- ✅ **Phase 7.6.2 concept-scope tag gate** ([findings](study/phase-7.6.2-scope-tags-findings.md)) — +0.062pp
- ✅ **Phase 7.7 Fix #1 — `_is_self_refusal()` full-text scan** ([findings](study/phase-7.7-refusal-discipline-findings.md)) — +0.10pp
- ✅ **Phase 7.7 Fix #2 — `citations=[]` as implicit refusal** — +0.14pp
- ❌ **Phase 7.7 Fix #3 — SYSTEM_PROMPT iteration** — TRIED + REVERTED (net negative). Documented for reference.
- ✅ **Phase 7.8 per-citation relevance gate** ([findings](study/phase-7.8-citation-relevance-findings.md)) — **+0.22pp; gate CLEARED at 0.633**. Largest single-phase lift in the series. Catches Pattern B (wrong-law citations that pass cite-and-verify).

**Remaining work (no longer blocking; production-acceptable):**

- ⏸ **Audit doc updates** — Pattern B detection rows can flip ✅; cumulative arc deserves a §3 note
- ⏸ **Per-citation relevance as first-class eval metric** — currently a pipeline-internal signal; could be surfaced in Aggregate for telemetry
- ⏸ **Cost optimization** — relevance gate adds ~1.6s p50 latency; parallelize with main answer call if Phase 8 SLO requires
- ✅ **Phase 7.8.1 Sabiá-as-its-own-judge sanity** ([OOS A/B findings](study/phase-7.8.1-sabia-vs-opus-judge-findings.md), [in-scope regression](study/phase-7.8.1-inscope-opus-regression.md)) — Opus catches +5 OOS rows on legalbench (Sabiá self-defense bias real at ~10%); in-scope `false_refusal_rate = 0.000` confirmed with Opus. Eval default = Opus, prod default = Sabiá (cost). Surfaced and fixed a CLI default-fallback bug en route.
- ❌ **Phase 7.8.2 partial-relevance gate threshold — CLOSED NOT SHIPPED 2026-05-19** ([plan](study/phase-7.8.2-partial-relevance-gate-plan.md), [findings](study/phase-7.8.2-partial-relevance-gate-findings.md)). Option C Pareto-won on internal eval (+0.20pp OOS recall, +0 in-scope FR via adaptive-by-classified_type), but legalbench validation failed criterion 3: +0.021pp vs +0.05pp pre-locked threshold. Root cause: 48 of 49 legalbench rows classify as `parafrase`, so the per-type strategy collapses to flat ≥0.80 there. Internal Pareto-win was surface-specific. Harness (`scripts/phase_7_8_2_threshold_sweep.py`) is reusable for any future eval that captures `classified_type` + `rejected_irrelevant_citations`.
- ⏸ **Per-document scope tagging with finer grain** — = BACKLOG #1 still parked in EXPERIMENTS.md, no longer a critical path
- ⏸ **OOS-C category** (intentionally tricky CRIMINAL questions deceptively close to crimes cibernéticos) — propose adding via curated subset from `eduagarcia/oab_exams` and/or `legalbench.br`. Lower priority now.

## Production observability — ✅ MOSTLY COMPLETE via Phase 7.5.2 + 7.5.7

Full audit at `study/rag-eval-metrics-audit.md`. Findings: [`study/phase-7.5.7-sre-golden-signals-findings.md`](study/phase-7.5.7-sre-golden-signals-findings.md).

- ✅ **SRE Four Golden Signals: Latency + Errors** (Phase 7.5.7) — `RAGAnswer.latency_ms` + `Aggregate.latency_p50/p95/p99_ms` + per-row try/except + `error_count/rate`. Saturation/Throughput require Phase 8 HTTP harness.
- ✅ **Cost-per-query tracker** (Phase 7.5.2 + judge-cost fix in 7.5.7) — `cost.py` pricing table + `RAGAnswer.cost_estimate_usd` + `Aggregate.cost_mean_usd`. Judge spend now correctly attributed (was 13× under-reported pre-7.5.7).
- ✅ **False refusal rate as first-class metric** (Phase 7.5.1) — `Aggregate.false_refusal_rate` + `oos_refusal_recall` separately surfaced.
- ⏸ **RAGAS Answer Relevance** (~1d, ~$0.10/run) — separate LLM-judge call: reverse-question method (Es et al. 2023, arxiv 2309.15217). Still ❌ in audit doc; defer until Phase 8 entry items above resolve.

## Posts (`posts/`, gitignored)

- ✅ **DONE** — ~~Atualizar 3 drafts existentes~~ — drafts 01/02/03 reflect current numbers; new draft 04 (`04-title-prefix-broke-my-routing-intuition.md`) added 2026-05-16.
- 🟡 **READY-TO-WRITE candidates** (per `study/concurso-pilot-findings.md` + `study/rag-eval-metrics-audit.md`):
  - "Selection bias no seu eval set: como questões OAB reais expuseram 31pp de gap" (concurso pilot finding)
  - "Auditor's gold-standard checklist para legal RAG: 39 métricas, 17 que cobrimos, 13 que faltam" (audit doc summary)
  - "Parser dedup warning é signal, não ruído: dois bugs de cobertura silenciosa em um dia" (§-suffix + inc-suffix narrative)

---

## Cross-references (live docs to consult before starting any item)

- `study/RETRIEVAL-JOURNEY.md` — master methodology doc (9 second-stage techniques refuted)
- `study/rag-eval-metrics-audit.md` — full audit of 39 gold-standard metrics with sources
- `study/concurso-pilot-findings.md` — concurso pilot baseline + investigation TODOs
- `study/query-expansion-plan.md` — 4-sub-phase plan to grow eval set
- `study/llm-provider-decision-2026-05-15.md` — Sabiá vs Sonnet data-driven decision
- `study/lawyer-review-checklist.md` — D7 handoff list
- `study/phase-7-production-infra-plan.md` — Phase 7 design + decisions D1-D6
- `docs/runbook-corpus-refresh.md` — operator runbook for weekly cron PRs
- Memory `project-parser-bug-dedup` — triage guide for dedup_keep_last warnings
- Memory `feedback-paid-api-caution` — don't burn Voyage/Anthropic/Marítaca speculatively
- Memory `project-purpose-production` — project framing is production-level (2026-05-15+)
