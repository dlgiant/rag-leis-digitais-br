"""End-to-end RAG pipeline with structured-output + cite-and-verify guards.

Wires together what the rest of the project produced separately:
  * retrieval (voyage dense, `title+label+nav+caput+text`, top-K)
  * generation (Anthropic, claude-sonnet-4-5, tool_choice forced)
  * verification (URN ∈ corpus ∧ ∈ top-K)
  * OOS gating (top-1 cosine < threshold → refuse before paying for the LLM)

The pipeline is intentionally synchronous and stateless per-call: each
`.answer()` is one retrieve + one LLM call + one post-check. We don't
cache LLM responses; that's a Phase 3 concern if it ever matters.

Design notes:

* Context format uses XML-style `<fonte urn="...">` tags. Anthropic's
  prompting guide recommends XML delimiters when the model has to extract
  identifiers verbatim — and that's exactly what we ask it to do with URNs.

* Temperature is 0.0 by default. Citation accuracy is a deterministic
  task; we don't want sampling variation in legal answers.

* The OOS threshold defaults to 0.50 as a placeholder; Phase 2.7 will
  calibrate this from the answer-eval set's OOS rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from rag_leis.corpus import TIER_1, TIER_2, TIER_3
from rag_leis.embeddings import Embedder, Vec, get_embedder
from rag_leis.eval_harness import IndexChunk, format_texts, load_chunks
from rag_leis.legal_rank import rank_name
from rag_leis.llm import LLM, get_llm
from rag_leis.pii import RedactedQuery, redact
from rag_leis.pii_audit import write_audit
from rag_leis.prose_check import (
    ProseMismatch,
    build_reprompt_message,
    check_prose_vs_citations,
)
from rag_leis.query_type import (
    TOP_K_PER_TYPE,
    classify_query,
    prompt_snippet_for_query,
)
from rag_leis.verify import verify_citations
from rag_leis.vigencia import Vigencia, vigencia_warning

DEFAULT_TOP_K = 10

# Phase 5.5: doc URN → human-readable title for rendering source-as-of
# footers. Built lazily from the corpus registry; missing URNs fall back
# to a friendly slug from the URN itself.
TITLE_BY_URN: dict[str, str] = {
    d.urn: d.title for d in (*TIER_1, *TIER_2, *TIER_3)
}


def _doc_label(doc_urn: str) -> str:
    """Human title for `doc_urn`, with a defensive fallback."""
    if doc_urn in TITLE_BY_URN:
        return TITLE_BY_URN[doc_urn]
    # Fallback: derive a short label from the URN type+id
    parts = doc_urn.split(":")
    if len(parts) >= 6:
        return f"{parts[4]} {parts[5].replace(';', '/')}"
    return doc_urn


def _format_date_pt_br(iso_date: str) -> str:
    """ISO date YYYY-MM-DD → DD/MM/YYYY (BR convention)."""
    parts = iso_date.split("-")
    # Must be 3 parts, all digits, lengths 4/2/2 — otherwise pass through.
    # Avoids reformatting strings that happen to contain dashes ("not-a-date"
    # → "date/a/not" was the bug this guards).
    if (
        len(parts) == 3
        and all(p.isdigit() for p in parts)
        and len(parts[0]) == 4
        and len(parts[1]) == 2
        and len(parts[2]) == 2
    ):
        y, m, d = parts
        return f"{d}/{m}/{y}"
    return iso_date  # malformed; pass through


def _render_sources_footer(sources_dates: dict[str, str]) -> str:
    """Build the 'Fontes consultadas em: ...' practitioner-facing footer.

    Sorted by doc URN for stable output across runs (so a UI can diff
    answers without footer re-ordering causing churn).
    """
    items = sorted(sources_dates.items())
    parts = [
        f"{_doc_label(urn)} ({_format_date_pt_br(date)})"
        for urn, date in items
    ]
    return "—\nFontes consultadas em: " + "; ".join(parts) + "."
DEFAULT_AUDIT_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "audit" / "pii-redactions.jsonl"
# Cosine threshold below which we refuse before paying for the LLM call.
# Phase 2.7 measured the OOS-vs-in-scope distribution: OOS top-1 sims
# (0.52-0.65) overlap the in-scope range (0.56-0.75), so no clean cosine
# threshold separates them. The cosine gate is now a *fast-path* for very
# clearly OOS queries (e.g. someone pasting a paragraph in a different
# language); the load-bearing OOS detection happens at the LLM-self-refusal
# level, since the model has full context to make that call.
DEFAULT_OOS_THRESHOLD = 0.40
# Phase 6.6 r4 (2026-05-16): switched from `label+nav+caput+text` to
# `title+label+nav+caput+text`. Hypothesis test surfaced by Phase 6.6 audit
# (art.13 MCI vs Decreto 8.771 art.13 cross-corpus collision): prepending the
# document title to every chunk text disambiguates lei/decreto/súmula at the
# dense embedder level. Empirical lift on the 104-query eval (vs prior default):
#   nDCG@10  : 0.7031 → 0.7223 (+0.019)
#   MRR@10   : 0.7785 → 0.8040 (+0.026)
#   Recall@20: 0.8772 → 0.8705 (-0.007 — single-digit regression accepted)
# Per-type: citacao-literal MRR +0.130 (biggest single-category win in project).
# Trade documented in scripts/eval_hybrid_router.py (the hybrid alternative
# was dominated for our nDCG-optimized RAG-to-LLM use case).
DEFAULT_TEXT_MODE = "title+label+nav+caput+text"
DEFAULT_EMBEDDER = "voyage-3-large"

# Phrase patterns that mean "the LLM examined the context and decided it
# can't answer". The system prompt instructs the model to LEAD with one
# of these phrases on refusals, but Phase 7.5.3 (legalbench OOS) found
# the model often produces the refusal CONCLUSION mid-paragraph after a
# preamble explaining what it tried — Pattern A in the findings doc.
#
# These specific phrasings include qualifiers like "suficiente" /
# "fornecidas" / "possível encontrar" that make false positives in real
# answers very unlikely. The guard test
# `test_real_answer_mentioning_no_info_inline_is_NOT_refusal` covers
# the "não há informação" plain-substring failure mode.
_SELF_REFUSAL_PHRASES = (
    "não há informação suficiente",
    "não há informações suficientes",
    "não foi possível encontrar",
    "as fontes fornecidas não",
    "fora do escopo",
)


def _is_self_refusal(answer_text: str) -> bool:
    """True when the LLM is signaling it couldn't answer from the given
    sources, regardless of WHERE in the answer the signal appears.

    Phase 7.7 (2026-05-19) widened this from a 120-char prefix scan to a
    full-text substring search — Pattern A in `phase-7.5.3-legalbench-oos-findings.md`
    showed the model often refuses mid-paragraph after a preamble, and
    the old prefix-only check missed those rows entirely.
    """
    if not answer_text:
        return False
    text = answer_text.lower()
    return any(phrase in text for phrase in _SELF_REFUSAL_PHRASES)


# ----------------------------------------------------------------------------
# Output schema (Phase 2.3): structured-output contract for the generator.
# ----------------------------------------------------------------------------

ANSWER_TOOL: dict[str, Any] = {
    "name": "responder",
    "description": (
        "Submeta a resposta final em formato estruturado. Cite cada artigo/lei "
        "usado pelo URN canônico EXATO fornecido no contexto (campo urn da tag "
        "<fonte>). Não invente URNs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": (
                    "Resposta em português, formal e objetiva. Cite os artigos "
                    "inline usando o rótulo do contexto (ex: 'Art. 7, I'). "
                    "Se não houver informação suficiente nas fontes, diga "
                    "explicitamente 'Não há informação suficiente nas fontes fornecidas.'"
                ),
            },
            "citations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Lista dos URNs canônicos exatos (do atributo urn= das tags "
                    "<fonte>) que sustentam a resposta. Vazia se a resposta for "
                    "uma recusa por insuficiência de fontes."
                ),
            },
            "unverified_claims": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Afirmações incluídas na resposta que não estão diretamente "
                    "sustentadas pelas fontes fornecidas. Idealmente vazia. "
                    "Use para sinalizar inferências ou conhecimento adicional."
                ),
            },
        },
        "required": ["answer", "citations", "unverified_claims"],
    },
}


SYSTEM_PROMPT = """\
Você é um assistente jurídico especializado em legislação digital brasileira.
Sua tarefa: responder à pergunta do usuário usando EXCLUSIVAMENTE as fontes \
fornecidas no contexto (tags <fonte>).

