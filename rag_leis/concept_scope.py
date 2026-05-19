"""Phase 7.6.2 — concept-scope gate: pre-LLM refusal mechanism.

Attacks the Phase 7.5 headline gap: 12.2% OOS refusal accuracy on the
external legalbench.br benchmark (vs 93.8% on internal eval — selection
bias of 6.7×). The mechanism is structural, not prompt-based:

  1. Each indexed Document declares 5-10 concept tags (corpus.py:Document.document_scope).
  2. Incoming query → LLM extractor maps it onto the same fixed vocabulary.
  3. If the query touches concepts AND no retrieved chunk's document
     declares any of those concepts → refuse before paying for the main
     LLM call. The refusal_reason names the offending concepts so audit
     logs explain WHY.

Defensive defaults are important:

- If the extractor returns NO concepts → **do not refuse** (let the
  existing cosine + LLM-self-refusal stack handle it; we don't want to
  reject queries just because the extractor lacks vocabulary coverage).
- Hallucinated concepts (not in the fixed vocabulary) are silently
  dropped — the structured-output tool can't constrain enum values
  cross-provider, so client-side filter is the guardrail.

Cost: ~$0.0005-0.001 per query (Sabiá-3.1 with a short prompt + tool
output). Latency: ~1-2s added p50.

Fail-fast gate (Phase 7.6.2): oos_a_refusal_rate on
`eval/legalbench_br_oos.yaml` must move from 0.122 to ≥0.22 (≥+0.10pp)
to justify the bigger BACKLOG #1 (full concept KG). Below that, the
mechanism doesn't have signal in this corpus and we park the bigger
idea.

Uso:
    from rag_leis.concept_scope import extract_concept_tags
    tags = extract_concept_tags(query, llm)
"""

from __future__ import annotations

from typing import Any

from rag_leis.corpus import CORPUS_BY_URN
from rag_leis.llm import LLM


def _build_vocabulary() -> frozenset[str]:
    """Union of all document_scope tags across the corpus registry.

    Raised at module import (not lazily) so a typo in a corpus.py tag is
    a visible failure on test run, not a silent gap at query time.
    """
    vocab = set()
    for doc in CORPUS_BY_URN.values():
        vocab.update(doc.document_scope)
    if not vocab:
        raise RuntimeError(
            "CONCEPT_VOCABULARY is empty — no Document in corpus.py has "
            "document_scope tags. Phase 7.6.2 mechanism requires per-doc "
            "tags to function."
        )
    return frozenset(vocab)


CONCEPT_VOCABULARY: frozenset[str] = _build_vocabulary()


CONCEPT_EXTRACTION_TOOL: dict[str, Any] = {
    "name": "extrair_conceitos_consulta",
    "description": (
        "Identifique TODOS os conceitos do vocabulário fixo que a consulta "
        "menciona ou pressupõe. Retorne lista vazia se nenhum conceito do "
        "vocabulário se aplicar (NÃO invente conceitos fora do vocabulário)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "concepts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Lista de conceitos do vocabulário que se aplicam à "
                    "consulta. Cada item DEVE ser uma string exata do "
                    "vocabulário fornecido — não use sinônimos ou variações."
                ),
            },
        },
        "required": ["concepts"],
    },
}


def _system_prompt(vocabulary: frozenset[str]) -> str:
    """Build the extractor system prompt with the current vocabulary inlined.

    Inlining is cheap: the vocabulary is <100 short strings (~500 input
    tokens at Sabiá rates = $0.00025/call). The alternative (RAG-on-RAG
    to retrieve a relevant subset) adds infrastructure for marginal save.
    """
    sorted_vocab = sorted(vocabulary)
    return f"""\
Você é um extrator de conceitos para um sistema jurídico-RAG brasileiro.

Tarefa: dada uma consulta em português, identifique quais conceitos do \
VOCABULÁRIO FIXO abaixo a consulta menciona, pressupõe, ou pergunta sobre. \
Inclua tanto conceitos explícitos quanto os razoavelmente inferíveis do \
contexto jurídico.

VOCABULÁRIO ({len(vocabulary)} conceitos):
{", ".join(sorted_vocab)}

REGRAS:
- Retorne SOMENTE conceitos exatos do vocabulário (case-sensitive, com hífens).
- Não invente conceitos. Se a consulta menciona algo fora do vocabulário, \
ignore esse aspecto.
- Se NENHUM conceito do vocabulário se aplica à consulta, retorne lista \
VAZIA. Isso é informativo (sinaliza que a consulta está fora do escopo \
indexado).
- Múltiplos conceitos relacionados são esperados — uma query sobre "vazamento \
de dados pela LGPD" tipicamente menciona vazamento-dados, dados-pessoais, \
ANPD, incidente, possivelmente DPO.

Use a ferramenta `extrair_conceitos_consulta`.
"""


EXTRACTION_SYSTEM_PROMPT: str = _system_prompt(CONCEPT_VOCABULARY)


def extract_concept_tags(query: str, llm: LLM) -> list[str]:
    """Map a natural-language query onto the fixed CONCEPT_VOCABULARY.

    Returns the list of vocabulary concepts the query touches, in the
    order the extractor produced. Hallucinated concepts (not in the
    vocabulary) are dropped silently — the function NEVER returns a
    string that isn't a vocabulary member.

    Empty list is a valid return — it means the query touches no
    indexed concept. Caller must NOT treat empty-list as a refusal
    signal on its own (see module docstring "Defensive defaults").

    One LLM call. Cost ~$0.0005-0.001 per call at Sabiá-3.1 rates.
    """
    if not query.strip():
        return []
    result = llm.complete_structured(
        EXTRACTION_SYSTEM_PROMPT,
        f"<consulta>\n{query.strip()}\n</consulta>",
        CONCEPT_EXTRACTION_TOOL,
        max_tokens=512,
    )
    raw = result.get("concepts", []) or []
    # Defensive vocabulary filter — drop anything outside the fixed set.
    # The structured-output schema doesn't constrain enum values across
    # all providers, so client-side validation is the guardrail.
    return [c for c in raw if isinstance(c, str) and c in CONCEPT_VOCABULARY]


def check_scope_overlap(
    query_concepts: list[str], retrieved_doc_urns: list[str]
) -> tuple[bool, set[str]]:
    """Decide whether the scope-check gate should refuse.

    Args:
      query_concepts: output of extract_concept_tags (already vocab-filtered)
      retrieved_doc_urns: doc URNs (not chunk URNs) of the top-K retrieval

    Returns:
      (should_refuse, retrieval_concepts) where:
        - should_refuse=True only when query_concepts is non-empty AND
          there's zero intersection with the union of retrieval doc scopes
        - retrieval_concepts is the union set of doc_scope tags across
          retrieval (for audit logging in the refusal_reason)

    Defensive defaults:
      - query_concepts empty → never refuse (extractor lacks coverage)
      - retrieved_doc_urns empty → never refuse (no retrieval to compare)
      - any doc URN not in registry is silently skipped
    """
    if not query_concepts:
        return False, set()
    retrieval_concepts: set[str] = set()
    for doc_urn in retrieved_doc_urns:
        doc = CORPUS_BY_URN.get(doc_urn)
        if doc:
            retrieval_concepts.update(doc.document_scope)
    if not retrieval_concepts:
        # No retrieval (or retrieval doesn't resolve to any tagged doc):
        # not enough information to refuse; defer to downstream gates.
        return False, retrieval_concepts
    overlap = set(query_concepts) & retrieval_concepts
    return (len(overlap) == 0), retrieval_concepts
