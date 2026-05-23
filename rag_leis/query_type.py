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
from typing import Any

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


# Phase 10d (2026-05-23) — Conversational query rewriter
# ============================================================================
#
# Implementation of the Phase 17.2 contract. Uses an LLM (Maritaca by
# default — sabia-4 is the production generator, and the rewriter prompt
# is PT-BR so a PT-BR-tuned model is natural) to produce the standalone
# form of a conversational follow-up.
#
# Cost: ~$0.0003 per rewrite (short system + short user + short output).
# Latency: ~200-400ms wall-clock. The first turn of any conversation
# never pays — `prior_turns` is empty, rewriter short-circuits.
#
# Failure mode: if the LLM call fails for any reason (network, rate
# limit, malformed response), the rewriter returns `current_query`
# unchanged. The pipeline then proceeds as if the turn were single-turn.
# Degrades gracefully — better to under-rewrite than to crash on a
# transient provider hiccup.


_REWRITER_SYSTEM_PROMPT = """\
Você é um reescritor de consultas conversacionais para um sistema RAG \
de legislação digital brasileira.

Sua tarefa: receber o histórico de uma conversa (turnos anteriores) + a \
pergunta atual do usuário, e produzir uma versão AUTOSSUFICIENTE da \
pergunta atual. A versão reescrita será usada como query única para \
classificação + retrieval + geração — sem acesso ao histórico.

Regras inegociáveis:

1. Se a pergunta atual JÁ É autossuficiente (não tem pronomes/elipse \
referindo aos turnos anteriores), retorne ela praticamente inalterada.

2. Pronomes e elipse ("isso", "ele", "que você mencionou", "e para X?") \
DEVEM ser resolvidos com o que está nos turnos anteriores. Substitua \
explicitamente.

3. Marcadores de mudança de assunto ("mudando de assunto", "outra \
pergunta", "agora sobre") DEVEM levar você a IGNORAR o histórico — a \
reescrita fica equivalente à pergunta atual sem o marcador.

4. Perguntas que pedem fontes FORA DO ESCOPO do corpus (jurisprudência \
do STF, doutrina, lei estadual, etc.) DEVEM manter essa característica. \
NÃO "resgate" perguntas fora do escopo inlinando entidades do corpus do \
histórico. Exemplo: "e jurisprudência do STF sobre isso?" → \
"jurisprudência do STF sobre [tópico do histórico]" — NÃO transforme em \
"o que diz a LGPD sobre [tópico]".

5. Use vocabulário compatível com o classificador interno:
   - Para perguntas de definição: "o que é X" ou "qual a definição de X"
   - Para citação literal: mantenha "art. N", "artigo N" se a pergunta \
referência um dispositivo
   - Para enumeração: "quais são X", "liste X"
   - Para cross-doc: "comparação entre X e Y", "diferença entre X e Y"

6. **PRESERVE A ESTRUTURA DA PERGUNTA DO USUÁRIO**. Não introduza \
"quais" ou "liste" se a pergunta original não usou essas palavras. \
Se o usuário pediu "pode dar mais detalhes?" sobre um conceito, \
reescreva como "qual a definição mais detalhada de X" — NÃO como \
"quais são os detalhes de X" (que muda o tipo de pergunta de \
definição para enumeração). Se o usuário pediu "o que NÃO é X?", \
preserve essa estrutura — NÃO transforme em "quais são as situações \
que NÃO são X". A regra geral: reescreva o MENOS necessário para \
tornar a pergunta autossuficiente; preserve a forma original.

7. Saída: APENAS a query reescrita. Sem prefixo ("Aqui está:"), sem \
sufixo, sem aspas, sem markdown. Apenas o texto da pergunta.\
"""


def _build_rewriter_user_message(
    prior_turns: list[tuple[str, str]], current_query: str,
) -> str:
    """Format the prior turns + current query as the user message.

    Uses an explicit `[USUÁRIO]` / `[ASSISTENTE]` prefix per turn so the
    LLM doesn't confuse turn boundaries. Caps assistant turn length at
    400 chars to keep the prompt under control (an LLM doesn't need the
    full answer text to resolve a pronoun — the topic + key entities are
    enough)."""
    lines: list[str] = ["HISTÓRICO DA CONVERSA:"]
    for role, content in prior_turns:
        role_label = "USUÁRIO" if role == "user" else "ASSISTENTE"
        # Truncate assistant turns; they're often long answer text and
        # the rewriter only needs topic + key entity references.
        truncated = content if len(content) <= 400 else content[:400] + "…"
        lines.append(f"[{role_label}] {truncated}")
    lines.append("")
    lines.append(f"PERGUNTA ATUAL: {current_query}")
    lines.append("")
    lines.append(
        "Reescreva a PERGUNTA ATUAL como uma query autossuficiente, "
        "seguindo as regras do system prompt."
    )
    return "\n".join(lines)


