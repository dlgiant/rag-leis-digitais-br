# Phase 10 — UI entry plan (planning, NOT YET BUILT)

**Date:** 2026-05-20
**Status:** Planning. No code yet; no pre-locked criteria committed yet.
**Predecessors:**
- Phase 8 (closed) — production HTTP service at `https://rag-leis-digitais-br.fly.dev` with X-API-Key auth, per-key rate limit, structured observability, threshold-based Slack alerts.
- [Phase 8 entry plan](phase-8-entry-plan.md) — explicit non-goal: "Web UI. API only. A UI would be a separate Phase 9/10 cycle."
- [Phase 7 production-infra plan](phase-7-production-infra-plan.md) — "Frontend (CLI? web?)" deferred.

## Why this phase exists

The Phase 8 deliverable is **a working API, not a working product**. To
produce real-world signal — operator self-use, demo recordings, eventual
public access — there has to be a UI layer that someone can click on
without remembering curl syntax. Phase 10 builds that layer.

Phase 10 also unlocks UX-driven feedback that bare-API testing can't
generate: do users actually understand "this query was refused because
no citations passed the relevance gate"? Do they trust the citations
when shown? Do they read the source-as-of-date footer? These are
questions the CLI eval set can't answer; only a UI can.

## Why this DOESN'T swap with Phase 9 (compliance)

Phase 9 in BACKLOG is "compliance / lawyer review (depends on D7
contracting)." The natural question is: should UI come first?

**Answer: don't swap numbering. Stage Phase 10 so it can run in
parallel with Phase 9.** Real LGPD obligations only trigger when
third-party users are involved. Self-use and ephemeral-demo UIs
don't trigger them; public multi-tenant does.

So:

| Sub-phase | Real users? | LGPD impact | Phase 9 gating |
|---|:-:|---|:-:|
| **10a — Local-only UI** | No (operator only) | Zero increase | None |
| **10b — Public demo, ephemeral** | Yes, but anonymous | Minimal (privacy notice required) | Soft gating (notice can be drafted without full lawyer review) |
| **10c — Public UI with named users** | Yes, named accounts | Full obligations (Art. 7, 18, breach notification, DPO if applicable, privacy policy + ToS) | **Hard gate on Phase 9 completion** |

Phase 10a unblocks UI work immediately. Phase 10c stays blocked
until Phase 9 closes. Phase 9 + 10 run in parallel; ship order is
deterministic (10a → 10b → Phase 9 → 10c).

## Three load-bearing design decisions

These shape everything else. Pick before any code:

### Decision 1: Framework (Astro vs Next.js)

| Option | Trade-off |
|---|---|
| **A. Astro (Recommended for 10a/b)** | Same stack as `ia.nunes.work` (already deployed). Content-first; islands architecture; minimal client JS. Hosted on Fly (BR-region honored) or Cloudflare Pages. ~2× lighter bundle than Next; faster TTI. SSR sufficient for chat shape — no React Server Components needed at v1 traffic. |
| B. Next.js (App Router) | Vercel-default deploys are US/EU regions — **must pin to BR-region** (currently `iad1`/`sfo1`/`fra1` only via Vercel; Fly+Next would honor `gru`). Larger ecosystem; React Server Components are real value at scale. Overkill for v1 chat UI. |
| C. Plain HTML + vanilla JS | Simplest. ~50 lines of HTML + fetch. No build tooling. Limits future growth — no component model means UI complexity hits a wall at ~3 screens. |
| D. SvelteKit | Comparable to Astro on bundle size; smaller ecosystem in BR. No specific advantage over Astro for this use case. |

**Recommendation: Astro.** LGPD region-pinning works out of the box on
Fly; the `ia.nunes.work` familiarity removes a learning curve; islands
architecture is well-suited to "mostly static page + interactive chat
component."

### Decision 2: Streaming (SSE vs one-shot)

Phase 8.5.1 measured **9-13s p95 production latency**. A chat UI that
spins for 13 seconds before showing anything feels broken — users
either reload or assume it's stuck.

**Streaming is non-negotiable for any UI sub-phase.** This means:

- Pipeline-side: the FastAPI handler needs to stream the answer
  token-by-token as the LLM produces it. Currently `/v1/ask` returns
  a full `RAGAnswer` JSON only when the pipeline completes. **A new
  `/v1/ask/stream` endpoint** (or an `Accept: text/event-stream` header
  on the existing `/v1/ask`) is required.
- Browser-side: `EventSource` for SSE consumption + DOM-incremental
  rendering of the answer.

**Sub-phase 10a (local UI) requires the streaming endpoint.** This
adds work to Phase 10 that bleeds into the pipeline — not just the
frontend. Explicit dependency: Phase 10a starts with **Phase 10.0 —
streaming endpoint on the server** before any frontend.

### Decision 3: Auth shape per sub-phase

