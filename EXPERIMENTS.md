# Experiments

Speculative or already-refuted angles that are **tracked but not actionable** without new evidence. Items move out of here only when (a) a specific use case demands them, or (b) the BACKLOG GO items they depend on produce signal that justifies revisiting.

This file is intentionally separate from BACKLOG.md. **BACKLOG** = "would do if I had a free week tomorrow." **EXPERIMENTS** = "would consider if specific evidence emerged."

---

## 🧪 Graph RAG concepts — MAYBE / parked

**Source:** [`study/paper-evaluation-graph-rag-2025.md`](study/paper-evaluation-graph-rag-2025.md) §3. Three 🟢 GO concepts went to [`BACKLOG.md`](BACKLOG.md); these are the four that didn't make the cut, with the evidence threshold for revisiting.

### #4 — Cross-references as queryable graph edges 🟡

**Cost if pursued:** 1-2 days (storage layer; parser data already exists).

**Status:** Clean engineering work but **no immediate user-facing benefit**. The parser already detects `amended_by` relationships and discards them; the eval surface (104 retrieval + 29 answer + 49 OOS + 40 rule recall + 5 discursive = 227 evaluated query shapes) has **zero** "amendment-traversal" queries. Build-it-and-they-might-come.

**Bar to revisit:** a specific user query shape emerges that needs cross-reference traversal (e.g., "what's been amended by Lei 14.155/2021?"), OR a future TIER document type (legislative history archives, ADIs) requires it structurally.

### #5 — Hierarchical communities for retrieval 🟡

**Cost if pursued:** 3-5 days (Leiden/Louvain clustering over a KG, retrieval-filter or re-rank changes).

**Status:** The existing dense retrieval already hits **97.5% in-corpus rule recall** (Phase 7.5.4, 40 rows). Ceiling for retrieval improvement is ≤2.5pp. Returns diminish fast against engineering cost.

**Bar to revisit:** evidence that retrieval is the bottleneck on some specific query shape. Today the evidence says it isn't — the bottleneck is refusal discipline (12.2%), not retrieval (97.5%).

### #6 — LLM ranking step using KG paths 🟡

**Cost if pursued:** 2-3 days.

**Status:** This project has **empirically refuted** re-ranking with cross-encoders ([`posts/02-stronger-reranker-worse-performance.md`](posts/02-stronger-reranker-worse-performance.md)) and hybrid retrieval ([`posts/03-hybrid-rrf-didnt-work.md`](posts/03-hybrid-rrf-didnt-work.md)). Re-litigating with "but now with KG features" is a coherent hypothesis but requires the same empirical work to validate.

**Bar to revisit:** BACKLOG GO items #1+#2 (concept graph) produce a working KG AND an unmet need for finer ranking surfaces. Otherwise this is rebuilding refuted infrastructure with new lipstick.

### #7 — Dataset queries / data lake statistics enrichment 🔴

**Cost if pursued:** n/a.

**Status:** Doesn't transfer. The project's corpus is legal *text*, not tabular datasets. No columns, no value distributions. The concept has no analog.

**Bar to revisit:** would require the project to fundamentally change scope (e.g., adding a tabular dataset corpus alongside legal text). Effectively never.

---

## How items leave this file

Each MAYBE item has an explicit **"Bar to revisit"** clause. When that bar is met, the item moves to BACKLOG.md as a 🟢 GO with a cost estimate. If the bar is never met, the item stays here as a tracked-but-parked decision.

🔴 items are noted for completeness; they're not expected to leave.

---

## Cross-references

- [`BACKLOG.md`](BACKLOG.md) — actionable items (the 🟢 counterpart to this file)
- [`study/paper-evaluation-graph-rag-2025.md`](study/paper-evaluation-graph-rag-2025.md) — full evaluation grounding the verdicts above
- [`study/RETRIEVAL-JOURNEY.md`](study/RETRIEVAL-JOURNEY.md) — master doc of refuted second-stage techniques (companion to why #6 needs a high bar)
