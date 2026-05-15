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
