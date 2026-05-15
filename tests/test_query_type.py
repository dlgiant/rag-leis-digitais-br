"""Unit tests for rag_leis.query_type — pure-regex query classifier.

Coverage targets the ambiguous cases the classifier has to decide:
  - "quais artigos da LGPD..." should be enumeração (not citação-literal,
    even though "artigo" appears — but it's plural, no specific number)
  - "o que diz o art. 9" should be citação-literal (not definição, even
    though "o que" appears)
  - "diferença entre LGPD e MCI" should be cross-doc (not paráfrase)
  - "o que é dado pessoal" should be definição (not paráfrase)

If any of these flip, callers downstream (adaptive top_k, prompt snippet)
land on the wrong defaults silently.
"""

from __future__ import annotations

import pytest

from rag_leis.query_type import (
    TOP_K_PER_TYPE,
    TYPE_PROMPT_SNIPPETS,
    classify_query,
    prompt_snippet_for_query,
    top_k_for_query,
)

# ----------------------------------------------------------------------------
# enumeracao
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "quais são as hipóteses legais para tratar dados pessoais?",
        "liste os princípios da LGPD",
        "enumere os direitos do titular",
        "quais sanções a ANPD pode aplicar?",
        # Ambiguity test — "artigos" plural + "quais" should be enumeração
        # even though "artigo" appears (no specific number → not literal).
        "quais artigos da LGPD tratam de marketing?",
    ],
)
def test_classify_enumeracao(query):
    assert classify_query(query) == "enumeracao"


# ----------------------------------------------------------------------------
# citacao-literal
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "o que diz o art. 9 do Marco Civil?",
        "o que diz o art. 154-A do Código Penal?",
        "art. 5 inciso X da Constituição",
        "Art 19 do MCI",
        "qual o conteúdo do artigo 18 da LGPD",
    ],
)
def test_classify_citacao_literal(query):
    assert classify_query(query) == "citacao-literal"


# ----------------------------------------------------------------------------
# cross-doc
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "diferença entre dado pessoal e informação pessoal",
        "comparação entre LGPD e MCI sobre consentimento",
        "relação entre habeas data e LGPD",
    ],
)
def test_classify_cross_doc(query):
    assert classify_query(query) == "cross-doc"


# ----------------------------------------------------------------------------
# definicao
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "o que é dado pessoal?",
        "o que são dados pessoais sensíveis?",
        "qual a definição de tratamento de dados?",
        "defina neutralidade de rede",
        "como é definido o conceito de habeas data?",
    ],
)
def test_classify_definicao(query):
    assert classify_query(query) == "definicao"


# ----------------------------------------------------------------------------
# parafrase (fallback)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "minha empresa precisa pedir autorização pra mandar e-mail marketing?",
        "fui invadido no celular sem permissão, isso é crime?",
        "policial pode pedir meus dados pra investigar crime?",
        "se vazaram meus dados, quem me avisa?",
    ],
)
def test_classify_parafrase(query):
    assert classify_query(query) == "parafrase"


# ----------------------------------------------------------------------------
# Precedence (order-of-evaluation tests)
# ----------------------------------------------------------------------------


def test_enumeracao_beats_citacao_literal_when_artigo_is_plural():
    """'quais artigos' triggers enumeração despite 'artigo' appearing — the
    plural + 'quais' is the stronger signal."""
    assert classify_query("quais artigos da LGPD tratam de consentimento?") == "enumeracao"


def test_citacao_literal_beats_definicao_when_specific_artigo():
    """'o que diz o art. 9' has 'o que' (definicao trigger) AND 'art. 9'
    (citacao-literal trigger). Citação-literal wins because the article
    number is the specific anchor."""
    assert classify_query("o que diz o art. 9 do MCI?") == "citacao-literal"


def test_cross_doc_beats_parafrase():
    """'diferença entre' is a strong cross-doc signal even in informal phrasing."""
    assert classify_query("qual a diferença entre LGPD e MCI?") == "cross-doc"


# ----------------------------------------------------------------------------
# Convenience accessors
# ----------------------------------------------------------------------------


def test_top_k_for_query_uses_classification():
    assert top_k_for_query("o que diz o art. 9?") == TOP_K_PER_TYPE["citacao-literal"]
    assert top_k_for_query("quais princípios da LGPD?") == TOP_K_PER_TYPE["enumeracao"]
    assert top_k_for_query("o que é dado pessoal?") == TOP_K_PER_TYPE["definicao"]


def test_prompt_snippet_for_query_uses_classification():
    snip = prompt_snippet_for_query("quais princípios da LGPD?")
    assert "enumeração" in snip.lower()
    assert prompt_snippet_for_query("policial pode pedir dados?") == ""


def test_top_k_table_covers_all_known_types():
    """If a new type joins the classifier, this test fails until TOP_K_PER_TYPE
    grows to match. Same for TYPE_PROMPT_SNIPPETS."""
    from rag_leis.query_type import _PATTERNS

    classifier_types = {t for t, _ in _PATTERNS} | {"parafrase"}
    assert classifier_types <= set(TOP_K_PER_TYPE.keys()), (
        f"TOP_K_PER_TYPE missing entries for: {classifier_types - set(TOP_K_PER_TYPE.keys())}"
    )
    assert classifier_types <= set(TYPE_PROMPT_SNIPPETS.keys()), (
        f"TYPE_PROMPT_SNIPPETS missing: {classifier_types - set(TYPE_PROMPT_SNIPPETS.keys())}"
    )