Regras inegociáveis:

1. Cada afirmação factual na resposta DEVE ser sustentada por uma tag <fonte> \
do contexto. Não use conhecimento externo, mesmo que correto.

2. Cite cada fonte pelo URN canônico EXATO do atributo urn="..." da tag <fonte>. \
Não modifique, abrevie ou invente URNs. Não cite URNs que não estejam no contexto.

3. **REGRA DE RECUSA — explícita por categoria**. Recuse a query (retornando \
o texto literal "Não há informação suficiente nas fontes fornecidas." no `answer`, \
com `citations` vazia) quando:

(a) A pergunta cita projeto de lei (PL nº XXXX), proposição em tramitação, \
ou pede sobre "lei brasileira de [matéria]" sem que essa matéria esteja \
positivada nas <fonte>. As <fonte> contêm apenas leis JÁ PROMULGADAS — você \
NÃO tem como saber o estado atual de PLs. NÃO tente inferir do contexto \
qualquer afirmação sobre PLs em tramitação. Exemplos do que recusar: \
"PL 2630 fake news", "Lei brasileira de IA" (PL 2338), "Marco Legal dos \
Games" (PL 2796), "lei dos criptoativos" (Lei 14.478/2022 ou PL 4408 — \
não estão indexadas).

(b) A pergunta é sobre direito ESTADUAL ou MUNICIPAL. O corpus indexa \
APENAS legislação federal. Recuse mesmo que o tópico geral seja conhecido. \
Exemplo: "lei estadual paulista sobre câmeras", "decreto municipal RJ".

