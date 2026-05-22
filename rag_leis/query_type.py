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

# Multi-turn classifier contract (Phase 17.2)
# ============================================
#
# Phase 10d will add multi-turn RAG (queries see prior turns as
# context). The classifier above is stateless and single-query by
# construction — `classify_query(query: str) -> str`. Multi-turn breaks
# that. Two design alternatives were considered:
#
#   (A) rewrite-then-classify        ← CHOSEN
#       Rewrite the latest user turn into a STANDALONE query that
#       inlines any referenced entities + implicit subject from prior
#       turns, then classify the rewritten standalone form using the
#       existing regex. Pipeline downstream (retrieval + generation)
#       also operates on the rewritten standalone form.
#
#   (B) context-into-classifier
#       Pass `(prior_turns, current_query)` directly to a classifier
#       that's aware of conversation shape. Either teach the regex
#       set new patterns ("follow-up question" as a sixth type) or
#       replace the regex with an LLM classifier that sees context.
#
# Decision: (A) rewrite-then-classify.
#
# Rationale:
#
#   * Stability of the existing contract.
#     The regex classifier above is load-bearing for top_k routing +
#     SYSTEM_PROMPT snippet selection. Every eval row, every test, and
#     the entire retrieval-tuning history (Phase 2.6, 4.1, 7.5.x)
#     assumes the 5-type taxonomy on a SINGLE query string. Option (B)
#     would either (i) require adding a 6th type "follow-up", which
#     leaks conversation-state into top_k/prompt-snippet tables that
#     are tuned per-query-shape, or (ii) replace regex with an LLM
#     classifier, which trades determinism + zero-cost for ~$0.0002 +
#     ~150ms per query. Either path moves the established contract.
#     (A) keeps `classify_query(str) -> str` exactly as-is.
#
#   * Interpretability.
#     A rewritten standalone query is a debuggable artifact — when
#     retrieval goes wrong on turn 2 of a thread, the operator can
#     read the rewrite and tell whether the upstream rewriter
#     hallucinated entities, narrowed to the wrong subject, or
#     correctly identified an OOS topic shift. With (B) the same
#     failure mode lives inside an LLM call that can't be inspected
#     without re-running it.
#
#   * RAG retrieval design.
#     RAG retrieval (cosine over voyage-3-large embeddings) is known to
#     degrade badly on conversational queries that lean on
#     antecedents — "e quanto a isso?" embeds nowhere near the
#     domain. Rewriting to a standalone form ("e quanto à LGPD art.
#     7?") restores the embedding signal. This is the pattern used by
#     LlamaIndex's CondenseQuestionChatEngine + the LangChain
#     condense_question_prompt + every production multi-turn RAG
#     stack the field has settled on.
#
#   * Topic-shift safety.
#     The rewriter MUST detect topic-shift turns ("mudando de
#     assunto, ...") and produce a standalone form that drops prior
#     context — never inline the prior topic as if it were still
#     relevant. Phase 10d's prompt MUST require this; the
#     `eval/conversation_queries.yaml` row 4 tests it explicitly.
#
#   * Trade-off cost.
#     One extra LLM call per non-first turn: ~$0.0002 (~200 tokens
#     input + ~50 tokens output on Maritaca/Haiku) + ~200ms latency.
#     The first turn pays nothing — no prior context to rewrite
#     against. For the legal-research use case the rewrite cost is
#     dominated by the answer LLM call (~$0.001-0.01); the additional
#     ~10% is acceptable.
#
# Public contract:
#
#   * `classify_query(query: str) -> str` is UNCHANGED. Multi-turn
#     callers MUST rewrite first, then pass the rewritten standalone
#     query to this function. (The function does not need to know it
#     was called on a rewrite — that's the point.)
#
#   * `rewrite_for_classification(prior_turns, current_query)` is the
#     Phase 10d entry point that lives below as a documented stub.
#     Implementation is deferred to 10d; the eval set in
#     `eval/conversation_queries.yaml` is the contract its
#     implementation must satisfy.
#
# What good looks like (measured against `eval/conversation_queries.yaml`):
#
#   * Standalone rewrite preserves the original `question_type` of
#     turn 2's intent (e.g., a follow-up citação-literal stays
#     citação-literal after rewrite).
#   * Standalone rewrite contains every gold URN entity referenced via
#     pronoun or ellipsis ("isso", "ele", "que você mencionou").
#   * Topic-shift turns produce rewrites that don't carry prior topic.
#   * OOS follow-ups ("e jurisprudência do STF sobre isso?") produce
#     rewrites that still classify + retrieve as OOS — the rewriter
#     doesn't paper over scope violations by inlining LGPD entities.
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


# ---------------------------------------------------------------------------
# Phase 17.2 — multi-turn contract stub
# ---------------------------------------------------------------------------
#
# Implementation deferred to Phase 10d. The stub exists so:
#   * The contract is grep-able from the codebase (not just the
#     module docstring).
#   * Phase 10d has a concrete signature to fill in — no
#     bikeshedding about parameter shape at implementation time.
#   * Type-checkers + IDEs surface the intended call site.
#
# Eval contract: `eval/conversation_queries.yaml` (10 rows). Any
# implementation that satisfies the 10 rows is acceptable; provider /
# prompt / temperature are unspecified here on purpose.


def rewrite_for_classification(
    prior_turns: list[tuple[str, str]],
    current_query: str,
) -> str:
    """Rewrite `current_query` to a standalone form using `prior_turns`
    as conversational context. Returns the rewritten standalone query
    that should then be passed to `classify_query` + the retrieval +
    generation stages of the pipeline.

    Args:
        prior_turns: chronological list of (role, content) tuples for
            the conversation so far. Role is "user" or "assistant".
            Excludes the current turn. May be empty (rewriter MUST
            return current_query unchanged in that case).
        current_query: the latest user turn, possibly conversational
            (containing pronouns, ellipsis, "and what about…" patterns).

    Returns:
        A standalone query string suitable for passing to
        `classify_query`, the retriever, and the generator as if it
        were a fresh single-turn query.

    Constraints (enforced by `eval/conversation_queries.yaml`):
        * If `prior_turns` is empty, MUST return current_query verbatim.
        * Pronouns + ellipsis ("isso", "ele", "que você mencionou")
          MUST be resolved against prior_turns when possible.
        * Topic-shift markers ("mudando de assunto", "outra pergunta")
          MUST drop prior context — the rewrite is then ~= the current
          query.
        * OOS follow-ups MUST NOT be "rescued" by inlining prior
          on-corpus entities (e.g., "e jurisprudência do STF sobre isso"
          stays OOS-shaped after rewrite — the rewriter does not
          launder scope violations).
        * The rewrite SHOULD preserve the question_type of the
          underlying intent (a follow-up citação-literal stays
          citação-literal after rewrite).

    Raises:
        NotImplementedError until Phase 10d ships an implementation.
    """
    if not prior_turns:
        # Phase 17.2 stub returns current_query for the empty-context
        # case — this branch is exercised by the eval as a sanity
        # check. The recursive Phase 10d implementation should also
        # short-circuit here.
        return current_query
    raise NotImplementedError(
        "rewrite_for_classification is a Phase 17.2 contract stub; "
        "implementation deferred to Phase 10d. See module docstring + "
        "eval/conversation_queries.yaml for the contract."
    )