| Sub-phase | Auth model | Stored data |
|---|---|---|
| **10a** | Single shared `X-API-Key` baked into operator's local env. UI runs on localhost. | Nothing user-side (operator IS the only user). |
| **10b** | No accounts. Anonymous demo with a server-side shared rate-limited key (different from operator's). | Ephemeral session cookies only; no PII retention. Audit log retains only redacted-query + answer (Phase 4.2 PII pipeline already does this). |
| **10c** | Email-based magic links OR Clerk/Auth.js OAuth. | User accounts (email, hashed identity), audit log per-user, conversation history. Requires lawful-basis declaration, privacy policy, DPO contact. |

10c's auth depends on **what Phase 9's lawyer review yields** for the
acceptable processing surface. Don't pick the auth provider until
Phase 9 surfaces requirements.

## Sub-phase decomposition

### Phase 10.0 — Streaming endpoint (1 session, $0)
Adds `POST /v1/ask/stream` (or upgrades `/v1/ask` to support SSE via
`Accept` header). The pipeline already produces the answer incrementally
inside `self.llm.complete_structured(...)`; streaming requires the LLM
backend (Maritaca) to support partial tool-call output. Maritaca's
OpenAI-compatible API supports `stream=true` on chat completions; need
to verify behavior with `tool_choice` forced.

**Pre-locked criteria:**
1. `POST /v1/ask` with `Accept: text/event-stream` returns SSE chunks
2. Final SSE message contains the full `RAGAnswer` JSON for clients
   that want it
3. Auth + rate limit gates unchanged
4. Existing non-streaming clients still get one-shot JSON

### Phase 10a — Local-only UI (1-2 sessions, $0)
Astro app at `ui/` (new top-level dir). Single chat page: input box,
send button, streaming answer area, citations panel.

**Pre-locked criteria:**
1. `cd ui && npm run dev` starts a local server
2. Operator can chat with the production API via the local UI
3. Streaming works (answer appears incrementally)
4. Citations render as clickable links to the LexML URN viewer
5. Refusal cases render appropriately (not as a generic error)

### Phase 10b — Public demo (1-2 sessions, ~$0-2/mo)
Same Astro app, deployed to a public URL (Fly app
`rag-leis-demo.fly.dev` or similar). Backed by a **separate
demo-only API key** with a tighter rate limit. Explicit "demo —
ephemeral session, no data retained" banner.

**Pre-locked criteria:**
1. Public URL serves the chat UI
2. Demo key is rate-limited tighter than operator key (e.g., 10
   req/min/IP)
3. Privacy notice visible above the input field
4. No persistent session storage — every page refresh = new session
5. No PII retention beyond Phase 4.2's existing audit log path

### Phase 10c — Public UI with accounts (gated on Phase 9)
The big one. Requires Phase 9's lawyer-reviewed:
- Privacy policy (Brazilian Portuguese; LGPD-compliant)
- Terms of Service
- Lawful-basis declaration per Art. 7
- Data subject rights flow (Art. 18 — access, correction, deletion)
- DPO contact (if processing volume requires)
- Breach notification protocol

Plus implementation: auth provider, user table, per-user audit log,
conversation history, account deletion flow.

**Do not plan in detail until Phase 9 is closer to closing.** The
lawyer-reviewed requirements will reshape this sub-phase substantially.

## Out of scope (explicit non-goals)

- **Mobile app (native iOS/Android).** Far future; if v1 UI traffic
  warrants, evaluate then.
- **Real-time multi-user collaboration.** Single-user chat only.
- **Voice input/output.** Defer indefinitely.
- **Document upload.** Users send queries, not documents. The corpus
  is fixed.
- **Conversation memory across sessions in 10a/b.** Single-turn only;
  conversation history is a Phase 10c feature.
- **Internationalization.** Portuguese only (the corpus is BR-legal).
  Maybe Spanish later. English never (audience mismatch).
- **Theming / dark mode.** Phase 11+ polish.
- **A11y deep dive.** Basic WCAG-AA at minimum for the core flow;
  comprehensive audit is Phase 11+.
- **Phase 8.4 load test against UI.** UI doesn't add server-side
  capacity concerns; Phase 8.4 numbers still apply.

## Open design questions to resolve at sub-phase start

1. **Where does the UI live in the repo?** Recommendation:
   `ui/` top-level dir with its own package.json. Keeps Python
   monorepo separate from the Astro project; no mixing of concerns.

2. **Single `app` vs separate Fly apps for backend + UI?**
   Recommendation: **single Fly app, Astro serves from a different
   path.** OR (cleaner): UI on its own Fly app
   (`rag-leis-ui.fly.dev`); backend stays at `rag-leis-digitais-br.fly.dev`.
   The latter scales independently and isolates failure modes.

3. **CSP / iframe embedding?** Allow embedding the chat widget in
   `ia.nunes.work` blog posts? Cool for demo screenshots; CSP work
   for v1. Defer.

4. **Citations — clickable URN viewer?** LexML has a public URN
   resolver at `https://www.lexml.gov.br/urn/<urn>`. Recommendation:
   wrap each citation in a link to the resolver. Test that the URN
   format the pipeline emits is the format LexML expects.

5. **Refusal cases — how to render?** When `refused=true`, don't
   show "ERROR" — show a sympathetic "I couldn't find the answer
   to that in the LGPD/MCI/related corpus" message. Same for
   `irrelevant-citations-implicit-refusal`. Specific copy needs
   Brazilian Portuguese review.

6. **Pre-canned example queries?** Probably yes — a "Try one of
   these:" section above the input with 3-5 known-good queries
   (e.g., "qual a definição de dado pessoal na LGPD?"). Lowers the
   friction of "what should I ask?" Onboarding-style.

## Risk + tradeoff analysis

| Risk | Severity | Mitigation |
|---|---|---|
| 13s latency feels broken to UI users | High | Streaming is non-negotiable (Phase 10.0) |
| Streaming breaks the verify step (citations only known after generation) | Medium | Stream the answer text but defer citations + post-gen state to a final SSE message; UI renders citations after the answer finishes |
| Phase 9 lawyer review surfaces UI changes | Medium | Stage 10a/b are minimal-surface; the bulk of LGPD-driven changes hit 10c (which is gated on Phase 9 anyway) |
| Maritaca streaming behavior unknown with tool_choice forced | Medium | Empirical test in Phase 10.0; fallback to non-streaming Sabiá call + UI-side "thinking..." indicator if streaming doesn't work |
| Astro + Fly is a new combination for the operator | Low | `ia.nunes.work` is Astro; deploying it on Fly is similar to Phase 8.5.1 work. No fundamentally new tech |
| UI users hit the relevance gate's "no citations" refusal often | Medium | Phase 10a will surface this UX issue empirically. Possible mitigation: UI shows what was retrieved even if the gate fires, with explanation |
| Demo key gets abused (Phase 10b) | Medium | Tight rate limit per IP + per-day quota; alerts via Phase 8.6 if abuse pattern emerges |
| LGPD region-pinning fails on Vercel (if chosen) | High (if chosen) | Pick Astro+Fly to avoid the question |

## Cost estimate

| Sub-phase | API spend | Wall time | Recurring |
|---|---:|---|---:|
| 10.0 — streaming endpoint | $0 | 1 session | $0 |
| 10a — local UI | $0 | 1-2 sessions | $0 (runs on operator's machine) |
| 10b — public demo | $0-2 | 1-2 sessions | ~$5/mo (separate Fly app shared-cpu-1x) |
| 10c — public accounts | n/a | n/a | n/a (planned after Phase 9) |

**Total Phase 10 (10.0 + 10a + 10b)**: ~3-5 sessions, ~$0-2 one-time,
~$5/mo recurring. Plus whatever 10c costs after Phase 9.

## Sequencing

Sub-phase ordering, with explicit dependencies:

```
Phase 10.0 (streaming endpoint, in rag_leis/server.py)
    ↓
Phase 10a (local UI, requires streaming)
    ↓
Phase 10b (public demo, requires 10a + tighter rate limit + privacy notice)
    ↓
    ⏸ wait for Phase 9 to close ⏸
    ↓
Phase 10c (public accounts; reshape after Phase 9)
```

**Phase 9 (compliance) runs in parallel from the start.** Phase 9's
output is the input for Phase 10c. Until Phase 9 lands, only
10.0 / 10a / 10b are buildable.

## What we'll learn that's not in this plan

- Whether Maritaca's streaming + `tool_choice` interaction works
  (no docs on this; empirical only).
- Whether citations rendered as links improve trust signal in the UI.
- Whether refusal-case copy lands well in BR-Portuguese.
- Whether 13s p95 latency is acceptable WITH streaming (different
  question from "without streaming").
- Whether the operator's expected query patterns differ from the
  eval set's distribution (real-use feedback that the eval set
  can't generate).

## Cross-references

- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — Phase 8 explicitly deferred UI to Phase 9/10
- [`phase-8.1-...-findings.md`](phase-8.1-...-findings.md) and following — production API surface this UI consumes
- [`phase-8.5.1-deploy-findings.md`](phase-8.5.1-deploy-findings.md) — Fly.io deployment pattern that 10b will reuse
- [`project-lgpd-brazil-residency`](../../.claude/projects/-home-ricardo-rag-leis-digitais-br/memory/project_lgpd_brazil_residency.md) (memory) — BR-region constraint that affects Astro vs Next.js framework choice
- BACKLOG.md Phase 9 line — the compliance/lawyer-review sub-phase that gates 10c