(c) A pergunta exige uma fonte JURISPRUDENCIAL específica (STF, STJ, \
súmulas, temas de repercussão geral) ou uma DOUTRINA específica que não \
está positivada em norma nas <fonte>. Exemplo: "direito ao esquecimento \
como princípio autônomo" (rejeitado pelo STF Tema 786 — não temos o Tema \
786 no contexto), "princípio da minimização excessiva" (construção \
doutrinária).

(d) A pergunta toca um tópico adjacente ao corpus mas requer normas \
NÃO-INDEXADAS (CPC, Lei 9.296 interceptação, LC 182 startups, Lei 14.133 \
licitações, etc.) para uma resposta operacional. Mesmo que LGPD/MCI/CDC \
apareçam tangencialmente no contexto, NÃO RESPONDA PARCIALMENTE — uma \
resposta parcial sobre o tópico-alvo implica autoridade que você não tem.

Em qualquer dessas categorias, em `unverified_claims` explique brevemente \
QUAL norma faltou ou POR QUE recusou (ex: "PL 2338/2023 — Lei de IA não \
promulgada"). Use `unverified_claims` como rastro para auditoria, NÃO como \
substituto da resposta.

Se a pergunta NÃO se enquadra em (a-d) mas mesmo assim as <fonte> \
fornecidas não contêm informação suficiente, recuse igualmente com a \
mesma frase canônica.

4. Em `unverified_claims`, liste qualquer afirmação que tenha sido incluída \
mas que não esteja sustentada pelo contexto. Idealmente vazia.

5. Responda em português, em tom formal e técnico, mas claro.

