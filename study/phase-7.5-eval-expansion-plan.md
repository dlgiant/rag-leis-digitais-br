# Phase 7.5 — Eval expansion (formalized)

**Status:** plan (in execution as of 2026-05-17).
**Predecessor:** Phase 7 (production infra) closed 2026-05-16.
**Successor:** Phase 8 (hosting + SRE observability). Phase 7.5 surfaces
the gaps Phase 8 needs to monitor before Phase 8 commits the architecture.

This formalizes work that was already happening organically post-Phase 7
under various labels ("audit cycle", "concurso pilot", "title-prefix
experiment"). Phase 7.5 nomenclature is retroactive but useful: it
captures a **single coherent goal — close eval-discipline gaps before
Phase 8** — and provides verifiable exit criteria.

## Why a phase (and not just "more eval work")

Three reasons phase-naming this matters:

1. **Decision-doc discipline.** Phases 6 and 7 each had `study/phase-N-plan.md`
   precede implementation. Without one for 7.5, the eval-expansion work
   continues organically but accumulates without forcing a "are we done?"
   decision point. Plan doc forces explicit exit criteria.

2. **Phase 8 dependency.** Phase 8 (hosting) needs to know which metrics
   to instrument as SLOs. Today the answer is "all 17 covered + the 4 ROI
   gaps from the audit doc." Phase 7.5 closes those gaps so Phase 8 has
   a stable measurement surface to monitor.

3. **Operator visibility.** Hiring managers / future-self reviewing the
   repo see phases as discrete deliverables. "Phase 7.5 — eval expansion"
   in `study/` is clearer than 6 disparate documents (`concurso-pilot-findings`,
   `query-expansion-plan`, `rag-eval-metrics-audit`, etc.).

## Inputs (all already in repo)

- `study/rag-eval-metrics-audit.md` — 39 metrics audit (17 ✅ / 9 🟡 / 13 ❌); top 4 ROI gaps
- `study/concurso-pilot-findings.md` — pilot baseline: 62.5% refusal accuracy on external vs 93.8% internal
- `study/query-expansion-plan.md` — 4 sub-phases (A-D) for external dataset integration
- `BACKLOG.md` § OOS hardening — concurso pilot 0/2 OOS-B + 43% OOS-A
- `BACKLOG.md` § Production observability — 4 audit gaps with effort estimates

## Decisions to lock before sub-phase work begins (D1-D5)

### D1 — Scope ceiling ✅ DECIDED 2026-05-17: comprehensive

All 4 sub-phases of `query-expansion-plan.md` (A+B+C+D) PLUS top 3 ROI
gaps from audit doc (false_refusal_rate + cost-per-query + SRE Golden
Signals). Audit doc gap #4 (RAGAS Answer Relevance) deferred to Phase 8.

### D2 — Order of operations ✅ DECIDED 2026-05-17: path β (instrument first)

1. Audit gap #3 (false_refusal_rate, 30 min) + #2 (cost tracker, 2h) first
2. Then sub-phases A→B→C→D
3. Then audit gap #1 (SRE Golden Signals, 1d) last

Rationale: 2.5h of observability upfront pays back across every eval
iteration in the rest of Phase 7.5 (knowing cost per run = iteration discipline).

### D3 — Sub-phase D (manual LGPD curation) execution

Sub-phase D requires manual labor: download OAB 39-44 PDFs, extract LGPD
questions, curate gold URNs. Two options:

- **D operator-only:** Ricardo curates ~15-30 LGPD questions himself.
  ~4-6h focused. Output: `eval/oab_lgpd_curated.yaml`.
- **D with lawyer review (D7-gated):** same extraction but gold validated
  by D7 consultant. Higher quality + leverages existing
  `study/lawyer-review-checklist.md` D7 hand-off.

**Recommendation:** D operator-only as baseline; flag as candidate for
D7 review when the lawyer is contracted. Don't block on D7.

### D4 — Cost ceiling for Phase 7.5

Cumulative API cost estimate per `query-expansion-plan.md`:
- Sub-phase A: ~$1.50 (50 Sabiá calls)
- Sub-phase B: ~$1.50 (30-50 Sabiá calls)
- Sub-phase C: ~$3-5 (10 discursive × multi-aspect LLM judge)
- Sub-phase D: ~$1 (~15-30 LGPD questions)
- Audit gap #1 (SRE) + #2 (cost) + #3 (false-refusal): no recurring API
  cost (instrumentation only)
- Voyage re-embeds: 0 (no corpus change in Phase 7.5)

**Total ceiling: ~$10 across all of 7.5.** Plus ~3-4 baseline eval re-runs
post-instrumentation (Sabiá full answer-eval ~$0.50 each) = ~$2.

**Phase 7.5 total budget: ~$15.** Within `feedback-paid-api-caution`
memory rule because each sub-phase is explicit-ask granularity.

### D5 — Phase 7.5 done criteria

Phase 7.5 is closed when:

1. **Eval surface:** ~60-75 OOS rows total (vs 24 today), ≥30 in-scope
   from external sources, ≥1 discursive eval baseline, ≥1 LGPD-specific
   in-scope subset (sub-phase D).
2. **Metrics surface:** false_refusal_rate + cost_per_query + SRE Golden
   Signals reported in `Aggregate` dataclass. Test that asserts all
   fields produce non-None values on baseline run.
3. **Methodology:** updated `study/rag-eval-metrics-audit.md` gap table
   (4 ROI items moved from ❌/🟡 to ✅) + `study/query-expansion-plan.md`
   marked as complete or each sub-phase status updated.
4. **One findings writeup:** `study/phase-7.5-findings.md` documenting
   what the expanded eval revealed about pipeline quality vs old measurements.
5. **No regression:** suite stays green (target 360+ tests). Production
   `DEFAULT_TEXT_MODE` metrics within band of last-known baseline
   (nDCG@10 ≥ 0.71, MRR@10 ≥ 0.79).

## Sub-phase ordering (per D2 = path β)

| Order | Item | Source | Cost (eng) | Cost ($) |
|---|---|---|---|---|
| 7.5.1 | false_refusal_rate first-class | Audit gap #3 | 30 min | $0 |
| 7.5.2 | cost-per-query tracker | Audit gap #2 | 2h | $0 (instrument) |
| 7.5.3 | Sub-phase A (legalbench.br OOS) | Query expansion §A | 2h | ~$1.50 |
| 7.5.4 | Sub-phase B (legalbench.br rule recall) | Query expansion §B | 3h | ~$1.50 |
| 7.5.5 | Sub-phase C (oab-bench discursive) | Query expansion §C | 4-5h | ~$3-5 |
| 7.5.6 | Sub-phase D (OAB 39-44 LGPD manual) | Query expansion §D | 4-6h human | ~$1 |
| 7.5.7 | SRE Golden Signals (latency / errors / throughput) | Audit gap #1 | 1d | $0 (instrument) |
| 7.5.8 | Phase 7.5 findings writeup + audit doc update | (this doc) | 2h | $0 |

**Total: ~3-4 days focused work + ~$10 API.** With Claude Code multiplier
historically ~5x on technical work, realistic ~1-1.5 days.

## Out of scope (explicit non-goals)

- ❌ Rabula benchmark integration (dataset URL not yet located)
- ❌ Full LegalBench US integration (audit doc §4 gap #5, superseded)
- ❌ RAGAS Answer Relevance (defer to Phase 8 after SRE infra)
- ❌ New TIER documents (no corpus change in Phase 7.5)
- ❌ Production deployment / hosting (= Phase 8)
- ❌ Lawyer engagement (= Phase 9, D7 external)

## Cross-references

- Predecessor: `study/phase-7-production-infra-plan.md`
- Sibling: `study/query-expansion-plan.md`, `study/rag-eval-metrics-audit.md`,
  `study/concurso-pilot-findings.md`
- Successor: TBD `study/phase-8-hosting-plan.md`
- Operational: `BACKLOG.md` § State snapshot + Query expansion + Production observability

## Status

- D1 + D2 locked 2026-05-17 (comprehensive + path β).
- D3-D5 remain as written (operator-only D, $15 budget, 5-criterion done gate).
- Execution begins with 7.5.1 (false_refusal_rate as first-class metric).
