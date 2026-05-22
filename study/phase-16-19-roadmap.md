# Phase 16–19 roadmap — post-round-3 review (drafted 2026-05-22)

Synthesizes the round-3 engineering review (`REVIEWER_NOTES_3.md`) and the
round-3 legal-domain review (`REVIEWER_NOTES_4.md`) into four sequenced
phases. The two reviewers converged on the same higher-order failure
class — the system asserts currentness/posture claims that contradict
its own data — so the plan treats "freshness + truth" as the first
sprint and defers anything that needs the D7 lawyer to the last.

## Convergence finding (drives the sequencing)

Engineering risk #1 (`fetched_at` reports deploy date, not Planalto
fetch date) and Legal risk #1 (vigência overlay still labels MCI art.
19/21 as `sub_judice` when STF fixed Tema 987's tese on 2024-06-26) are
the **same bug class** under two reviewers' lenses. Both fail loud
under any skeptical reading because the system contradicts itself. The
fix has two parts: (a) correct the asserted claim, (b) install the
loop that keeps it correct (overlay quarterly review cadence, sidecar
`fetched_at` written by the fetcher, not derived from mtime).

Without (b), every fix is a future stale-doctrine bug.

## Phase 16 — Freshness + truth (Sprint 1)

Pure content + telemetry. No architectural change. Each item is a
small PR; the bundle ships in roughly 1.5 operator-days.

| Item | Surface | Cost | Rationale |
|---|---|---|---|
| **16.1** `fetched_at` persisted in metadata sidecars | `rag_leis/fetch_tier.py:121-136`, `rag_leis/eval_harness.py:137-146` | ½ day | Production footer is currently lying — Docker `COPY` resets mtime to build time. Completes round-1 item #6. |
| **16.2** Vigência taxonomy: add `alterado_por_jurisprudencia`; update MCI 19/21 entries (Tema 987 julgado 26/06/2024); add `proxima_revisao` to every entry | `rag_leis/vigencia.py:37-46`, `data/vigencia/overlays.yaml` | 2–3 h | Worst stale-doctrine error today. `proxima_revisao` installs the review loop. |
| **16.3** Exclude `PENDENTE_*` Tier-4 stubs from retrieval; comment out — not delete — eval rows pinning them as gold | `rag_leis/rag.py` (load-time filter), `data/chunks/tier-4/jurisprudencia.jsonl`, `eval/queries.yaml:983,988,997` | 2 h | Chunks' own `notes` field documents the hallucination risk; pipeline rewards retrieving them. Stub → tese transcription is D7-gated (Phase 19). |
| **16.4** Expose `RAG_SCOPE_CHECK_ENABLED` / `RAG_RELEVANCE_GATE_ENABLED` / `RAG_RELEVANCE_JUDGE` in `_build_pipeline_from_env` | `rag_leis/server.py:204-221` | 30 min | Prerequisite for the canary in Phase 17. Production currently locked to dataclass defaults — no A/B without redeploy. |

**Why this is one sprint:** 16.2 + 16.3 + 16.4 can ship as a single
"freshness + gates" PR (they share theme + touch independent files).
16.1 is a separate ½-day PR because the parser-side change has its own
test surface.

## Phase 17 — Multi-turn primitives (Sprint 2)

Items that have a hard deadline: Phase 10d (multi-turn) is on the
BACKLOG and will collide with the stateless-per-call assumption. These
must land before 10d code does.

| Item | Surface | Cost | Dependency |
|---|---|---|---|
| **17.1** Nightly refusal-discipline canary GHA (20-row legalbench OOS subset, prod-equivalent stack, gates on `oos_refusal_recall ≥ 0.55` + `false_refusal_rate ≤ 0.02`) | `.github/workflows/nightly-refusal-canary.yml`, `run_concurso_eval.py` | ½ day | 16.4 (env-exposed gates) |
| **17.2** Multi-turn classifier contract: decide rewrite-then-classify vs. context-into-classifier; document on `query_type.py`. Write 10-row conversation-shape eval (`turn_1`, `turn_2`, `gold_for_turn_2`) | `eval/conversation_queries.yaml` (new), `rag_leis/query_type.py` | 1 day | None — must precede 10d |
| **17.3** Move `load_dotenv()` out of `rag_leis/llm.py:34` and `rag_leis/maritaca.py:39`; centralize at entry points. Remove the Phase 13 monkeypatch workaround. | `rag_leis/llm.py`, `rag_leis/maritaca.py`, test fixtures | 2 h | None |
| **17.4** Provider-aware tool-use retry (n=1) with `complete()` JSON-fallback; `pipeline.tool_use_fallback_rate` metric | `rag_leis/llm.py:205-208`, `rag_leis/obs.py` | ½ day | None |
| **17.5** Calibrate or pin `DEFAULT_OOS_THRESHOLD` with citation to a `study/` measurement on `legalbench_br_oos.yaml` | `rag_leis/rag.py:115`, new `study/phase-17.5-oos-threshold-calibration.md` | 2 h | None |
| **17.6** `regulamentation_target` doc-level metadata + render in `<fonte>`; system_prompt addendum: "ao citar regulamento, sempre cite a lei regulamentada" | `data/metadata/tier-*`, `rag_leis/rag.py` | 2 h | None — closes the structural sibling of the Decreto 8.771 false-refusal that sabia-4 currently masks |

**Gating item:** 17.2 is the one that must finish before any Phase 10d
code is written. Everything else in Phase 17 is parallelizable.

## Phase 18 — Corpus + cross-doc gold expansion (Sprint 3)

