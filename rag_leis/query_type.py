"""Query-type classifier for adaptive top_k routing.

Reviewer round 2 (item 10) + BACKLOG Phase 2.6 deferred decision converge:
treat every query identically (top_k=10) wastes retrieval on citação-literal
queries (1 chunk needed) and starves enumeração (10-30 chunks needed,
top_k=10 caps recall at ~71% even with a perfect retriever; reflected in
the row 7 sanções non-determinism that plagued Phase 2-3).

This module's contract: regex-only classifier with explicit fallback
order. NO LLM call — we don't want a per-query taxation pre-LLM call,
and the regex is well-suited to PT-BR legal query patterns.

The five types match `eval/queries.yaml` and `eval/answer_queries.yaml`:

  - enumeracao        "quais são as X?", "liste", "enumere" → recall-heavy
  - citacao-literal   "o que diz o art. X?"                  → precision-heavy
  - definicao         "o que é Y?", "qual a definição"       → balanced
  - cross-doc         "diferença entre X e Y", "X e Y"       → multi-source
  - parafrase         (default — natural-language without legal vocab)

Out-of-scope detection is NOT done here — that's the LLM-self-refusal
guard at runtime (Phase 2.7). OOS queries get classified as one of the
five before the pipeline figures out the answer doesn't exist.
"""

from __future__ import annotations

import re

# Order matters: each regex is tried in this sequence; first match wins.
# Reasoning behind the order:
#   1. enumeracao — strongest signal ("quais", "liste"). Beats art-N
#      mention (e.g., "quais artigos da LGPD tratam de X" is enumeração
#      not citação-literal).
#   2. citacao-literal — explicit "art. N" mention. Beats definição
#      ("o que diz o art. 9" is literal, not definitional).
#   3. cross-doc — multi-source linking words. Beats definição/paráfrase
#      because explicit cross-doc framing is a stronger signal.
#   4. definicao — "o que é", "qual a definição", "como X é definido".
#   5. parafrase — fallback. Any query that doesn't trigger the above
#      is treated as a natural-language paraphrase.

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "enumeracao",
        re.compile(
            r"\b(quais|liste|enumere|cite|cita|listar)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "citacao-literal",
        re.compile(
            # "art. 9", "artigo 9", "art 9-A", "art. 5 inciso X" — anchored on
            # the "art" token to avoid false-positives on e.g. "particular".
            r"\bart(?:igo)?\.?\s*\d+(?:-[A-Z])?",
            re.IGNORECASE,
        ),
    ),
    (
        "cross-doc",
        re.compile(
            # "diferença entre X e Y", "comparação entre", "relação entre",
            # "X e Y na" (when X and Y are distinct law names).
            r"\b(diferen[çc]a|compara[çc][ãa]o|rela[çc][ãa]o)\s+entre\b",
            re.IGNORECASE,
        ),
    ),
    (
        "definicao",
        re.compile(
            r"\b(o que (?:é|são)|qual a defini[çc][ãa]o|como (?:é|s[ãa]o) definid[oa]s?|defina|definir)\b",
            re.IGNORECASE,
        ),
    ),
]


# Per-type top_k targets. Reasoning per type:
#   enumeracao: gold sets in answer_queries reach 14 URNs (MCI art.7) and
#     enumeração queries in eval/queries.yaml go up to 26 (Lei 14.129
#     art.3 princípios). top_k=25 captures all but the largest, with
#     diminishing returns above that.
#   citacao-literal: usually 1 article + its §§. Top_k=8 fits an article
#     family without spilling into siblings of other articles.
#   definicao: usually 1 inciso/caput + 2-5 contextual siblings. 12.
#   cross-doc: gold spans 2-7 chunks across laws. 15 gives headroom.
#   parafrase: balanced default. 12 (slight bump from old 10 — paráfrase
#     queries tend to need procedural §§ siblings).
TOP_K_PER_TYPE: dict[str, int] = {
    "enumeracao": 25,
    "citacao-literal": 8,
    "definicao": 12,
    "cross-doc": 15,
    "parafrase": 12,
}


# Per-type guidance appended to the SYSTEM_PROMPT. Kept short — the
# generator already has the full contract in the base prompt; these
# snippets nudge behavior for the specific query shape.
TYPE_PROMPT_SNIPPETS: dict[str, str] = {
    "enumeracao": (
        "TIPO DA QUERY: enumeração. Prefira listas explícitas cobrindo "
        "TODOS os itens presentes no contexto (incisos, alíneas). Se o "
        "contexto fornecer pelo menos um item da lista, NÃO recuse — "
        "responda com o subconjunto disponível e indique 'lista parcial' "
        "em unverified_claims se aplicável."
    ),
    "citacao-literal": (
        "TIPO DA QUERY: citação literal a artigo específico. Foque a "
        "resposta no dispositivo citado + seus filhos (parágrafos, "
        "incisos). Evite expandir para artigos vizinhos."
    ),
    "definicao": (
        "TIPO DA QUERY: definição. Comece pela definição literal do "
        "conceito; em seguida cite siblings com contexto operacional "
        "(parágrafos com exceções, regulamentação correlata)."
    ),
    "cross-doc": (
        "TIPO DA QUERY: cross-doc (resposta vive em ≥2 leis). Conecte "
        "os dispositivos explicitamente — não apenas liste; explique "
        "como uma lei se relaciona com a outra (regulamenta, integra, "
        "contradiz, complementa)."
    ),
    "parafrase": "",  # default behavior; no extra snippet
}


def classify_query(query: str) -> str:
    """Return one of: enumeracao | citacao-literal | cross-doc | definicao | parafrase.

    Pure-regex, no LLM, no normalization beyond Python's `re.IGNORECASE`.
    First pattern in `_PATTERNS` order to match wins; falls back to
    'parafrase'. The order is documented in the module docstring and is
    part of the contract — changing it shifts which type a borderline
    query lands in.
    """
    for type_name, pattern in _PATTERNS:
        if pattern.search(query):
            return type_name
    return "parafrase"


def top_k_for_query(query: str, default: int = 12) -> int:
    """Convenience: classify + look up top_k. `default` for unknown types
    (defensive — shouldn't happen since classify always returns a known
    type or 'parafrase', but the lookup is defensive)."""
    return TOP_K_PER_TYPE.get(classify_query(query), default)


def prompt_snippet_for_query(query: str) -> str:
    """Convenience: classify + look up prompt snippet. Empty string for
    parafrase (no extra guidance)."""
    return TYPE_PROMPT_SNIPPETS.get(classify_query(query), "")
