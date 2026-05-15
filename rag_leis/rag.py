"""End-to-end RAG pipeline with structured-output + cite-and-verify guards.

Wires together what the rest of the project produced separately:
  * retrieval (voyage dense, `label+nav+caput+text`, top-K)
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

from rag_leis.embeddings import Embedder, Vec, get_embedder
from rag_leis.eval_harness import IndexChunk, format_texts, load_chunks
from rag_leis.llm import LLM, get_llm
from rag_leis.pii import RedactedQuery, redact
from rag_leis.pii_audit import write_audit
from rag_leis.query_type import (
    TOP_K_PER_TYPE,
    classify_query,
    prompt_snippet_for_query,
)
from rag_leis.verify import verify_citations
from rag_leis.vigencia import Vigencia, vigencia_warning

DEFAULT_TOP_K = 10
DEFAULT_AUDIT_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "audit" / "pii-redactions.jsonl"
# Cosine threshold below which we refuse before paying for the LLM call.
# Phase 2.7 measured the OOS-vs-in-scope distribution: OOS top-1 sims
# (0.52-0.65) overlap the in-scope range (0.56-0.75), so no clean cosine
# threshold separates them. The cosine gate is now a *fast-path* for very
# clearly OOS queries (e.g. someone pasting a paragraph in a different
# language); the load-bearing OOS detection happens at the LLM-self-refusal
# level, since the model has full context to make that call.
DEFAULT_OOS_THRESHOLD = 0.40
DEFAULT_TEXT_MODE = "label+nav+caput+text"
DEFAULT_EMBEDDER = "voyage-3-large"

# Prefix patterns that mean "the LLM examined the context and decided it
# can't answer". Anchored to the start of `answer` because the system
# prompt instructs the model to LEAD with this literal sentence on
# refusals — anchoring avoids matching inline "não há informação" mentions
# that appear within real answers.
_SELF_REFUSAL_PREFIXES = (
    "não há informação suficiente",
    "não há informações suficientes",
    "não foi possível encontrar",
    "as fontes fornecidas não",
    "fora do escopo",
)


def _is_self_refusal(answer_text: str) -> bool:
    if not answer_text:
        return False
    head = answer_text.strip().lower()[:120]
    return any(head.startswith(p) for p in _SELF_REFUSAL_PREFIXES)


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

3. Se a pergunta não puder ser respondida com as fontes fornecidas, retorne \
o texto literal "Não há informação suficiente nas fontes fornecidas." em \
`answer`, deixe `citations` vazia e explique brevemente em `unverified_claims` \
o que faltou.

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
    corpus_urns: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        self.corpus_urns = frozenset(self.urns)

    # ------------------------------------------------------------------

    def answer(self, query: str) -> RAGAnswer:
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
            )

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

        answer_text = str(result.get("answer", ""))
        cited = [str(u) for u in result.get("citations", [])]
        retrieved_urns = frozenset(u for u, _ in retrieved)
        verified, rejected = verify_citations(cited, retrieved_urns, self.corpus_urns)

        # LLM-self-refusal: model read the context and emitted the canonical
        # "informação insuficiente" prefix. This is the strongest OOS signal
        # we have — it's the model's judgment with full context, not a
        # surface-similarity threshold. Mark refused; preserve the answer
        # text and any citations the model managed to attach (could still
        # be useful for "I can't answer but here's what I found"-style UIs).
        self_refused = _is_self_refusal(answer_text)

        flagged = self._collect_flagged_vigencia(verified)
        return RAGAnswer(
            answer=answer_text,
            citations=verified,
            unverified_claims=[str(c) for c in result.get("unverified_claims", [])],
            rejected_citations=rejected,
            refused=self_refused,
            refusal_reason="llm-self-refusal" if self_refused else None,
            raw_retrieval=retrieved,
            flagged_vigencia=flagged,
            classified_type=classified,
            classified_top_k=effective_top_k,
            pii_types_redacted=pii_types,
        )

    # ------------------------------------------------------------------

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