Operator + intermittent lawyer touch. Ships over ~2 weeks.

| Item | Surface | Cost | Notes |
|---|---|---|---|
| **18.1** Index Tier-1.5: ECA (arts. 17-18, 78, 240-241-E), LC 105/2001, Lei 12.414/2011, Decreto 10.474/2020. Update README declared corpus. | `data/chunks/tier-1/`, fetch + parse, README | 1 day | Parser already handles `lei` / `lei.complementar` URNs; overlays already reference these docs as "não indexada". |
| **18.2** Manual transcription of operative articles of Res. CD/ANPD 1/2021 + 2/2022 (arts. 1-15) | `data/chunks/tier-3/`, metadata | ½ day | Same shape as Tema 786 verbatim transcription. Unblocks `eficacia_limitada` overlays. |
| **18.3** Habeas data gold expansion: add Lei 9.507 arts. 2, 7, 8 to `alternative_acceptable_urns` | `eval/answer_queries.yaml:91-100` | 30 min | Closes round-2 ask. |
| **18.4** Cross-doc gold for 5 canonical scenarios from `study/lawyer-review-checklist.md:110-122` with `companion_urns` + `relationship` typing | `eval/answer_queries.yaml` | 1 day (with lawyer) | Highest-leverage move on legal quality. Doesn't need full D7 contract — needs intermittent lawyer attention. |
| **18.5** PII redactor: OAB, CRM, processo CNJ, eleitoral regex (drains Phase 14 audit findings) | `rag_leis/pii.py`, `data/pii/missed.yaml` | 2 h | LGPD compliance posture on lawyer queries. |

## Phase 19 — D7 lawyer-gated work (Sprint 4)

Don't start until D7 is contracted. Starting earlier produces work
that must be redone after lawyer sign-off.

| Item | Cost | Why D7-gated |
|---|---|---|
| **19.1** Verbatim STF Tema 987 tese transcription; remove stub flag; re-enable retrieval. Same for Temas 533, 815 if/when their teses fix. | ½ day lawyer + ½ day operator | Tese fidelity is the whole point — only a lawyer should bless the verbatim. |
| **19.2** "Judicial-acceptable" precision tier on `eval/answer_queries.yaml`: annotate `judicial_acceptable_urns` per row; run eval once at strict tier. | ½ day lawyer + 2 h operator | The number that matters becomes measurable. |
| **19.3** Quarterly vigência overlay audit cadence: pass 1 over the existing 12 entries via the Phase 12 review UI. | ½ day lawyer | Closes the loop that 16.2's `proxima_revisao` field opens. Prevents Tema-987-class staleness from recurring. |
| **19.4** Hierarquia warning logic: suppress when `kind=jurisprudencia` merely supports a higher-rank cite. Validate on 9 jurisprudência rows in `eval/queries.yaml:932-1001`. | 1 h operator (after lawyer confirms rule) | Removes a false-positive warning that today trains undercitation of súmulas. |

## Smaller cleanups (fold into adjacent PRs, no dedicated phase)

- Add Tier-4 to `TITLE_BY_URN` in `rag.py:60-63` (currently misses jurisprudência footers).
- `parser.py:471` switch from `logging.getLogger` to structlog.
- `rag.py:107` move stray `DEFAULT_AUDIT_LOG_PATH` to module-level constants block.
- `rag.py:530-534` lift lazy `concept_scope` + `cost` imports to module top.
- Stub `pendente_julgamento` Tema chunks: enforce rank-down to 5 in `legal_rank.py:62-65` (consistency with retrieval exclusion in 16.3).

## Sequencing rationale (the four "why this order" answers)

1. **Phase 16 first** because the system is currently misrepresenting
   itself to users. Every other phase amplifies that.
2. **Phase 17 next** because Phase 10d is the next named scope and
   will lock-in wrong primitives if shipped before classifier
   contract + canary land.
3. **Phase 18 in parallel with 17** for items that don't share files
   (corpus indexing, PII regex). 18.4 (cross-doc gold with lawyer)
   slots wherever D7 has bandwidth.
4. **Phase 19 last** because D7 is the constrained resource. Producing
   work that needs lawyer rework wastes that constraint.

## Cost summary

| Phase | Operator-days | Lawyer-days | LLM spend |
|---|---|---|---|
| 16 (freshness + truth) | 1.5 | 0 | ~$0 |
| 17 (multi-turn primitives) | 2.5 | 0 | ~$2 (calibration + canary) |
| 18 (corpus + gold) | 2.5 | 0.5 (intermittent) | ~$3 (re-index + re-eval) |
| 19 (lawyer-gated) | 1.5 | 2 | ~$5 (re-run eval with new gold) |
| **Total** | **8 op-days** | **2.5 lawyer-days** | **~$10** |

## Exit criteria

Phase 16-19 are "done" when:

- Tema 987 overlay is current with STF's 2024-06-26 ruling, and every
  overlay entry has a `proxima_revisao` date ≤ 90 days out.
- No Tier-4 chunk with `PENDENTE_*` notes is retrievable.
- Production footer source-as-of-date matches Planalto fetch date,
  not deploy date.
- Nightly canary has been green for 7 consecutive days.
- Multi-turn classifier contract is documented + 10 conversation eval
  rows are committed.
- Corpus declared scope matches indexed scope (README ↔ `data/chunks/`).
- 5 cross-doc canonical scenarios have gold in `eval/answer_queries.yaml`.
- "Judicial-acceptable" precision number is reported in the next
  eval-summary findings doc.
