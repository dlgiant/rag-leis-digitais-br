"""Phase 7.6.2 — tests for concept-scope module.

Focus: vocabulary integrity, extractor's defensive vocabulary filter,
and the scope-overlap gate decision predicate. Does not call real LLMs.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from rag_leis.concept_scope import (
    CONCEPT_EXTRACTION_TOOL,
    CONCEPT_VOCABULARY,
    EXTRACTION_SYSTEM_PROMPT,
    check_scope_overlap,
    extract_concept_tags,
)
from rag_leis.corpus import CORPUS_BY_URN

# ----------------------------------------------------------------------------
# Vocabulary integrity
# ----------------------------------------------------------------------------


def test_vocabulary_is_non_empty():
    """Built from union of Document.document_scope across the registry.
    If this fails, no Document has tags, and the gate can never fire."""
    assert len(CONCEPT_VOCABULARY) > 0


def test_vocabulary_is_frozenset_of_strings():
    """Type contract: caller can `in` against it and iterate stably."""
    assert isinstance(CONCEPT_VOCABULARY, frozenset)
    for item in CONCEPT_VOCABULARY:
        assert isinstance(item, str)
        assert item.strip() == item  # no leading/trailing whitespace
        assert " " not in item  # tags are hyphen-cased, not space-separated


def test_vocabulary_covers_expected_core_concepts():
    """Smoke test: concepts a hiring reviewer would expect in a Brazilian
    legal-digital RAG MUST be present. Catches accidental tag deletion."""
    must_have = {
        "dados-pessoais", "consentimento", "habeas-data",
        "marco-civil", "crimes-ciberneticos", "direitos-autorais",
        "ANPD", "intimidade",
    }
    missing = must_have - CONCEPT_VOCABULARY
    assert not missing, f"Vocabulary missing core concepts: {missing}"


def test_system_prompt_enumerates_full_vocabulary():
    """The extractor LLM gets the full vocabulary inlined — verify all
    tags appear in the prompt so the model isn't blind to any concept."""
    for tag in CONCEPT_VOCABULARY:
        assert tag in EXTRACTION_SYSTEM_PROMPT, f"Tag {tag!r} not in prompt"


def test_extraction_tool_has_required_shape():
    """Schema contract: tool returns {concepts: list[str]}, required."""
    assert CONCEPT_EXTRACTION_TOOL["name"] == "extrair_conceitos_consulta"
    props = CONCEPT_EXTRACTION_TOOL["input_schema"]["properties"]
    assert "concepts" in props
    assert props["concepts"]["type"] == "array"
    assert "concepts" in CONCEPT_EXTRACTION_TOOL["input_schema"]["required"]


# ----------------------------------------------------------------------------
# extract_concept_tags — defensive vocabulary filter
# ----------------------------------------------------------------------------


def _stub_llm_returning(concepts: list[str]):
    """Build a stub LLM whose complete_structured returns the given concepts."""
    stub = MagicMock()
    stub.complete_structured.return_value = {"concepts": concepts}
    stub.last_call_usage = {"input_tokens": 100, "output_tokens": 20}
    stub.provider = "maritaca"
    stub.name = "sabia-3.1"
    return stub


def test_extract_concepts_returns_valid_vocabulary_members():
    """Happy path: LLM returns valid tags; function passes them through."""
    valid = sorted(CONCEPT_VOCABULARY)[:3]
    stub = _stub_llm_returning(valid)
    result = extract_concept_tags("a query about LGPD", stub)
    assert set(result) == set(valid)


def test_extract_concepts_filters_hallucinated_tags():
    """LLM returns tags not in vocabulary → must be dropped silently.
    The structured-output schema can't constrain enum values across all
    providers, so client-side filter is the guardrail."""
    valid = sorted(CONCEPT_VOCABULARY)[0]
    stub = _stub_llm_returning([valid, "tag-that-does-not-exist", "another-fake-tag"])
    result = extract_concept_tags("a query", stub)
    assert result == [valid]


def test_extract_concepts_empty_query_returns_empty_list():
    """Defensive: empty/whitespace-only query → no LLM call, no concepts."""
    stub = _stub_llm_returning(["dados-pessoais"])
    result = extract_concept_tags("   ", stub)
    assert result == []
    # And the stub LLM was NOT called
    stub.complete_structured.assert_not_called()


def test_extract_concepts_handles_empty_llm_response():
    """LLM returns concepts=[] → empty list back (NOT an error)."""
    stub = _stub_llm_returning([])
    result = extract_concept_tags("a query", stub)
    assert result == []


