"""Unit tests for rag_leis.vigencia.

Pure-logic, no network. Validates schema enforcement (typos in status are
load errors, not silent "vigente" defaults), duplicate detection, and the
warning string format that downstream tests assert against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_leis.vigencia import (
    VALID_STATUSES,
    Vigencia,
    load_overlays,
    vigencia_warning,
)


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "overlays.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_real_overlays_file_resolves():
    """The real overlays.yaml shipped at data/vigencia/overlays.yaml must
    parse without errors. Catches typos in status / missing fields the
    moment a curator edits the file."""
    project_root = Path(__file__).resolve().parents[1]
    overlays = load_overlays(project_root / "data" / "vigencia" / "overlays.yaml")
    assert len(overlays) >= 10, f"expected ≥10 overlays in v0, got {len(overlays)}"
    # All MCI art.19 / LGPD art.52 / CF art.5 LXXIX should appear — the
    # canonical cases from the reviewer's critique.
    assert "urn:lex:br:federal:lei:2014-04-23;12965~art19" in overlays
    assert "urn:lex:br:federal:lei:2018-08-14;13709~art52" in overlays
    assert "urn:lex:br:federal:constituicao:1988-10-05;1988~art5;inc79" in overlays


def test_missing_file_returns_empty():
    """A pipeline run without the overlays.yaml present should not crash —
    just behave as if everything is vigente. Defensive for fresh checkouts."""
    assert load_overlays(Path("/nonexistent/path.yaml")) == {}


def test_invalid_status_raises(tmp_path):
    """A typo in status (e.g. 'subjudice' missing the underscore) MUST raise.
    Silent fallback to vigente would mask exactly the cases the overlay was
    supposed to flag."""
    p = _write_yaml(tmp_path, """
- urn: urn:lex:br:federal:lei:2014-04-23;12965~art19
  status: subjudice
  fundamento: STF Tema 987
  desde: 2017-09-29
  descricao_curta: |
    placeholder
""")
    with pytest.raises(ValueError, match="invalid status"):
        load_overlays(p)


def test_duplicate_urn_raises(tmp_path):
    p = _write_yaml(tmp_path, """
- urn: urn:lex:br:federal:lei:2014-04-23;12965~art19
  status: sub_judice
  fundamento: STF Tema 987
  desde: 2017-09-29
  descricao_curta: x
- urn: urn:lex:br:federal:lei:2014-04-23;12965~art19
  status: vigente
  fundamento: y
  desde: 2020-01-01
  descricao_curta: z
""")
    with pytest.raises(ValueError, match="duplicate overlay URN"):
        load_overlays(p)


def test_missing_urn_raises(tmp_path):
    p = _write_yaml(tmp_path, """
- status: sub_judice
  fundamento: x
  desde: 2017-09-29
  descricao_curta: y
""")
    with pytest.raises(ValueError, match="missing 'urn'"):
        load_overlays(p)


def test_warning_string_contains_canonical_marker():
    """The '⚠️ Atenção:' prefix is the assertion target for golden tests
    that the pipeline answer surfaces the flag. Lock the format here."""
    vig = Vigencia(
        status="sub_judice",
        fundamento="STF Tema 987",
        desde="2017-09-29",
        descricao_curta="Aplicação em discussão no STF.",
    )
    msg = vigencia_warning(vig)
    assert msg.startswith("⚠️ Atenção:")
    assert "sub_judice" in msg
    assert "STF Tema 987" in msg
    assert "2017-09-29" in msg


def test_short_label_is_one_line():
    vig = Vigencia(
        status="eficacia_limitada",
        fundamento="ANPD Res. 4/2023",
        desde="2023-02-24",
        descricao_curta="x",
    )
    label = vig.short_label()
    assert "\n" not in label
    assert "eficacia_limitada" in label
    assert "ANPD Res. 4/2023" in label


def test_valid_statuses_taxonomy():
    """If a future commit removes a status from the taxonomy, this test
    will catch the breakage at the level of intent rather than waiting
    for downstream YAML loads to fail."""
    expected = {
        "vigente",
        "sub_judice",
        "suspenso",
        "vacatio_legis",
        "eficacia_limitada",
        "revogado_tacito",
        "alterado_por_ec",
        "alterado_por_jurisprudencia",  # Phase 16.2
        "atualizado_recentemente",
    }
    assert expected == VALID_STATUSES
