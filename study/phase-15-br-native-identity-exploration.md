# Phase 15 — Brazilian-native identity (exploration breakdown)

**Status:** Open. Breakdown of requirements documented; sub-exploration
findings NOT yet populated (open-question rows remain unanswered).
**Predecessor:** [Plan](../../.claude/plans/curried-humming-hellman.md)
(Phase 15 — Brazilian-native identity exploration, approved 2026-05-20)
**Type:** Research only. Does NOT ship code. Build phases (if
approved) become 15.1 / 15.2 in BACKLOG.

## Context

The project's current and planned auth surfaces all use US-based
identity providers:

- **Phase 11+** (internal review UI) — Clerk + GitHub OAuth + Google
  OAuth. Data subjects are operator + lawyer; LGPD risk is low because
  they consent to their own identity transit.
- **Phase 10c** (future public UI with named users) — also planned
  to use Clerk. For a Brazilian audience, this means every user's
  identity data transits US infrastructure. Lawful under LGPD Art. 33
  with disclosure, but **not LGPD-perfect** and not symbolically
  aligned with a Brazilian legaltech product.

Phase 15 researches two BR-native identity systems as alternatives /
complements for the Phase 10c public-user tier:

1. **`gov.br`** — Brazilian federal citizen identity. Standard OIDC.
   Returns verified CPF + name + email + identity-level
   (bronze/silver/gold). Data processed entirely in BR government
   infrastructure. LGPD-perfect for citizen auth.
2. **e-OAB** — Verifies the user is an active member of the Ordem dos
   Advogados do Brasil. ICP-Brasil X.509 certificate (NOT OAuth).
   Provides "this is a real practicing lawyer with active OAB
   inscription" signal — strongest possible identity claim for a BR
   legaltech product.

**Output:** a written recommendation per system (go/no-go), with
documented timelines, technical-feasibility notes, and
cost/complexity tradeoffs.

This phase is **upstream of Phase 10c** but downstream of Phase 9
(lawyer review). The lawyer in Phase 9 should bless or block the
identity choices Phase 15 surfaces.

## Sub-exploration A — `gov.br`

### What this would give us

- BR-resident identity processing (LGPD-perfect)
- Verified CPF on every authenticated user
- Identity tier (bronze/silver/gold) — bronze is self-declared,
  silver/gold are verified via banks / biometrics / e-CPF
- Email + full legal name from federal records

### Requirements to verify during exploration

| Requirement | Known | Open question |
|---|---|---|
| **OIDC discovery URL** | `https://sso.acesso.gov.br/.well-known/openid-configuration` | Verify still live + which scopes accept current schema |
| **Service-provider registration** | Required; via `gov.br/servidor` portal | Process applies to individuals or only legal entities (CNPJ)? Operator has no Brazilian CNPJ today; this might be a blocker |
| **Approval timeline** | Estimated 5-15 business days per public docs | What rejection criteria are common? Is "personal RAG demo" likely to be approved or rejected as redundant/insufficient? |
| **Service categorization** | The `gov.br` portal requires you to declare the service category (e-gov / private-sector / academic / etc.) | Which category fits a privately-operated legaltech tool? |
| **Identity-level requirement** | Bronze allows fake CPFs with verified email; silver/gold require real verification | What level should we REQUIRE for our use case? For a public legaltech tool, silver is probably the right minimum |
| **Clerk integration path** | Clerk supports custom OIDC providers on the free tier | Has anyone wired `gov.br` to Clerk before? Are there gotchas with Clerk's expected `email` claim vs `gov.br`'s claim names? |
| **Sandbox / test environment** | gov.br operates a sandbox at `sso.staging.acesso.gov.br` | Same registration process? Can the operator test integration before production approval? |
| **Privacy-policy implications** | Disclosure of `gov.br` integration is required | What template language does the gov.br SP onboarding require in the privacy policy? |
| **Service-level guarantees** | gov.br is a government service — likely no SLA we can sue on | What's the historical uptime? Outage frequency? |
| **Branding requirements** | gov.br may require its logo + "Entrar com gov.br" button styling | Are there branding-compliance docs we must follow? Penalties for non-compliance? |

### Findings (populated during exploration)

> _Not yet populated. Each "open question" row above should be
> resolved here with a concrete answer + source link._

### Exploration cost

- **Wall time**: ~½-1 session of reading gov.br docs + checking the
  SP portal's registration form requirements
- **API spend**: $0
- **External dependencies**: gov.br documentation, possibly contacting
  their support if questions arise

## Sub-exploration B — e-OAB

### What this would give us

- "This user holds an active OAB inscription" — verifiable practitioner identity
- Direct symbolic alignment with Brazilian legal practice
- OAB number + jurisdictional sectional (OAB/SP, OAB/RJ, etc.)
- Strongest possible identity claim for a BR legaltech audience

### Requirements to verify during exploration

