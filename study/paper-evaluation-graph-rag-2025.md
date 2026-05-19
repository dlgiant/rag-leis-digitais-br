# Paper evaluation — "A Graph RAG Approach to Enhance Explainability in Dataset Discovery" (Springer 2025)

**Date:** 2026-05-17
**Paper:** *A Graph RAG Approach to Enhance Explainability in Dataset Discovery*
**Venue:** Data Science and Engineering (Springer Nature), November 2025
**DOI:** [10.1007/s41019-025-00313-x](https://link.springer.com/article/10.1007/s41019-025-00313-x)
**Deliverable type:** Research note + go/no-go (no implementation).
**Plan:** `~/.claude/plans/lucky-questing-nova.md`

⚠️ **Access caveat:** the PDF and abstract page both redirect through Springer's
auth wall. This evaluation is built from the publicly indexed
abstract + descriptions surfaced via web search of the DOI. Recommendation
depth is bounded by that access; specific architectural details
(loss functions, exact prompt templates, dataset splits) are not
verifiable here. The 🟢/🟡/🔴 verdicts below should be re-confirmed if
full paper access becomes available — none of the GO verdicts depend
on details the abstract didn't reveal, but the cost estimates might.

---

## §1 — Paper summary

### Problem

Dataset discovery in large, heterogeneous data ecosystems (Data Lakes,
Data Spaces) suffers from a **lack of transparency** — users get
recommendations but no usable explanation of *why* a dataset matches
their request, *what* it contains, or *how* it aligns with stated
preferences. The paper positions explainability as the core gap.

### Architecture (as described in accessible material)

A four-stage pipeline:

1. **Concept extraction.** User request (natural language) →
   Knowledge Graph (KG) interpretation that extracts relevant
   *dimensions*, *levels*, and *indicators* from the request.
2. **Query translation.** LLM transforms the extracted KG concepts
   into actionable dataset queries against the discovery platform.
3. **Enrichment.** Candidate datasets are enriched with statistical
   metadata (e.g., value distributions — "% of records associated with
   a specific value") and KG-derived contextual knowledge
   (e.g., hierarchical groupings — "Italy ∈ Europe").
4. **LLM ranking + explanation.** An LLM ranks candidates against the
   user's preferences and produces a final report with the ranking +
   natural-language justification grounded in the KG path traversal.

### Two-layer Knowledge Graph

A distinctive structural choice:

- **Static layer** — background knowledge: definitions of dimensions,
  indicators, concept taxonomies. Domain-stable.
- **Dynamic layer** — source-related knowledge: per-source metadata
  profiles + summary representations of source content, aligned (via
  shared concept nodes) with the static layer.

The split lets the static layer be hand-curated once + the dynamic
layer be regenerated as the data ecosystem changes, without redoing
the ontology.

### Evaluation methodology

Beyond traditional ranking correctness, the paper introduces three
**explainability dimensions** as first-class evaluation axes:

- **Coherence** — does the explanation hang together logically?
- **General quality** — overall reader-perceived usefulness
- **Compactness** — is the explanation as short as it can be while
  remaining complete?

These are evaluated via LLM judge (implied — explicit method not
visible in indexed material).

### Bibliographic note

Authors not visible in the indexed abstract. The journal is Data
Science and Engineering (peer-reviewed, Springer Nature, founded
2016, broad data-management scope). November 2025 publication date
means this is post-RAGAS, post-GraphRAG (Microsoft 2024), so the
paper is participating in an active conversation rather than founding
one.

---

## §2 — Project gap surfaces (what this paper might attach to)

For the go/no-go in §3 to be grounded, here are the load-bearing gaps
this project actually has as of post-Phase-7.5:

### Gap A — Refusal discipline (12.2% on external OOS)

Phase 7.5.3 measured 12.2% OOS refusal accuracy on 49 legalbench.br
rows — 6.7× worse than the internal eval (93.8%) claimed. Diagnosed in
[`phase-7.5-findings.md`](phase-7.5-findings.md) §2 Finding 2 as a
generation-side problem: the model is excellent at finding in-corpus
content (97.5% rule recall, 7.5.4) and bad at refusing when content
*isn't* in corpus. The current refusal stack:

- Cosine fast-path threshold (top-1 < 0.40 → refuse pre-LLM)
- LLM self-refusal detection via `_is_self_refusal()` (prefix match)
- SYSTEM_PROMPT mandate to refuse subtype d (OOS adjacent)

The current Phase 8 entry plan is **SYSTEM_PROMPT iteration against
the 49 OOS rows**. The paper offers a structurally different angle:
*concept-level* scope check — independent of prompt phrasing.

### Gap B — Explanation quality as distinct from faithfulness

Audit doc ([`rag-eval-metrics-audit.md`](rag-eval-metrics-audit.md))
row #9 — *RAGAS Answer Relevance* — remains ❌. The project measures
faithfulness (does the generated answer match the `expected_paragraph`?)
but does not measure whether the answer is *responsive* to the
question or whether the citation chain *makes sense* as legal
reasoning. The paper's coherence/quality/compactness dimensions map
directly onto this gap.

### Gap C — Latent graph structure the project has but doesn't query

Three pieces of graph-shaped data exist in the codebase, none of them
queryable as a graph:

- `rag_leis/legal_rank.py` — every chunk has `legal_rank ∈ {1..5}`
  (CF → LC → LO → Decreto → Resolução). Used only by
  `_compute_hierarchy_warning` in `rag.py`. Not used for retrieval
  filtering, not used for explanation generation.
- `rag_leis/parser.py` — detects amendment patterns
  (`amended_by` references inside `<blockquote>` historical noise)
  and strips them from text. Detection is **already implemented**;
  result is **discarded** rather than stored as cross-reference edges.
- `rag_leis/vigencia.py` — vigência overlays carry temporal
  (when-was-revoked-by-whom) edges. Stored per-chunk; not
  cross-queryable.

The paper's "store source metadata as graph nodes aligned with
concept nodes" is exactly the formalism this data is missing.

### Gap D — Pre-retrieval scope check

Today the only pre-LLM scope signal is cosine top-1 < 0.40. Once
cosine passes that threshold, the LLM is on its own to decide
"do these retrieved chunks actually answer the question?" — and 7.5.3
showed it answers wrong 88% of the time when they don't. A structured
scope check ("query is about concept X; no indexed document claims
to cover X") is missing.

---

## §3 — Concept-by-concept mapping (the go/no-go matrix)

| # | Paper concept | Fit | Cost if pursued | Verdict |
|---|---|:---:|---|---|
| 1 | Static KG of legal concepts linked to documents | 🟢 | 2-3 days | **GO** |
| 2 | Per-document summary/scope representation | 🟢 | 1 day | **GO** (ship first) |
| 3 | Explanation-quality eval dimension | 🟢 | 1 day | **GO** |
| 4 | Cross-references as queryable graph edges | 🟡 | 1-2 days | **MAYBE** |
| 5 | Hierarchical communities for retrieval | 🟡 | 3-5 days | **MAYBE** |
| 6 | LLM ranking step using KG paths | 🟡 | 2-3 days | **NO for now** |
| 7 | Dataset queries / data lake statistics | 🔴 | n/a | **NO** |

### #1 — Static KG of legal concepts → 🟢 GO

**Paper concept.** Two-layer KG with static background knowledge
(dimensions/indicators) hand-curated and linked to source metadata.

**Project mapping.** Build a small static concept graph for legal
concepts the corpus covers: *consentimento, dados pessoais, habeas data,
crimes cibernéticos, neutralidade da rede, vazamento, ANPD, etc.* Each
concept node links to the articles in the corpus that operationalize
it. Crucially: a concept node with **zero linked articles** = a topic
the corpus doesn't cover.

**Why it attacks gap A.** Query → concept extraction (LLM call) →
check whether activated concepts have any in-corpus articles. If none
→ high-confidence refusal with a *structured* reason ("query is
about [comodato]; no indexed document covers contract types").
Different mechanism than SYSTEM_PROMPT iteration; **complementary,
not competing**. Could close most of the Pattern B (alucinação para
corpus adjacente) failures from 7.5.3 §3.

**Cost.** 2-3 days:
- Half day: enumerate ~50 concept nodes the corpus actually covers
  (this is a curation task; should be lawyer-reviewed eventually, but
  operator-only is acceptable for v0)
- 1 day: link concepts to articles (LLM-assisted: for each article,
  ask "which of these 50 concepts does this article operationalize?";
  one Sabiá pass over the 7200 chunks ≈ $4-5)
- 0.5 day: integrate as pre-retrieval scope check in `rag.py:answer()`
- 0.5 day: tests + threshold calibration

**Recommendation.** GO, but conditional on #2 working first.

### #2 — Per-document summary / scope representation → 🟢 GO (ship first)

**Paper concept.** Each source has a *summary representation* aligned
with the static KG — "what this source is about" in terms of shared
concepts.

**Project mapping.** Add a `document_scope: list[str]` field to each
document in `corpus.py` (Tier 1/2/3/4 registry). For each of the
~30 indexed documents, write 5-10 concept tags: LGPD →
`[consentimento, dados-pessoais, ANPD, DPO, direitos-do-titular, ...]`.
This is a strict subset of #1 — concepts exist as flat tags first,
upgrade to graph nodes only if it works.

**Why it attacks gap A separately from #1.** The scope check becomes:
*does any indexed document declare it covers any concept the query
touches?* If no — refuse. This is the smallest possible version of the
mechanism; if it doesn't move the 12.2% number, #1 won't either.

**Cost.** 1 day:
- 3-4h: 5-10 concept tags per doc × ~30 docs (operator-only OK)
- 2h: query-side concept extractor (cheap LLM call mapping query →
  concept tags from the fixed vocabulary)
- 2h: integrate as second-tier scope check after cosine fast-path
- Tests

**Recommendation.** **Ship first** if any KG-related work happens.
Cheap, low-risk, fail-fast validates whether the whole "concept
matching" hypothesis has signal in this corpus.

### #3 — Explanation-quality evaluation dimension → 🟢 GO

**Paper concept.** Evaluate not just ranking correctness but the
explanation itself across three dimensions: coherence, general quality,
compactness.

**Project mapping.** Add a new LLM-judge call in `run_answer_eval.py`
(parallel to faithfulness): judge the *answer text* against three
axes. Reuses the existing Opus-4-7 judge infrastructure +
`_fold_judge_cost_into_answer()` (Phase 7.5.7). Closes audit doc gap
#4 (RAGAS Answer Relevance is the same shape).

**Why this is independent of #1/#2.** No KG required. Pure eval
expansion. Can ship before any pipeline change.

**Cost.** 1 day:
- 2h: judge prompt design (3 axes, one structured-output schema)
- 2h: integrate into `Aggregate` + serialization
- 2h: run baseline on the existing 29-row answer-eval + concurso
  pilot ($1-2 cost)
- 2h: tests + findings doc

**Recommendation.** GO. Lowest-risk concept in this paper; aligns
with already-prioritized audit-doc gap.

### #4 — Cross-references as queryable graph edges → 🟡 MAYBE

**Paper concept.** Source-to-source relationships stored as
first-class graph edges.

**Project mapping.** Parser already detects `amended_by`
relationships (currently strips them from text + discards). Promoting
to a stored edge would let queries like "what's been amended by
14.155/2021?" be served from the graph instead of full-text.

**Why MAYBE.** Clean engineering work, but **no immediate
user-facing benefit** in the current question shapes. The 104-query
eval set has no "amendment-traversal" queries; the discursive set has
none. Without a use case demanding it, this is build-it-and-they-might-
come work.

**Park unless** a specific user query shape emerges that needs cross-
reference traversal, or a future TIER document type (legislative
history archives?) requires it structurally.

### #5 — Hierarchical communities for retrieval → 🟡 MAYBE

**Paper concept.** Group entities into hierarchical communities (the
canonical example: Italy ⊂ Europe), used as a retrieval pruning /
expansion signal.

**Project mapping.** Run a community-detection algorithm (Leiden /
Louvain) over the KG built in #1, use community membership as a
retrieval filter or as a re-ranking signal.

**Why MAYBE.** The existing dense retrieval already hits 97.5% in-
corpus rule recall (7.5.4). The ceiling for retrieval improvement is
small — at most ~2.5pp. Returns diminish fast against the engineering
cost.

**Defer** until evidence emerges that retrieval itself is leaving
points on the table (today the evidence says it isn't).

### #6 — LLM ranking step using KG paths → 🟡 NO for now

**Paper concept.** After candidate retrieval, an LLM ranks them using
KG-path features (concept overlap with query, semantic distance, etc.)
as ranking criteria.

**Project mapping.** Add a re-ranking step before context construction
in `rag.py`, using LLM judgment over KG-derived features.

**Why NO for now.** This project has **empirically refuted**
re-ranking with cross-encoders ([`posts/02-stronger-reranker-worse-performance.md`](../posts/02-stronger-reranker-worse-performance.md))
and hybrid retrieval ([`posts/03-hybrid-rrf-didnt-work.md`](../posts/03-hybrid-rrf-didnt-work.md)).
Re-litigating with "but now with KG features!" requires a fresh
hypothesis with new evidence. The bar is high.

**Re-justify only if** #1+#2 produce a working KG and an unmet need
for finer ranking emerges.

### #7 — Dataset queries / data lake statistics enrichment → 🔴 NO

**Paper concept.** Enrich candidate datasets with value distributions
("% of records with value X").

**Project mapping.** None. The project's corpus is legal *text*, not
tabular datasets. There are no columns, no value distributions, no
statistical metadata to compute. The concept doesn't translate.

---

## §4 — Recommended uptake order (if any GO items are pursued)

If a future Phase picks up any GO concept, the order is:

### Step 1 — Ship #3 (explanation-quality eval) first

**Independent** of any KG work. Adds a measurement axis the audit doc
flagged as ❌. If the existing system scores well on coherence/quality
already, that's useful baseline; if it scores poorly, that's the same
"refusal discipline" diagnostic showing up on the explanation surface.

Either way, no architecture risk. 1 day, ~$1-2 API.

### Step 2 — Ship #2 (document scope representation) second

**Smallest version of the KG idea.** Flat tags, no graph. Tests
whether the concept-matching mechanism produces signal on the 49
legalbench OOS rows. **Fail-fast gate:**

- Re-run `legalbench_br_oos.yaml` with scope check enabled
- If `oos_refusal_recall` moves from 0.122 by less than +0.10 (i.e.,
  doesn't get to 22% or higher), **stop**. The mechanism doesn't have
  signal in this corpus; #1 won't either.
- If it moves by ≥0.10, proceed to #1.

1 day, ~$5 API (initial concept tagging + re-run).

### Step 3 — Ship #1 (static KG) third, only if #2 cleared the gate

Upgrade flat tags to a proper KG with relationships
(*broader-than*, *related-to*, *contradicted-by*, etc.). Adds
explanation-generation capability the flat-tag version can't produce.

2-3 days, ~$5-10 API.

Each step has the property that **its independent value is non-zero**
— shipping just #3 closes a known audit gap; shipping #3+#2 closes
the gap *and* moves the refusal numbers (if the hypothesis holds);
shipping all three turns the project into "Graph RAG with concept-
level scope checking and grounded explanations" — a portfolio-grade
narrative.

The order also has the property that **wrong-direction failure is
detected early**. If the concept-matching idea is wrong for this
corpus, #2's eval re-run shows it before #1's curation cost has been
incurred.

---

## §5 — Honest non-takeaways (what the paper does NOT transfer)

### Knowledge graphs aren't free in this domain

The paper's KG is over **datasets** (schemas, value distributions,
hierarchical groupings like "Italy ∈ Europe"). Much of that auto-
extracts from structured metadata. A legal concept ontology can be
seeded by an LLM but **needs lawyer review to be trustworthy** for a
production legal system. That review is a D7 / Phase 9 dependency,
not a Phase 8 dependency. The cost estimates in §3 assume operator-
only v0; production-quality version is 5-10× the estimate.

### Their explainability is not our explainability gap

The paper's explainability problem is "user got recommendations, no
idea why" — explanations don't exist at all. This project's
explainability problem is the opposite: explanations exist (verified
URN citations + "Fontes consultadas em DD/MM/AAAA" footer + cite-and-
verify guard) but **don't generalize beyond URN-level**. The user
gets "I cite LGPD art. 7º X" but no "and here's why this article
covers your question." The paper's mechanisms close THIS specific
gap, but framing it as "the system has no explanations today" would
be inaccurate.

### Re-litigating already-refuted techniques carries a cost

Concepts #5 (community-based retrieval) and #6 (LLM re-ranking)
graze territory the project already investigated and refuted (rerankers
in [post 02], hybrid in [post 03], gated router in
[post 04](../posts/04-title-prefix-broke-my-routing-intuition.md)).
"This time with KG features!" is a coherent hypothesis but
requires the same level of empirical work to validate. Default is
**don't re-litigate**; specific evidence required to revisit.

### The paper is one Graph RAG paper among several

Microsoft's GraphRAG (2024), KG-SMILE (arxiv 2509.03626), KGRAG-Ex
(arxiv 2507.08443), and others all live in this space. The Springer
paper offers one architectural variation (the static/dynamic KG split
is the distinctive piece visible in the abstract). A real "Graph RAG
for this project" decision would warrant a comparative survey across
these papers, not just this one. **That's a different document** —
this note answers "is there anything useful in THIS paper" not "what's
the best Graph RAG approach."

---

## §6 — Cross-references

### Project context for the verdicts above

- [`phase-7.5-findings.md`](phase-7.5-findings.md) §2 Finding 2 —
  refusal-discipline gap (the load-bearing case for #1 + #2)
- [`phase-7.5.3-legalbench-oos-findings.md`](phase-7.5.3-legalbench-oos-findings.md)
  §3 — three SYSTEM_PROMPT/code fixes already proposed as the
  *alternative* path to fix refusal discipline. The KG-based concepts
  in this paper are a different angle, not a replacement.
- [`rag-eval-metrics-audit.md`](rag-eval-metrics-audit.md) row #9
  (Answer Relevance) — what concept #3 closes; row #31 (hierarchy
  compliance) — what `legal_rank` already does
- [`query-expansion-plan.md`](query-expansion-plan.md) — methodology
  template for any future "concept extraction eval set" work

### Code surfaces a future implementer would touch

- `rag_leis/rag.py:282-340` — `RAGAnswer` dataclass; new signals
  would land here as fields (e.g., `concept_scope_refused: bool`,
  `explanation_quality_score: dict[str, float]`)
- `rag_leis/legal_rank.py` — existing graph-shaped data the project
  doesn't currently treat as a graph (1-of-5 sources for #1)
- `rag_leis/parser.py` — `amended_by` detection that's currently
  thrown away (1-of-5 sources for #1/#4)
- `rag_leis/vigencia.py` — temporal edges (revoked-by) that could
  become first-class KG edges
- `rag_leis/corpus.py` — where a `document_scope: list[str]` field
  for concept #2 would attach
- `rag_leis/run_answer_eval.py` — where the explanation-quality judge
  for #3 would land

### Project decisions/policies the verdicts respect

- BACKLOG.md § OOS hardening — Phase 8 entry priority is refusal
  discipline; the GO concepts here support that priority rather than
  competing with it
- Memory `feedback-paid-api-caution` — cost estimates in §3 are
  explicit and small per item; no concept here triggers a "burn API
  speculatively" anti-pattern
- Memory `project-purpose-production` — production framing means
  lawyer review (D7) is the natural eventual gate for #1's concept
  curation, even though v0 can be operator-only

---

## §7 — One-paragraph TL;DR

The paper proposes a two-layer Knowledge Graph (static concepts +
dynamic source metadata) plus an LLM-grounded explanation step.
**Three of seven concepts transfer well to this project**:
explanation-quality evaluation (closes a known audit gap; 1 day),
per-document scope representation (cheapest possible attack on the
12.2% refusal gap; 1 day, fail-fast), and full static concept KG
(stronger attack on the same gap; 2-3 days, only after the scope
representation shows signal). **Four concepts are weak or refuted
fits**. The strongest single contribution is offering a *structurally
different* angle on refusal discipline than SYSTEM_PROMPT iteration —
complementary, not competing. **No implementation work in this note**;
decision belongs to a future Phase 7.6 or Phase 8 design step.