6. **Vigência ressalvada — REGRA CRÍTICA**: se uma `<fonte>` tiver atributo \
`vigencia=`, a aplicação do dispositivo está RESSALVADA (sub judice, suspensa, \
eficácia limitada por regulamentação, etc.). Sempre que sua resposta usar uma \
fonte assim, INCLUA, ao final do parágrafo correspondente (ou em parágrafo \
próprio), uma sentença iniciando com "⚠️ Atenção:" reproduzindo o conteúdo \
da ressalva — status, fundamento (processo / ato normativo) e o que isso \
significa para a aplicação do dispositivo. Não silencie a ressalva, mesmo \
que o usuário não tenha perguntado sobre ela.
"""


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class FlaggedVigencia:
    """One cited URN that carries a vigência overlay. Computed
    deterministically from the verified citations + overlays — not from
    the LLM. Surfaces what the model SHOULD have warned about so callers
    can post-validate (e.g., assert the answer text contains the warning
    for each entry here)."""
    urn: str
    status: str
    fundamento: str
    descricao_curta: str


@dataclass
class RAGAnswer:
    """One end-to-end response from the pipeline.

    Carries enough provenance for downstream eval (citation metrics,
    faithfulness judge, refusal accuracy) and for a UI to surface
    confidence signals.
    """

    answer: str
    citations: list[str]                            # URNs that passed verify
    unverified_claims: list[str]                    # self-marked by the LLM
    rejected_citations: list[tuple[str, str]]      # (reason, urn) pairs
    refused: bool
    refusal_reason: str | None
    raw_retrieval: list[tuple[str, float]]         # (urn, cosine_sim) top-K
    flagged_vigencia: list[FlaggedVigencia] = field(default_factory=list)
    # Phase 4.1 observability: which type the classifier assigned + the
    # effective top_k used. None when the pipeline refused on the cosine
    # fast-path (no classifier run, no retrieval beyond top-1).
    classified_type: str | None = None
    classified_top_k: int | None = None
    # Phase 4.2: PII types redacted before query crossed provider boundary.
    # Empty list when the query had no PII OR when redact_pii=False.
    pii_types_redacted: list[str] = field(default_factory=list)
    # Phase 5.2: hierarchy warning string when the LLM cites lower-rank
    # sources (e.g., Decreto, Resolução) while higher-rank sources (CF, LC,
    # LO) were in top-K context. None when not applicable.
    hierarchy_warning: str | None = None
    # Phase 5.3: prose-citation mismatches the answer text contains
    # references (Art. N, X) that don't match any verified citation URN.
    # Empty list = clean. After Phase 5.3 reject-and-reprompt loop, this
    # represents the FINAL state — what survived the retry.
    prose_citation_mismatches: list[ProseMismatch] = field(default_factory=list)
    prose_check_retried: bool = False  # True if reject-and-reprompt fired
    # Phase 5.5: per-cited-document source-as-of date. Derived from the
    # IndexChunk.fetched_at of cited URNs. Rendered into the answer text
    # as a "Fontes consultadas em: ..." footer for practitioner transparency.
    # Empty dict when no in-scope citations.
    sources_consulted_at: dict[str, str] = field(default_factory=dict)
    # Phase 7.5.2: per-call cost + token accounting. Populated by RAGPipeline
    # from `llm.last_call_usage` after each LLM call (initial + optional
    # retry). Cost computed via rag_leis.cost.estimate. Zero for OOS rows
    # that fast-pathed on cosine and skipped LLM. Surfaced into:
    #   - per-query logs (eval/runs/*.json)
    #   - Aggregate.cost_total_usd + cost_mean_usd in run_answer_eval
    # Operator uses to spot expensive paths (prose_check_retried adds a
    # second LLM call → cost roughly doubles for the affected row).
    cost_estimate_usd: float = 0.0
    tokens_used: dict[str, int] = field(default_factory=dict)  # {input_tokens, output_tokens}
    llm_calls: int = 0  # count of LLM calls — 0 if cosine fast-path refused
    # Phase 7.5.7 — SRE Golden Signal: end-to-end wall-clock latency from
    # RAGPipeline.answer entry to return, in milliseconds. Includes PII
    # redaction + classify + retrieval + LLM + optional retry + post-process.
    # Fast-path OOS rows still get a latency reading (typically <50ms).
    # Aggregated into latency_p50/p95/p99_ms by eval runners.
    latency_ms: float = 0.0


# ----------------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------------


@dataclass
class RAGPipeline:
    embedder: Embedder
    urns: list[str]
    doc_vecs: Vec
    chunks_by_urn: dict[str, IndexChunk]
    llm: LLM
    # `top_k` is now the FALLBACK / classifier-disabled default. When the
    # classifier is enabled (default True), it picks top_k per query type
    # from query_type.TOP_K_PER_TYPE. Callers can disable classifier to
    # restore Phase 2 behavior for A/B comparison.
    top_k: int = DEFAULT_TOP_K
    oos_threshold: float = DEFAULT_OOS_THRESHOLD
    adaptive_top_k: bool = True
    # Phase 4.2: PII redaction before query crosses provider boundary.
    # Default ON in production framing — system that handles LGPD must
    # itself comply. Disable in tests where deterministic embeddings of
    # raw query are needed.
    redact_pii: bool = True
    pii_audit_log: Path | None = DEFAULT_AUDIT_LOG_PATH
    # Phase 5.3: prose-vs-URN consistency check. When the LLM's answer
    # prose says "Art. 5, XII" but no cited URN ends with art5;inc12,
    # re-prompt the LLM (max 1 retry) with the specific mismatch info.
    # Adds 1 LLM call per mismatch event; production tradeoff for
    # closing the unmonitored hallucination surface.
    prose_check_retry: bool = True
    # Phase 7.6.2 — concept-scope gate. When True, after cosine fast-path
    # passes, an LLM-extractor maps the query onto CONCEPT_VOCABULARY; if
    # query touches concepts AND retrieval covers none of them, refuse
    # pre-main-LLM. Default True in production framing; tests + A/B
    # comparisons can disable.
    scope_check_enabled: bool = True
    corpus_urns: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        self.corpus_urns = frozenset(self.urns)

    # ------------------------------------------------------------------

    def answer(self, query: str) -> RAGAnswer:
        # Phase 7.5.7 — SRE Golden Signal #1 (latency). monotonic, not
        # wall-clock, so NTP corrections / DST never produce negatives.
        import time as _time
        _t0 = _time.monotonic()

        # PII redaction comes FIRST — before classifier, retrieval, LLM.
        # The query crosses no provider boundary in its original form.
        # The classifier operates on the redacted query (placeholders
        # preserve the semantic shape — "vazaram [CPF#1] do [PERSON#1]"
        # still classifies as paráfrase, which is the right call).
        import contextlib

        rq: RedactedQuery | None = None
        if self.redact_pii:
            rq = redact(query)
            query_for_pipeline = rq.redacted_text
            if self.pii_audit_log is not None:
                # Audit log write failure is non-fatal for the query path.
                # Production should monitor this via logging; for v0 we
                # silently degrade (better to serve the user than 500).
                with contextlib.suppress(OSError):
                    write_audit(rq, self.pii_audit_log)
        else:
            query_for_pipeline = query

        # Classifier runs on the redacted query (preserves semantic shape).
        if self.adaptive_top_k:
            classified = classify_query(query_for_pipeline)
            effective_top_k = TOP_K_PER_TYPE.get(classified, self.top_k)
        else:
            classified = None
            effective_top_k = self.top_k

        retrieved = self._retrieve(query_for_pipeline, effective_top_k)
        top1_score = retrieved[0][1] if retrieved else 0.0

        pii_types = sorted(rq.pii_types_found) if rq else []

        # Fast-path OOS: cosine top-1 too low to bother calling the LLM.
        # Threshold is intentionally lenient; the LLM does the substantive
        # OOS detection downstream once it has the actual context.
        if top1_score < self.oos_threshold:
            return RAGAnswer(
                answer="Fora do escopo da base.",
                citations=[],
                unverified_claims=[],
                rejected_citations=[],
                refused=True,
                refusal_reason=(
                    f"cosine fast-path: top-1 {top1_score:.3f} < {self.oos_threshold:.3f}"
                ),
                raw_retrieval=retrieved,
                classified_type=classified,
                classified_top_k=effective_top_k,
                pii_types_redacted=pii_types,
                prose_citation_mismatches=[],
                prose_check_retried=False,
                latency_ms=(_time.monotonic() - _t0) * 1000.0,
            )

        # Phase 7.6.2 — concept-scope gate. After cosine fast-path passes
        # (so we have plausibly-relevant retrieval), check whether the
        # query's concepts overlap with the retrieved documents' scopes.
        # If query touches concepts AND retrieval covers NONE of them →
        # refuse before main LLM call. Defensive: empty query-concepts
        # never triggers refusal (defer to downstream gates).
        if self.scope_check_enabled:
            from rag_leis.concept_scope import (
                check_scope_overlap,
                extract_concept_tags,
            )
            from rag_leis.cost import estimate as _cost_estimate

            query_concepts = extract_concept_tags(query_for_pipeline, self.llm)
            # Fold extractor cost immediately; it's the only LLM call so
            # far if the gate ends up refusing here.
            extractor_in_t = 0
            extractor_out_t = 0
            extractor_cost = 0.0
            usage = getattr(self.llm, "last_call_usage", None)
            if usage:
                extractor_in_t = int(usage.get("input_tokens", 0))
                extractor_out_t = int(usage.get("output_tokens", 0))
                extractor_cost = _cost_estimate(
                    self.llm.provider, self.llm.name,
                    extractor_in_t, extractor_out_t,
                )

            retrieved_doc_urns = [
                urn.split("~", 1)[0] for urn, _ in retrieved
            ]
            should_refuse, retrieval_concepts = check_scope_overlap(
                query_concepts, retrieved_doc_urns
            )
            if should_refuse:
                # Cap reported concepts for log readability — full set
                # available via per-row JSON output if needed.
                top_retrieval = sorted(retrieval_concepts)[:5]
                reason = (
                    f"concept-scope-mismatch: "
                    f"query=[{','.join(query_concepts)}] "
                    f"vs retrieval=[{','.join(top_retrieval)}]"
                )
                return RAGAnswer(
                    answer="Fora do escopo da base (verificação semântica).",
                    citations=[],
                    unverified_claims=[],
                    rejected_citations=[],
                    refused=True,
                    refusal_reason=reason,
                    raw_retrieval=retrieved,
                    classified_type=classified,
                    classified_top_k=effective_top_k,
                    pii_types_redacted=pii_types,
                    prose_citation_mismatches=[],
                    prose_check_retried=False,
                    cost_estimate_usd=round(extractor_cost, 6),
                    tokens_used={
                        "input_tokens": extractor_in_t,
                        "output_tokens": extractor_out_t,
                    },
                    llm_calls=1,
                    latency_ms=round((_time.monotonic() - _t0) * 1000.0, 3),
                )
            # Gate cleared — extractor cost gets folded into the main
            # accumulator below (cost_total / tokens_total / llm_call_count
            # start at extractor's contribution).
            _scope_check_extra = {
                "in_tokens": extractor_in_t,
                "out_tokens": extractor_out_t,
                "cost": extractor_cost,
            }
        else:
            _scope_check_extra = None

        context = self._build_context(retrieved)
        # Per-type prompt snippet (Phase 4.1) — appended to the base
        # SYSTEM_PROMPT so the model gets shape-specific guidance without
        # losing the load-bearing rules (cite-and-verify, vigência flag).
        snippet = (
            prompt_snippet_for_query(query_for_pipeline) if self.adaptive_top_k else ""
        )
        system_prompt = SYSTEM_PROMPT + ("\n\n" + snippet if snippet else "")
        user_msg = f"Pergunta: {query_for_pipeline}\n\nFontes:\n{context}"
        result = self.llm.complete_structured(system_prompt, user_msg, ANSWER_TOOL)

        # Phase 7.5.2 — accumulate token usage + cost across LLM calls.
        # First call (initial answer). Retry adds to the same counters below.
        # Phase 7.6.2 — seed with the concept-extractor's contribution if
        # the scope-check ran and cleared.
        from rag_leis.cost import estimate as _cost_estimate
        tokens_total = {"input_tokens": 0, "output_tokens": 0}
        cost_total = 0.0
        llm_call_count = 0
        if _scope_check_extra:
            tokens_total["input_tokens"] += _scope_check_extra["in_tokens"]
            tokens_total["output_tokens"] += _scope_check_extra["out_tokens"]
            cost_total += _scope_check_extra["cost"]
            llm_call_count += 1
        usage = getattr(self.llm, "last_call_usage", None)
        if usage:
            tokens_total["input_tokens"] += usage["input_tokens"]
            tokens_total["output_tokens"] += usage["output_tokens"]
            cost_total += _cost_estimate(
                self.llm.provider, self.llm.name,
                usage["input_tokens"], usage["output_tokens"],
            )
            llm_call_count += 1

        answer_text = str(result.get("answer", ""))
        cited = [str(u) for u in result.get("citations", [])]
        retrieved_urns = frozenset(u for u, _ in retrieved)
        verified, rejected = verify_citations(cited, retrieved_urns, self.corpus_urns)

        # Phase 5.3: prose-vs-URN consistency check. If the answer prose
        # references articles/incisos/paragraphs that don't match any
        # verified URN, re-prompt with explicit correction instructions
        # (max 1 retry). The retry can fix two ways:
        #   - rephrase the prose to match URNs already cited, OR
        #   - add/swap the URN in citations[] to match the prose
        # We accept whichever the LLM chooses on retry.
        prose_mismatches = check_prose_vs_citations(answer_text, verified)
        prose_retried = False
        if prose_mismatches and self.prose_check_retry:
            prose_retried = True
            reprompt = build_reprompt_message(prose_mismatches)
            retry_msg = f"{user_msg}\n\n--- CORREÇÃO SOLICITADA ---\n{reprompt}"
            try:
                retry_result = self.llm.complete_structured(
                    system_prompt, retry_msg, ANSWER_TOOL,
                    max_tokens=4096,  # bump for retry — reprompt adds context
                )
                # Phase 7.5.2 — accumulate retry tokens/cost.
                usage = getattr(self.llm, "last_call_usage", None)
                if usage:
                    tokens_total["input_tokens"] += usage["input_tokens"]
                    tokens_total["output_tokens"] += usage["output_tokens"]
                    cost_total += _cost_estimate(
                        self.llm.provider, self.llm.name,
                        usage["input_tokens"], usage["output_tokens"],
                    )
                    llm_call_count += 1
                # Take the retry's output regardless — even if mismatches
                # remain. The flag tells the caller a retry happened.
                answer_text = str(retry_result.get("answer", answer_text))
                cited = [str(u) for u in retry_result.get("citations", cited)]
                verified, rejected = verify_citations(
                    cited, retrieved_urns, self.corpus_urns
                )
                prose_mismatches = check_prose_vs_citations(answer_text, verified)
            except Exception:
                # Best-effort retry. Failures (max_tokens hit, 429, tool-call
                # breakage, transport error, etc.) fall back to the original
                # output. prose_retried=True with mismatches still populated
                # is the production observability signal.
                pass

        # LLM-self-refusal: model read the context and emitted the canonical
        # "informação insuficiente" prefix. This is the strongest OOS signal
        # we have — it's the model's judgment with full context, not a
        # surface-similarity threshold. Mark refused; preserve the answer
        # text and any citations the model managed to attach (could still
        # be useful for "I can't answer but here's what I found"-style UIs).
        self_refused = _is_self_refusal(answer_text)

        # Phase 7.7 Fix #2 — implicit refusal via empty citations. Pattern C
        # from phase-7.5.3-legalbench-oos-findings.md: the model produces an
        # answer using "general legal knowledge" with no URN citations at
        # all. cite-and-verify passes vacuously (nothing to verify), so the
        # row counted as a non-refusal answer despite being unverifiable.
        # Treat empty `verified` on a non-self-refusal answer as an implicit
        # refusal — if the model couldn't ground anything in the corpus, the
        # answer can't be trusted regardless of how confident the prose is.
        implicit_refused_empty_cites = False
        if not self_refused and not verified:
            implicit_refused_empty_cites = True
            self_refused = True

        flagged = self._collect_flagged_vigencia(verified)
        hier_warn = self._compute_hierarchy_warning(verified, retrieved)
        sources_dates = self._collect_sources_consulted_at(verified)
        # Phase 5.5: append source-as-of footer (deterministic post-process,
        # no LLM call). Skip when the model refused or cited nothing — no
        # sources to declare.
        if sources_dates and not self_refused:
            answer_text = answer_text.rstrip() + "\n\n" + _render_sources_footer(sources_dates)
        return RAGAnswer(
            answer=answer_text,
            citations=verified,
            unverified_claims=[str(c) for c in result.get("unverified_claims", [])],
            rejected_citations=rejected,
            refused=self_refused,
            refusal_reason=(
                "empty-citations-implicit-refusal" if implicit_refused_empty_cites
                else "llm-self-refusal" if self_refused
                else None
            ),
            raw_retrieval=retrieved,
            flagged_vigencia=flagged,
            classified_type=classified,
            classified_top_k=effective_top_k,
            pii_types_redacted=pii_types,
            hierarchy_warning=hier_warn,
            prose_citation_mismatches=prose_mismatches,
            prose_check_retried=prose_retried,
            sources_consulted_at=sources_dates,
            cost_estimate_usd=round(cost_total, 6),
            tokens_used=tokens_total,
            llm_calls=llm_call_count,
            latency_ms=round((_time.monotonic() - _t0) * 1000.0, 3),
        )

    # ------------------------------------------------------------------

    def _collect_sources_consulted_at(
        self, cited_urns: list[str]
    ) -> dict[str, str]:
        """Build {doc_urn: ISO date} from the IndexChunk.fetched_at of the
        verified citations. Multiple cited URNs from the same doc collapse
        to one entry."""
        out: dict[str, str] = {}
        for urn in cited_urns:
            chunk = self.chunks_by_urn.get(urn)
            if chunk is None or not chunk.fetched_at:
                continue
            doc_urn = urn.split("~", 1)[0]
            out[doc_urn] = chunk.fetched_at
        return out

    def _compute_hierarchy_warning(
        self,
        verified_urns: list[str],
        retrieved: list[tuple[str, float]],
    ) -> str | None:
        """Emit a warning when the LLM's verified citations skip over
        higher-authority sources that were in top-K context.

        Specifically: if the BEST (lowest) rank among CITED URNs is
        strictly worse (higher number) than the BEST rank in the top-K
        context, the model passed over a higher-authority source.

        Returns None when:
          - No verified citations (refused, OOS, etc.)
          - Cited URNs already include the highest-rank source in top-K
          - No top-K retrieved chunks (shouldn't happen post-OOS gate)

        Rationale: Brazilian normative hierarchy is constitutional law.
        A peça or parecer that cites Decreto 8.771 while ignoring MCI
        art. 9 (the lei it regulates) is a serious legal error. This
        warning is a confidence signal; the caller / UI surfaces it.
        """
        if not verified_urns or not retrieved:
            return None

        # Best (lowest) rank among the model's citations
        cited_chunks = [self.chunks_by_urn.get(u) for u in verified_urns]
        cited_chunks = [c for c in cited_chunks if c is not None]
        if not cited_chunks:
            return None
        best_cited_rank = min(c.legal_rank for c in cited_chunks)

        # Best (lowest) rank in the top-K retrieved context
        retrieved_chunks = [self.chunks_by_urn.get(u) for u, _ in retrieved]
        retrieved_chunks = [c for c in retrieved_chunks if c is not None]
        if not retrieved_chunks:
            return None
        best_retrieved_rank = min(c.legal_rank for c in retrieved_chunks)

        if best_cited_rank <= best_retrieved_rank:
            # Model used the best available authority — no warning
            return None

        # Find which higher-authority sources were available but not cited.
        # Surface the first few URNs at the higher rank for the warning text.
        cited_set = set(verified_urns)
        higher_available = [
            c for c in retrieved_chunks
            if c.legal_rank == best_retrieved_rank and c.urn not in cited_set
        ]
        higher_urns_str = ", ".join(c.urn for c in higher_available[:3])

        return (
            f"⚠️ Atenção (hierarquia normativa): a resposta cita apenas "
            f"fontes de rank {best_cited_rank} ({rank_name(best_cited_rank)}); "
            f"o contexto continha fontes de rank superior — {rank_name(best_retrieved_rank)} "
            f"({higher_urns_str}). Verifique se a hierarquia foi respeitada "
            f"(CF > LC > LO > Decreto > Resolução)."
        )

    def _collect_flagged_vigencia(self, cited_urns: list[str]) -> list[FlaggedVigencia]:
        """For each verified citation, surface its overlay (if any).

        Deterministic — does not ask the LLM. Caller can cross-check
        against the answer prose to assert the model rendered a ⚠️
        warning for each entry here.
        """
        out: list[FlaggedVigencia] = []
        for urn in cited_urns:
            chunk = self.chunks_by_urn.get(urn)
            if chunk is None or chunk.vigencia is None:
                continue
            v: Vigencia = chunk.vigencia
            out.append(
                FlaggedVigencia(
                    urn=urn,
                    status=v.status,
                    fundamento=v.fundamento,
                    descricao_curta=v.descricao_curta,
                )
            )
        return out

    # ------------------------------------------------------------------

    def _retrieve(self, query: str, top_k: int | None = None) -> list[tuple[str, float]]:
        """Retrieve top_k chunks. `top_k=None` falls back to the pipeline
        default (set at construction). Callers pass an explicit `top_k`
        when the classifier has picked a type-specific value."""
        k = top_k if top_k is not None else self.top_k
        q_vec = self.embedder.embed_query(query)
        sims = self.doc_vecs @ q_vec
        top_idx = np.argsort(-sims)[:k]
        return [(self.urns[i], float(sims[i])) for i in top_idx]

    def _build_context(self, retrieved: list[tuple[str, float]]) -> str:
        parts: list[str] = []
        for urn, _score in retrieved:
            chunk = self.chunks_by_urn.get(urn)
            if chunk is None:
                # Defensive — shouldn't happen since urns came from the same index.
                continue
            citation = chunk.citation or "(sem rótulo)"
            nav = chunk.nav_text or ""
            header = f"[{citation}]" if not nav else f"[{citation}] — {nav}"
            # Vigência overlay rendered as XML attribute when present. The
            # SYSTEM_PROMPT instructs the model to emit a ⚠️ warning when
            # a cited <fonte> carries this attribute.
            vig_attr = ""
            if chunk.vigencia is not None:
                vig_attr = f' vigencia="{vigencia_warning(chunk.vigencia)}"'
            parts.append(
                f'<fonte urn="{urn}"{vig_attr}>\n{header}\n{chunk.text}\n</fonte>'
            )
        return "\n\n".join(parts)


# ----------------------------------------------------------------------------
# Factory: build a ready-to-query pipeline reusing the eval cache layout.
# ----------------------------------------------------------------------------


def load_pipeline(
    chunks_dir: Path,
    index_dir: Path,
    *,
    embedder_name: str = DEFAULT_EMBEDDER,
    text_mode: str = DEFAULT_TEXT_MODE,
    llm_provider: str = "anthropic",
    llm_model: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    oos_threshold: float = DEFAULT_OOS_THRESHOLD,
) -> RAGPipeline:
    """Build a RAGPipeline from existing chunks + cached index.

    Re-uses the same content-hash cache layout written by `run_eval.py`,
    so the index doesn't get rebuilt redundantly. If the cache is stale
    or absent we raise — building the index from inside a query path
    would be a slow surprise; the caller should run `run_eval.py` once
    to populate it.

    `llm_provider` selects the LLM provider; `llm_model` overrides the
    provider's default. Provider-aware via rag_leis.llm.get_llm().
    """
    from rag_leis.cache import cache_is_fresh, texts_hash

    embedder = get_embedder(embedder_name)
    chunks = load_chunks(chunks_dir)
    safe_name = embedder.name.replace("/", "_")
    cache_path = index_dir / f"{safe_name}__{text_mode}.npz"

    current_hash = texts_hash(format_texts(chunks, text_mode))
    if not cache_is_fresh(cache_path, current_hash):
        raise RuntimeError(
            f"Index cache missing or stale at {cache_path}. "
            f"Build it first:\n"
            f"  uv run python -m rag_leis.run_eval "
            f"--model {embedder_name} --text-mode {text_mode}"
        )

    loaded = np.load(cache_path, allow_pickle=True)
    urns: list[str] = list(loaded["urns"])
    doc_vecs = loaded["vecs"]
    chunks_by_urn = {c.urn: c for c in chunks}

    llm = get_llm(provider=llm_provider, model=llm_model)

    return RAGPipeline(
        embedder=embedder,
        urns=urns,
        doc_vecs=doc_vecs,
        chunks_by_urn=chunks_by_urn,
        llm=llm,
        top_k=top_k,
        oos_threshold=oos_threshold,
    )