| Requirement | Known | Open question |
|---|---|---|
| **Auth mechanism** | ICP-Brasil X.509 client certificate, NOT OAuth | What's the modern API integration pattern? Is there a server-side validation API we can call instead of full mTLS? |
| **OAB number verification** | OAB sections (state-level) maintain registries; there's no single federal API | Is there a Conselho Federal OAB API for "is OAB number X active?" Or must we go state-by-state? |
| **Certificate-based mTLS** | If we accept e-OAB certs directly, we need TLS termination that captures + validates the client cert | Does Fly/Vercel support TLS-passthrough or client-cert termination? Or do we need a custom edge? |
| **Certificate validation** | Need to validate against the ICP-Brasil root CAs | Where are the ICP-Brasil CA chain files distributed? How often do they rotate? |
| **Certificate revocation** | CRL or OCSP check needed to detect revoked certs | How fresh must the revocation check be? What's the standard for legaltech? |
| **Cert-parsing libraries** | Some Python/Node libraries exist for ICP-Brasil cert parsing | What's their maturity? Are they maintained? Permissive license? |
| **Alternative: e-OAB via gov.br** | gov.br GOLD level may include e-OAB-equivalent identity claims | Does gov.br's `professional` or `legal_attorney` claim provide what we need without separate e-OAB cert handling? **This is the load-bearing question** — if YES, sub-exploration B collapses into A. |
| **User UX** | e-OAB certs live in the lawyer's browser/token/smart card | What fraction of BR lawyers actually have a working e-OAB cert installed in their browser? Acceptable UX or a meaningful adoption barrier? |
| **OAB CFOAB API** | Conselho Federal OAB at cna.oab.org.br | Is there a developer-accessible API for OAB number lookup? Or is it only via web scraping? |
| **Legal restrictions** | Some uses of e-OAB are restricted to court filings | Is a private legaltech tool allowed to use e-OAB as auth, or is that out of bounds? Worth checking OAB's published positions. |

### Findings (populated during exploration)

> _Not yet populated. Each "open question" row above should be
> resolved here with a concrete answer + source link. The "Alternative:
> e-OAB via gov.br" row is load-bearing for the whole sub-exploration
> shape — answer FIRST._

### Exploration cost

- **Wall time**: ~1 session of reading ICP-Brasil + OAB CFOAB docs,
  testing whether gov.br GOLD provides equivalent claims
- **API spend**: $0
- **External dependencies**: OAB documentation, possibly contacting
  CFOAB

## Cross-cutting decision criteria

After both sub-explorations, the comparison matrix would look like:

| Property | Current (Clerk Google/GitHub) | gov.br | e-OAB |
|---|---|---|---|
| Data residency | US | **BR (gov-owned)** | BR |
| LGPD posture | Disclose international transfer | **Best possible** | Best possible |
| Setup wall-time | 5 min | 5-15 days + tech | Weeks (TBD) |
| Cost | $0 (≤10K MAU) | $0 + approval | $0 + cert ops |
| Identity strength | "Has a Google/GitHub" | "Has a CPF" | "Has an active OAB" |
| UX | Universal (everyone has Google) | High (BR citizens have gov.br) | Lower (cert UX) |
| Symbolic alignment for BR legaltech | Low | **High** | **Highest** |
| Public-user readiness | Yes | After approval | After approval + cert ops |
| Cell values populated by exploration? | ✅ known | 🔬 to verify | 🔬 to verify |

## Sequencing

Sub-exploration A (gov.br) goes FIRST. The "does gov.br GOLD include
an attorney claim?" question may collapse B (e-OAB) entirely into A.
If it does, e-OAB-specific work disappears; if not, B proceeds
independently.

Phase 15 can run **in parallel with Phase 11.1-11.4** (the review-UI
build phases). Phase 15 is research; Phase 11 is implementation. They
don't share files.

## "Done" criteria for Phase 15

The exploration is "done" when:

1. **Both sub-exploration sections have every open-question row
   populated** (not "TBD", not blanked-out)
2. **The comparison matrix has real values** in every cell, not
   placeholders
3. **A specific go/no-go recommendation per system**, with reasoning,
   is written
4. **BACKLOG Phase 15 entry** is updated with the recommendation
5. **Phase 9 (lawyer-review) entry in BACKLOG** is amended to add
   "review Phase 15 findings + bless or block identity choices" to
   its scope

## What this phase does NOT do

- Build any code. Code lands in 15.1+ if approved.
- Integrate with Clerk (also 15.1+).
- Submit the service-provider registration to `gov.br`. The
  exploration documents the registration REQUIREMENTS; submitting is
  a separate operator-decision after Phase 15 lands and Phase 9
  blesses.
- Decide Phase 10c's final auth stack. Phase 10c's decision is
  downstream of Phase 15's outputs + Phase 9's review.

## Recommendation (populated when exploration completes)

> _Not yet populated. Final output should be: one paragraph per system
> with a YES/NO recommendation, plus a concrete next-phase scope (e.g.,
> "Phase 15.1 — build gov.br integration as a second Clerk social
> connection")._

## Cross-references

- BACKLOG.md Phase 15 entry — research scope
- BACKLOG.md Phase 9 — compliance/lawyer review (blesses or blocks
  the identity choices)
- BACKLOG.md Phase 10c — public UI with user accounts (consumer of
  this exploration's output)
- [`study/lawyer-review-checklist.md`](lawyer-review-checklist.md) —
  Phase 9 deliverable that should incorporate this phase's findings
- [`rag_leis/clerk_auth.py`](../rag_leis/clerk_auth.py) — current
  auth implementation; Phase 15.1+ (if approved) would extend it
