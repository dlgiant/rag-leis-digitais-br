"""Phase 7.8 — per-citation relevance gate.

Attacks Pattern B from `phase-7.5.3-legalbench-oos-findings.md`:
the model cites real URNs from the corpus that PASSED cite-and-verify
(URN ∈ corpus ∧ URN ∈ top-K) but are semantically wrong for the query.
Example: query about CPC petição inicial requirements → model cites
Lei 9.507/97 Habeas Data art.8 because that's a procedural law that
happens to be in the corpus. Verification passes; the answer is wrong.

Phase 7.7's empty-citations fix catches the variant where the model
gives no citations. This module catches the case where the model gives
citations that look real but are off-topic.

Mechanism:
  1. After cite-and-verify produces `verified` URNs, look up each
     chunk's text.
  2. One batched LLM call: for each (urn, chunk_text, query),
     ask "is this citation directly relevant to THIS specific query,
     or only relevant to the broader topic?"
  3. If ZERO citations are judged relevant → treat as implicit refusal.

Cost: one extra LLM call per row that has citations.
Conservative defaults:
  - Skip if `verified` is empty (no citations to judge).
  - Judge errors → defer to downstream gates (don't refuse on judge failure).
  - Reject answer only when ALL citations are irrelevant — if any one
    is relevant, the answer stands (avoids false-refusals on partially
    relevant answers).

Uses the same LLM as the pipeline generator (no separate judge instance
required for v0). Future enhancement: route to a different model if
Sabiá-judging-Sabiá shows lenient bias.
"""

from __future__ import annotations

from typing import Any

from rag_leis.eval_harness import IndexChunk
from rag_leis.llm import LLM


CITATION_RELEVANCE_TOOL: dict[str, Any] = {
    "name": "avaliar_relevancia_citacoes",
    "description": (
        "Para cada citação fornecida, decida se o dispositivo citado responde "
        "DIRETAMENTE à pergunta específica do usuário. Relevante = um advogado "
        "responderia a pergunta citando este artigo. Não-relevante = o artigo "
        "trata de tópico relacionado mas não responde a pergunta-alvo."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "evaluations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "urn": {
                            "type": "string",
                            "description": "URN canônico exato (copiar do input)",
                        },
                        "relevant": {
                            "type": "boolean",
                            "description": (
                                "true = artigo responde diretamente à pergunta; "
                                "false = artigo trata de tópico tangencial"
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "1 frase justificando a decisão.",
                        },
                    },
                    "required": ["urn", "relevant", "reason"],
                },
            },
        },
        "required": ["evaluations"],
    },
}


RELEVANCE_JUDGE_SYSTEM = """\
Você avalia se citações jurídicas respondem DIRETAMENTE a uma pergunta \
específica, ou se apenas tocam um tópico tangencialmente relacionado.

Critério ESTRITO: para cada citação, marque relevant=true APENAS se um \
advogado experiente CITARIA este dispositivo como fundamentação da \
resposta à pergunta-alvo. Marque relevant=false quando:

- O dispositivo é de uma LEI DIFERENTE da que a pergunta nomeia \
explicitamente (ex: pergunta sobre "CPC" + citação de Lei 9.507/97 \
Habeas Data → false; o art.8 da Lei 9.507 trata de procedimento de \
habeas data, NÃO de requisitos de petição inicial CPC).
- O dispositivo trata do mesmo TÓPICO mas não responde a pergunta \
ESPECÍFICA (ex: pergunta sobre "prazo prescricional de IRPJ" + \
citação de Lei genérica sobre direitos do contribuinte → false).
- O dispositivo é remotamente conexo via cadeia de analogia (ex: \
"art. X da Lei A pode informar a aplicação da Lei B" → false; isto \
é construção doutrinária, não fundamentação positivada).

Marque relevant=true SOMENTE quando o dispositivo citado é precisamente \
o que um advogado mencionaria primeiro respondendo à pergunta.

Se TODAS as citações fornecidas forem irrelevantes, o sistema vai \
recusar a resposta (sinal pra você ser estrito: prefira marcar como \
não-relevante em casos limítrofes; falso-positivo de relevância vaza \
respostas erradas em produção, falso-negativo apenas força recusa).

Use a ferramenta `avaliar_relevancia_citacoes`.
"""


def _format_citations_for_judge(
    citations: list[str], chunks_by_urn: dict[str, IndexChunk]
) -> str:
    """Render the (urn, chunk_text) pairs as XML-style tags for the judge prompt.

    Truncates each chunk to ~400 chars to bound prompt size. The judge
    only needs enough text to assess relevance, not the full article.
    """
    parts: list[str] = []
    for urn in citations:
        chunk = chunks_by_urn.get(urn)
        if chunk is None:
            # URN passed verify but not in chunks_by_urn — defensive,
            # shouldn't happen in practice but don't crash.
            parts.append(f'<citation urn="{urn}"><text>[chunk not found]</text></citation>')
            continue
        text = chunk.text or ""
        snippet = text[:400] + ("…" if len(text) > 400 else "")
        parts.append(f'<citation urn="{urn}"><text>{snippet}</text></citation>')
    return "\n".join(parts)


def judge_citation_relevance(
    judge: LLM,
    query: str,
    citations: list[str],
    chunks_by_urn: dict[str, IndexChunk],
) -> dict[str, bool]:
    """For each cited URN, decide relevance via one batched LLM call.

    Returns: {urn: relevant_bool}. Defensive defaults:
      - Empty citations → empty dict (no LLM call)
      - LLM error → empty dict (caller treats as "no evaluations available")
      - URN in response but not in input → ignored
      - Input URN missing from response → treated as relevant=True (defer
        to downstream gates rather than over-refuse)

    The caller decides what to do with the result; the typical pattern
    is: refuse if `not any(result.values())`.
    """
    if not citations:
        return {}

    # Defensive cap: at very long citation lists (10+), prompt and output
    # both balloon and risk hitting max_tokens. Sabiá-3.1 errored on a
    # row with ~12 citations during Phase 7.8 validation. Take the first
    # 10 — they're already ranked by retrieval order, so the most likely
    # relevant ones are at the front.
    capped = citations[:10]

    user_msg = (
        f"<pergunta>\n{query.strip()}\n</pergunta>\n\n"
        f"<citacoes>\n{_format_citations_for_judge(capped, chunks_by_urn)}\n</citacoes>"
    )
    try:
        result = judge.complete_structured(
            RELEVANCE_JUDGE_SYSTEM,
            user_msg,
            CITATION_RELEVANCE_TOOL,
            max_tokens=4096,
        )
    except Exception:
        # Judge failure (timeout, schema parse error, etc.) — defer to
        # downstream gates rather than blocking the pipeline. Logged
        # implicitly via the empty return.
        return {}

    evaluations = result.get("evaluations") or []
    decisions: dict[str, bool] = {}
    for e in evaluations:
        if not isinstance(e, dict):
            continue
        urn = e.get("urn")
        if not isinstance(urn, str) or urn not in citations:
            # Hallucinated URN (judge invented one not in input) — ignore
            continue
        decisions[urn] = bool(e.get("relevant", True))

    # For citations the judge OMITTED from its response, default to
    # relevant=True (don't over-refuse on judge incompleteness).
    for urn in citations:
        decisions.setdefault(urn, True)

    return decisions