def rewrite_for_classification(
    prior_turns: list[tuple[str, str]],
    current_query: str,
    llm: Any | None = None,
) -> str:
    """Rewrite `current_query` to a standalone form using `prior_turns`
    as conversational context. Returns the rewritten standalone query
    that should then be passed to `classify_query` + the retrieval +
    generation stages of the pipeline.

    Args:
        prior_turns: chronological list of (role, content) tuples for
            the conversation so far. Role is "user" or "assistant".
            Excludes the current turn. Empty → returns current_query
            verbatim (no LLM call).
        current_query: the latest user turn, possibly conversational
            (containing pronouns, ellipsis, "and what about…" patterns).
        llm: optional LLM instance (anything that exposes `complete()`).
            Defaults to constructing a fresh `get_llm("maritaca")`.
            Tests inject a mock here to avoid the network call.

    Returns:
        A standalone query string suitable for passing to
        `classify_query`, the retriever, and the generator as if it
        were a fresh single-turn query.

    Contract (enforced by `eval/conversation_queries.yaml`):
        * If `prior_turns` is empty, returns `current_query` verbatim
          (no LLM call).
        * Pronouns + ellipsis are resolved against `prior_turns`.
        * Topic-shift markers ("mudando de assunto") cause prior
          context to be DROPPED.
        * OOS follow-ups stay OOS-shaped after rewrite.
        * The rewrite preserves the question_type of the underlying
          intent (a follow-up citação-literal stays citação-literal).

    Failure mode: if the LLM call raises, returns `current_query`
    unchanged. The pipeline then proceeds as if the turn were
    single-turn — degraded but never broken.
    """
    if not prior_turns:
        return current_query

    if llm is None:
        # Lazy import — keeps query_type.py importable without the LLM
        # module's deps in eval-only paths.
        from rag_leis.llm import get_llm
        llm = get_llm(provider="maritaca")

    user_msg = _build_rewriter_user_message(prior_turns, current_query)
    try:
        raw = llm.complete(
            system=_REWRITER_SYSTEM_PROMPT,
            user=user_msg,
            max_tokens=256,
            temperature=0.0,  # determinism > creativity for a rewriter
        )
    except Exception:
        # Defensive fallback — never crash on a transient provider
        # failure. The pipeline will treat the turn as single-turn,
        # which is degraded but correct behavior.
        return current_query

    return _clean_rewriter_response(raw, current_query)


def _clean_rewriter_response(raw: str, fallback: str) -> str:
    """Strip the common shapes that LLMs prepend/append despite the
    system prompt: leading "Aqui está:" prose, wrapping quotes, markdown
    code fences, trailing punctuation drift. Returns `fallback` if
    cleaning produces an empty string."""
    if not raw:
        return fallback
    text = raw.strip()

    # Drop a leading code-fence block (```...```) if present
    if text.startswith("```"):
        # find the next ```
        end = text.rfind("```")
        if end > 3:
            # extract inside; strip optional language tag
            inner = text[3:end].strip()
            # if there's a language tag (e.g., ```text\n...), drop the first line
            if "\n" in inner:
                first_line, rest = inner.split("\n", 1)
                if len(first_line) <= 10:  # likely a language tag
                    inner = rest
            text = inner.strip()

    # Strip wrapping quotes (single, double, smart). Common LLM habit.
    # Smart-quote pairs are asymmetric — "…" uses U+201C/U+201D, not the
    # same char — so check (opening, closing) pairs not single chars.
    _QUOTE_PAIRS = [('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")]
    for open_q, close_q in _QUOTE_PAIRS:
        if text.startswith(open_q) and text.endswith(close_q) and len(text) >= len(open_q) + len(close_q):
            text = text[len(open_q):-len(close_q)].strip()
            break

    # Drop common Portuguese prefixes ("Reescrita: ...", "Aqui está: ...")
    prefixes = (
        "reescrita:", "aqui está:", "aqui está a query reescrita:",
        "pergunta reescrita:", "query reescrita:", "resposta:",
    )
    lower = text.lower()
    for p in prefixes:
        if lower.startswith(p):
            text = text[len(p):].strip()
            lower = text.lower()
            break

    return text if text else fallback