def test_extract_concepts_drops_non_string_items():
    """Defensive: even if LLM returns {concepts: [None, 1, "valid"]}, only
    string items in vocab survive."""
    valid = sorted(CONCEPT_VOCABULARY)[0]
    stub = MagicMock()
    stub.complete_structured.return_value = {"concepts": [None, 1, valid]}
    stub.last_call_usage = {"input_tokens": 100, "output_tokens": 20}
    stub.provider = "maritaca"
    stub.name = "sabia-3.1"
    result = extract_concept_tags("a query", stub)
    assert result == [valid]


# ----------------------------------------------------------------------------
# check_scope_overlap — the gate decision predicate
# ----------------------------------------------------------------------------


def test_empty_query_concepts_never_refuses():
    """Defensive: empty query_concepts → defer to downstream gates.
    Refusing on extractor-coverage-failure would create false-refusals
    on legitimate in-scope queries the extractor didn't tag."""
    refuse, retrieval = check_scope_overlap([], ["urn:lex:br:federal:lei:2018-08-14;13709"])
    assert refuse is False
    assert retrieval == set()


def test_empty_retrieval_doc_urns_never_refuses():
    """Defensive: no retrieval to compare → defer to downstream gates."""
    refuse, retrieval = check_scope_overlap(["dados-pessoais"], [])
    assert refuse is False
    assert retrieval == set()


def test_overlap_present_does_not_refuse():
    """Happy path: query mentions dados-pessoais, retrieval has LGPD doc
    (which is tagged dados-pessoais). Gate must NOT fire."""
    lgpd_urn = "urn:lex:br:federal:lei:2018-08-14;13709"
    assert lgpd_urn in CORPUS_BY_URN  # sanity
    refuse, retrieval = check_scope_overlap(
        ["dados-pessoais"], [lgpd_urn]
    )
    assert refuse is False
    assert "dados-pessoais" in retrieval


def test_no_overlap_refuses():
    """Refusal path: query about sigilo-bancario; retrieval is LGPD (no
    tag overlap). Gate must fire."""
    lgpd_urn = "urn:lex:br:federal:lei:2018-08-14;13709"
    refuse, retrieval = check_scope_overlap(
        ["sigilo-bancario"], [lgpd_urn]
    )
    assert refuse is True
    assert "sigilo-bancario" not in retrieval
    # LGPD's actual tags must be in retrieval for refusal_reason audit
    assert "dados-pessoais" in retrieval


def test_partial_overlap_does_not_refuse():
    """Mixed: query mentions 2 concepts, retrieval covers 1 of them.
    Any overlap is enough — gate does NOT refuse on partial mismatch."""
    lgpd_urn = "urn:lex:br:federal:lei:2018-08-14;13709"
    refuse, _retrieval = check_scope_overlap(
        ["dados-pessoais", "sigilo-bancario"], [lgpd_urn]
    )
    assert refuse is False  # dados-pessoais overlaps; that's enough


def test_unknown_doc_urn_skipped_silently():
    """Defensive: retrieval contains a doc URN not in CORPUS_BY_URN
    (race condition / stale index). Skip it, don't crash."""
    refuse, retrieval = check_scope_overlap(
        ["dados-pessoais"], ["urn:lex:br:federal:lei:9999-12-31;99999"]
    )
    # Unknown URN contributes no tags → effectively empty retrieval
    # → defensive default: don't refuse
    assert refuse is False
    assert retrieval == set()


# ----------------------------------------------------------------------------
# Corpus-side: every Document declares ≥1 tag
# ----------------------------------------------------------------------------


def test_every_corpus_document_has_at_least_one_tag():
    """Without this assertion, a future Document added without tags
    would be silently invisible to the scope-check gate. Force errors
    at test time, not at production query time."""
    missing = [doc.urn for doc in CORPUS_BY_URN.values() if not doc.document_scope]
    assert not missing, f"Documents without document_scope: {missing}"


def test_corpus_tags_are_all_in_vocabulary():
    """Trivially true by construction (vocabulary IS the union), but
    asserts that no Document accidentally has a typo'd tag that wouldn't
    be in vocabulary even though it's in document_scope."""
    for doc in CORPUS_BY_URN.values():
        for tag in doc.document_scope:
            assert tag in CONCEPT_VOCABULARY, (
                f"{doc.urn} has tag {tag!r} not in CONCEPT_VOCABULARY"
            )
