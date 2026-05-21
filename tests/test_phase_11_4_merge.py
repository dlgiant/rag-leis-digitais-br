"""Phase 11.4 — tests for the merge tool's YAML-edit logic.

These are PURE tests: no DB connection, no stdin. They exercise the
ruamel.yaml round-trip + the apply_review / apply_new_row functions
against an in-memory fixture matching the shape of eval/queries.yaml.

Test strategy: build a Proposal in code, call apply_*_to_yaml against
a known input, assert the resulting rows have the expected mutation.
ruamel.yaml's round-trip is exercised implicitly by reading the
fixture via load_eval() and writing it back via save_eval(), then
re-reading to confirm structure preserved.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from rag_leis.eval_loader import query_id as derive_query_id
from rag_leis.proposals import Proposal
from scripts.phase_11_4_merge_proposals import (
    apply_new_row_to_yaml,
    apply_refinement_to_yaml,
    apply_review_to_yaml,
    find_row_by_query_id,
    load_eval,
    save_eval,
)


@pytest.fixture
def fixture_yaml(tmp_path: Path) -> Path:
    """A minimal eval/queries.yaml shape — 2 rows with comments + types."""
    p = tmp_path / "queries.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            # Eval fixture for Phase 11.4 tests.

            - query: "qual a definição de dado pessoal na LGPD?"
              type: definicao
              relevant: ["urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1"]
              notes: "LGPD art. 5º, I — definição literal."

            - query: "o que é neutralidade de rede no Marco Civil?"
              type: definicao
              relevant: ["urn:lex:br:federal:lei:2014-04-23;12965~art9"]
              notes: "MCI art. 9."
            """
        )
    )
    return p


# ---------------------------------------------------------------------------
# load_eval / save_eval — ruamel round-trip
# ---------------------------------------------------------------------------


