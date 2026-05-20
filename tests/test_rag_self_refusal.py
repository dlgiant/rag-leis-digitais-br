"""Unit tests for the LLM-self-refusal classifier in rag_leis.rag.

This is the load-bearing OOS signal — the cosine fast-path only catches
extreme cases. Bugs here would silently flip OOS rows back to "answered"
in the eval, which is the failure mode Phase 2.7 was meant to fix.
"""

from __future__ import annotations

from rag_leis.rag import _is_self_refusal


def test_canonical_prefix_is_refusal():
    """The exact phrase the system prompt instructs the model to emit."""
    assert _is_self_refusal("Não há informação suficiente nas fontes fornecidas.")


def test_refusal_with_followup_explanation_still_refusal():
    """Common pattern: model refuses then explains what little it found.
    The leading sentence is the signal, anchored at the start."""
    text = (
        "Não há informação suficiente nas fontes fornecidas. As fontes "
        "disponíveis limitam-se a mencionar que o casamento civil pode "
        "ser dissolvido pelo divórcio (Art. 226 §6 CF), sem detalhar "
        "procedimento."
    )
    assert _is_self_refusal(text)


def test_refusal_case_insensitive():
    assert _is_self_refusal("NÃO HÁ INFORMAÇÃO SUFICIENTE...")
    assert _is_self_refusal("não Há informação suficiente...")


def test_alternative_refusal_phrasings():
    assert _is_self_refusal("Não foi possível encontrar...")
    assert _is_self_refusal("As fontes fornecidas não contêm...")
    assert _is_self_refusal("Fora do escopo da base.")  # cosine fast-path
    assert _is_self_refusal("Não há informações suficientes...")  # plural


def test_real_answer_mentioning_no_info_inline_is_NOT_refusal():
    """A real answer that happens to use 'não há informação' inline
    shouldn't trigger — the prefix must be the literal lead."""
    text = (
        "O Marco Civil da Internet (art. 9º) estabelece neutralidade. "
        "Não há informação no caput sobre os critérios técnicos; estes "
        "constam dos parágrafos."
    )
    assert not _is_self_refusal(text)


def test_empty_string_is_not_refusal():
    """Defensive — an empty answer (LLM bug?) shouldn't auto-refuse."""
    assert not _is_self_refusal("")
    assert not _is_self_refusal("   \n  ")


def test_real_answer_does_not_match():
    """A normal substantive answer must not trigger."""
    assert not _is_self_refusal(
        "Segundo a LGPD (art. 5º, I), dado pessoal é toda informação "
        "relacionada a pessoa natural identificada ou identificável."
    )


def test_leading_whitespace_tolerated():
    """The model sometimes leads with a newline or a space."""
    assert _is_self_refusal("  \n  Não há informação suficiente nas fontes.")


# ----------------------------------------------------------------------------
# Phase 7.7 — Pattern A from phase-7.5.3-legalbench-oos-findings.md §3:
# the model refuses mid-paragraph after a preamble. The old 120-char prefix
# scan missed these entirely. The full-text scan must catch them.
# ----------------------------------------------------------------------------


def test_pattern_a_refusal_after_preamble_caught():
    """Real failure case from 7.5.3 legalbench/182 — model explains what
    it tried, then concludes with the canonical refusal phrase. The whole
    body needs to be scanned, not just the first 120 chars."""
    text = (
        "O momento adequado para arguir a incompetência territorial "
        "está previsto no Código de Processo Civil, norma que não está "
        "presente nas fontes fornecidas. As fontes constitucionais "
        "(CF/88) não disciplinam o momento processual específico para "
        "essa arguição. Portanto, não há informação suficiente nas "
        "fontes fornecidas para responder à pergunta com precisão."
    )
    assert _is_self_refusal(text)


def test_pattern_a_refusal_with_alternative_phrasing_caught():
    """Same shape but with 'as fontes fornecidas não' appearing
    mid-paragraph after a preamble."""
    text = (
        "Considerando o conteúdo do art. 5 CF, observamos que a "
        "matéria orçamentária requer fundamentação específica. "
        "Conforme análise das normas indexadas, as fontes fornecidas "
        "não contêm o dispositivo aplicável ao caso."
    )
    assert _is_self_refusal(text)


def test_substantive_answer_with_inline_no_info_still_not_refusal():
    """Stronger version of the existing guard: a long real answer that
    contains 'não há informação' (without 'suficiente') must NOT be
    flagged — the qualifier 'suficiente' is what disambiguates."""
    text = (
        "A LGPD (Lei 13.709/2018) trata de dados pessoais em seu art. 5, "
        "I, definindo o conceito. Não há informação específica no caput "
        "sobre prazo de retenção; o art. 16 trata dessa hipótese. "
        "Adicionalmente, o art. 7 enumera as bases legais. Portanto, "
        "a resposta requer leitura combinada dos arts. 5, 7 e 16."
    )
    assert not _is_self_refusal(text)


def test_refusal_with_long_preamble_caught():
    """Edge case: a very long preamble (>500 chars) before the refusal
    phrase. Old prefix-scan would miss; new full-text scan must catch."""
    preamble = "A questão envolve análise complexa de múltiplos dispositivos. " * 8
    text = preamble + " Portanto, não há informação suficiente nas fontes."
    assert _is_self_refusal(text)
