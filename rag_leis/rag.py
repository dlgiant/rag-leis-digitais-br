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
from rag_leis.llm import AnthropicLLM
from rag_leis.verify import verify_citations

DEFAULT_TOP_K = 10
DEFAULT_OOS_THRESHOLD = 0.50  # placeholder; Phase 2.7 calibrates
DEFAULT_TEXT_MODE = "label+nav+caput+text"
DEFAULT_EMBEDDER = "voyage-3-large"


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
"""


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------


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


# ----------------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------------


@dataclass
class RAGPipeline:
    embedder: Embedder
    urns: list[str]
    doc_vecs: Vec
    chunks_by_urn: dict[str, IndexChunk]
    llm: AnthropicLLM
    top_k: int = DEFAULT_TOP_K
    oos_threshold: float = DEFAULT_OOS_THRESHOLD
    corpus_urns: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        self.corpus_urns = frozenset(self.urns)

    # ------------------------------------------------------------------

    def answer(self, query: str) -> RAGAnswer:
        retrieved = self._retrieve(query)
        top1_score = retrieved[0][1] if retrieved else 0.0

        if top1_score < self.oos_threshold:
            return RAGAnswer(
                answer="Fora do escopo da base.",
                citations=[],
                unverified_claims=[],
                rejected_citations=[],
                refused=True,
                refusal_reason=(
                    f"top-1 score {top1_score:.3f} < limiar OOS {self.oos_threshold:.3f}"
                ),
                raw_retrieval=retrieved,
            )

        context = self._build_context(retrieved)
        user_msg = f"Pergunta: {query}\n\nFontes:\n{context}"
        result = self.llm.complete_structured(SYSTEM_PROMPT, user_msg, ANSWER_TOOL)

        cited = [str(u) for u in result.get("citations", [])]
        retrieved_urns = frozenset(u for u, _ in retrieved)
        verified, rejected = verify_citations(cited, retrieved_urns, self.corpus_urns)

        return RAGAnswer(
            answer=str(result.get("answer", "")),
            citations=verified,
            unverified_claims=[str(c) for c in result.get("unverified_claims", [])],
            rejected_citations=rejected,
            refused=False,
            refusal_reason=None,
            raw_retrieval=retrieved,
        )

    # ------------------------------------------------------------------

    def _retrieve(self, query: str) -> list[tuple[str, float]]:
        q_vec = self.embedder.embed_query(query)
        sims = self.doc_vecs @ q_vec
        top_idx = np.argsort(-sims)[: self.top_k]
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
            parts.append(
                f'<fonte urn="{urn}">\n{header}\n{chunk.text}\n</fonte>'
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

    llm = AnthropicLLM(model=llm_model) if llm_model else AnthropicLLM()

    return RAGPipeline(
        embedder=embedder,
        urns=urns,
        doc_vecs=doc_vecs,
        chunks_by_urn=chunks_by_urn,
        llm=llm,
        top_k=top_k,
        oos_threshold=oos_threshold,
    )