def test_load_eval_reads_rows(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert rows[0]["query"] == "qual a definição de dado pessoal na LGPD?"
    assert rows[1]["type"] == "definicao"


def test_save_eval_roundtrips(fixture_yaml: Path):
    """Reading, then writing without changes, should preserve comments
    + structure (modulo formatting equivalence)."""
    rows = load_eval(fixture_yaml)
    save_eval(rows, fixture_yaml)
    written = fixture_yaml.read_text(encoding="utf-8")
    # ruamel preserves the comment; rows survive
    assert "# Eval fixture for Phase 11.4 tests." in written
    assert "qual a definição de dado pessoal na LGPD?" in written
    # Round-trip output may differ in trivial whitespace from the
    # human-written input; load again and assert structure.
    rows_again = load_eval(fixture_yaml)
    assert len(rows_again) == len(rows)
    assert rows_again[0]["query"] == rows[0]["query"]


# ---------------------------------------------------------------------------
# find_row_by_query_id
# ---------------------------------------------------------------------------


def test_find_row_by_query_id_hits(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    qid = derive_query_id(rows[0]["query"])
    located = find_row_by_query_id(rows, qid)
    assert located is not None
    idx, row = located
    assert idx == 0
    assert row["query"] == rows[0]["query"]


def test_find_row_by_query_id_misses(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    located = find_row_by_query_id(rows, "deadbeef0000")
    assert located is None


# ---------------------------------------------------------------------------
# apply_review_to_yaml
# ---------------------------------------------------------------------------


def _make_review_proposal(
    query_id: str,
    *,
    verdict: str = "correct",
    suggested_gold_urns: tuple[str, ...] = (),
    suggested_classified_type: str | None = None,
    notes: str = "",
) -> Proposal:
    return Proposal(
        id="prop-test-1",
        ts="2026-05-21T15:00:00+00:00",
        reviewer_email="lawyer@example.test",
        is_operator=False,
        kind="review",
        query_id=query_id,
        verdict=verdict,
        notes=notes,
        suggested_gold_urns=suggested_gold_urns,
        suggested_classified_type=suggested_classified_type,
    )


def test_apply_review_with_suggested_urns_replaces_relevant(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    qid = derive_query_id(rows[0]["query"])
    p = _make_review_proposal(
        qid,
        verdict="incorrect",
        suggested_gold_urns=(
            "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2",
        ),
    )
    msg = apply_review_to_yaml(rows, p)
    assert "relevant" in msg
    # The first row's relevant field should now be the suggestion
    new_urns = list(rows[0]["relevant"])
    assert new_urns == ["urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2"]


def test_apply_review_with_suggested_classified_type_updates_type(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    qid = derive_query_id(rows[0]["query"])
    p = _make_review_proposal(
        qid,
        verdict="incorrect",
        suggested_classified_type="parafrase",
    )
    msg = apply_review_to_yaml(rows, p)
    assert "type" in msg
    assert rows[0]["type"] == "parafrase"


def test_apply_review_correct_with_no_suggestions_is_noop(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    qid = derive_query_id(rows[0]["query"])
    original_row = dict(rows[0])
    p = _make_review_proposal(qid, verdict="correct")
    msg = apply_review_to_yaml(rows, p)
    assert "no yaml change" in msg.lower()
    # Row is unchanged
    assert rows[0]["query"] == original_row["query"]
    assert rows[0]["type"] == original_row["type"]


def test_apply_review_missing_query_id_raises(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    p = _make_review_proposal(
        "deadbeef0000",  # not in fixture
        suggested_gold_urns=("urn:x",),
    )
    with pytest.raises(ValueError, match="not found"):
        apply_review_to_yaml(rows, p)


def test_apply_review_without_query_id_raises(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    p = Proposal(
        id="x", ts="2026-05-21T00:00:00+00:00",
        reviewer_email="x", is_operator=False, kind="review",
        query_id=None, verdict="correct",
    )
    with pytest.raises(ValueError, match="missing query_id"):
        apply_review_to_yaml(rows, p)


# ---------------------------------------------------------------------------
# apply_new_row_to_yaml
# ---------------------------------------------------------------------------


def test_apply_new_row_appends(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    initial_count = len(rows)
    p = Proposal(
        id="newrow-1",
        ts="2026-05-21T16:00:00+00:00",
        reviewer_email="operator@example.test",
        is_operator=True,
        kind="new_row",
        new_query_text="qual o prazo de retenção de logs de conexão?",
        new_qtype="definicao",
        new_core_urns=(
            "urn:lex:br:federal:lei:2014-04-23;12965~art13",
        ),
        notes="MCI art. 13 — 1 ano",
    )
    msg = apply_new_row_to_yaml(rows, p)
    assert "appended" in msg
    assert len(rows) == initial_count + 1
    new_row = rows[-1]
    assert new_row["query"] == "qual o prazo de retenção de logs de conexão?"
    assert new_row["type"] == "definicao"
    assert list(new_row["relevant"]) == [
        "urn:lex:br:federal:lei:2014-04-23;12965~art13"
    ]
    assert new_row["notes"] == "MCI art. 13 — 1 ano"


def test_apply_new_row_with_supporting_urns_uses_graded_form(fixture_yaml: Path):
    """When supporting URNs are present, the YAML uses the graded
    `relevant: {core: [...], supporting: [...]}` shape."""
    rows = load_eval(fixture_yaml)
    p = Proposal(
        id="newrow-2",
        ts="2026-05-21T16:30:00+00:00",
        reviewer_email="operator@example.test",
        is_operator=True,
        kind="new_row",
        new_query_text="quais princípios regem o tratamento de dados?",
        new_qtype="enumeracao",
        new_core_urns=("urn:lex:br:federal:lei:2018-08-14;13709~art6",),
        new_supporting_urns=("urn:lex:br:federal:lei:2018-08-14;13709~art5",),
    )
    apply_new_row_to_yaml(rows, p)
    new_row = rows[-1]
    assert isinstance(new_row["relevant"], dict)
    assert "core" in new_row["relevant"]
    assert "supporting" in new_row["relevant"]


def test_apply_new_row_missing_query_text_raises(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    p = Proposal(
        id="x", ts="2026-05-21T00:00:00+00:00",
        reviewer_email="x", is_operator=True, kind="new_row",
        new_query_text=None,
    )
    with pytest.raises(ValueError, match="new_query_text"):
        apply_new_row_to_yaml(rows, p)


# ---------------------------------------------------------------------------
# Full round-trip: edit + save + re-load gives the same data
# ---------------------------------------------------------------------------


def test_apply_and_save_roundtrips(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    qid = derive_query_id(rows[0]["query"])
    p = _make_review_proposal(
        qid,
        verdict="incorrect",
        suggested_gold_urns=(
            "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2",
        ),
    )
    apply_review_to_yaml(rows, p)
    save_eval(rows, fixture_yaml)

    # Re-load and verify the change persisted
    rows_again = load_eval(fixture_yaml)
    new_urns = list(rows_again[0]["relevant"])
    assert new_urns == ["urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2"]
    # Comment from the top of the file should still be there
    written = fixture_yaml.read_text(encoding="utf-8")
    assert "# Eval fixture for Phase 11.4 tests." in written


# ---------------------------------------------------------------------------
# apply_refinement_to_yaml (Phase 11.3 → 11.4 promotion path)
# ---------------------------------------------------------------------------


def test_apply_refinement_promotes_to_new_row(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    initial_count = len(rows)
    p = Proposal(
        id="refine-1",
        ts="2026-05-21T17:00:00+00:00",
        reviewer_email="lawyer@example.test",
        is_operator=False,
        kind="refinement",
        query_id="abc123",
        refined_query_text="alternate phrasing — what is the LGPD definition of personal data?",
        new_core_urns=(
            "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1",
            "urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2",
        ),
    )
    msg = apply_refinement_to_yaml(rows, p)
    assert "promoted refinement" in msg
    assert len(rows) == initial_count + 1
    new_row = rows[-1]
    assert new_row["query"] == p.refined_query_text
    # URNs captured at refine-time become the row's relevant
    assert list(new_row["relevant"]) == list(p.new_core_urns)


def test_apply_refinement_missing_refined_text_raises(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    p = Proposal(
        id="x", ts="2026-05-21T00:00:00+00:00",
        reviewer_email="x", is_operator=False, kind="refinement",
        refined_query_text=None,
        new_core_urns=("urn:lex:x",),
    )
    with pytest.raises(ValueError, match="refined_query_text"):
        apply_refinement_to_yaml(rows, p)


def test_apply_refinement_missing_retrieved_urns_raises(fixture_yaml: Path):
    rows = load_eval(fixture_yaml)
    p = Proposal(
        id="x", ts="2026-05-21T00:00:00+00:00",
        reviewer_email="x", is_operator=False, kind="refinement",
        refined_query_text="some phrasing",
        new_core_urns=(),
    )
    with pytest.raises(ValueError, match="new_core_urns"):
        apply_refinement_to_yaml(rows, p)


# ---------------------------------------------------------------------------
# Phase 12.3 — apply_vigencia_to_yaml (overlays.yaml writes)
# ---------------------------------------------------------------------------


@pytest.fixture
def overlays_yaml(tmp_path: Path) -> Path:
    """Minimal overlays.yaml fixture with one pre-existing entry."""
    p = tmp_path / "overlays.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            # Vigência overlays fixture for tests.

            - urn: "urn:lex:br:federal:lei:2014-04-23;12965~art19"
              status: sub_judice
              fundamento: "STF RE 1.037.396 (Tema 987)"
              desde: 2017-09-29
              descricao_curta: |
                Aplicação em discussão no STF.
            """
        )
    )
    return p


def _make_vigencia_proposal(
    *,
    urn: str,
    status: str = "sub_judice",
    fundamento: str = "STF RE 9.999.999",
    desde: str = "2026-05-21",
    descricao: str = "Test descrição curta de vigência.",
) -> Proposal:
    return Proposal(
        id="vig-test-1",
        ts="2026-05-21T17:00:00+00:00",
        reviewer_email="lawyer@example.test",
        is_operator=False,
        kind="vigencia",
        vigencia_urn=urn,
        vigencia_status=status,
        vigencia_fundamento=fundamento,
        vigencia_desde=desde,
        vigencia_descricao_curta=descricao,
    )


def test_apply_vigencia_appends_new_overlay(overlays_yaml: Path):
    from scripts.phase_11_4_merge_proposals import (
        apply_vigencia_to_yaml,
        load_overlays_yaml,
    )
    rows = load_overlays_yaml(overlays_yaml)
    initial = len(rows)
    p = _make_vigencia_proposal(
        urn="urn:lex:br:federal:lei:2018-08-14;13709~art42",
    )
    msg = apply_vigencia_to_yaml(rows, p)
    assert "appended" in msg
    assert len(rows) == initial + 1
    assert rows[-1]["urn"] == "urn:lex:br:federal:lei:2018-08-14;13709~art42"
    assert rows[-1]["status"] == "sub_judice"


def test_apply_vigencia_replaces_existing_overlay(overlays_yaml: Path):
    from scripts.phase_11_4_merge_proposals import (
        apply_vigencia_to_yaml,
        load_overlays_yaml,
    )
    rows = load_overlays_yaml(overlays_yaml)
    initial = len(rows)
    # The fixture already has an entry for MCI art. 19; submit a new
    # annotation that REPLACES its fields.
    p = _make_vigencia_proposal(
        urn="urn:lex:br:federal:lei:2014-04-23;12965~art19",
        status="suspenso",
        fundamento="Liminar ADPF nova",
    )
    msg = apply_vigencia_to_yaml(rows, p)
    assert "replaced" in msg
    # No new entry — same length
    assert len(rows) == initial
    # First row's status changed
    assert rows[0]["status"] == "suspenso"
    assert rows[0]["fundamento"] == "Liminar ADPF nova"


def test_apply_vigencia_missing_field_raises(overlays_yaml: Path):
    from scripts.phase_11_4_merge_proposals import apply_vigencia_to_yaml
    rows: list[dict] = []
    p = Proposal(
        id="x", ts="2026-05-21T00:00:00+00:00",
        reviewer_email="x", is_operator=False, kind="vigencia",
        vigencia_urn="urn:lex:br:federal:lei:2018-08-14;13709~art1",
        vigencia_status="sub_judice",
        vigencia_fundamento=None,  # missing
        vigencia_desde="2026-05-21",
        vigencia_descricao_curta="x",
    )
    with pytest.raises(ValueError, match="fundamento"):
        apply_vigencia_to_yaml(rows, p)
