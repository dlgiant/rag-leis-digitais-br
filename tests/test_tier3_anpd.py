"""Golden tests for Tier-3 (ANPD) — Phase 4.3.a manual transcription.

Pins the critical content of each ANPD resolução we transcribed.
Failures here mean either:
  - The build_res_*.py script was edited without verifying content
  - The PDF source changed and the SHA-256 in the build script stayed stale
  - The transcription mis-encoded an article

Phase 4.3.b (real pdfplumber parser) MUST produce chunks that pass these
same tests — that's the contract for swapping the parser body without
breaking downstream consumers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_leis.parsers.anpd_pdf import AnpdPdfParser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RES_15_URN = "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15"


@pytest.fixture(scope="module")
def res_15_chunks() -> dict:
    """Load all Res. 15/2024 chunks via the stub parser, indexed by URN."""
    chunks = AnpdPdfParser().parse(RES_15_URN, "")
    return {c.urn: c for c in chunks}


def _find_chunk(chunks_by_urn: dict, partition_suffix: str):
    """Return the chunk whose URN ends with `partition_suffix`."""
    matches = [u for u in chunks_by_urn if u.endswith(partition_suffix)]
    assert len(matches) == 1, (
        f"expected exactly one chunk ending in {partition_suffix!r}, "
        f"got {len(matches)}: {matches[:3]}"
    )
    return chunks_by_urn[matches[0]]


# ----------------------------------------------------------------------------
# Critical content goldens
# ----------------------------------------------------------------------------


def test_res_15_total_chunk_count(res_15_chunks):
    """Total chunk count. If the build script changes the structure
    (adds/removes articles), this fails until the test is updated AND
    the change is justified."""
    assert len(res_15_chunks) == 131, (
        f"expected 131 chunks (24 art + 73 inc + 34 par), got {len(res_15_chunks)}"
    )


def test_res_15_art6_prazo_3_dias_uteis(res_15_chunks):
    """THE most-cited operational rule of Res. 15/2024: 3 dias úteis prazo
    para comunicação à ANPD. A senior practitioner asking 'em quanto tempo
    devo notificar incidente?' must hit this chunk."""
    art6 = _find_chunk(res_15_chunks, "~art6")
    assert art6.kind == "artigo"
    assert "três dias úteis" in art6.text, (
        f"art.6 caput must contain 'três dias úteis' — got {art6.text[:200]!r}"
    )
    assert "comunicação de incidente" in art6.text.lower()


def test_res_15_art9_prazo_titular(res_15_chunks):
    """The titular-side mirror of art.6: also 3 dias úteis but to the
    affected person. Critical for the practitioner."""
    art9 = _find_chunk(res_15_chunks, "~art9")
    assert "três dias úteis" in art9.text
    assert "titular" in art9.text.lower()


def test_res_15_art3_has_19_definicoes(res_15_chunks):
    """Art. 3 of the Regulamento lists 19 definitions (I-XIX)."""
    art3 = _find_chunk(res_15_chunks, "~art3")
    assert art3.kind == "artigo"
    # All 19 incs of art.3 exist
    for i in range(1, 20):
        partition = f"~art3;inc{i}"
        matches = [u for u in res_15_chunks if u.endswith(partition)]
        assert len(matches) == 1, f"missing art.3;inc{i}"


def test_res_15_inc12_incidente_definition(res_15_chunks):
    """The canonical definition of 'incidente de segurança' lives in
    art.3, XII. This is the most-referenced term in the Regulamento."""
    inc12 = _find_chunk(res_15_chunks, "~art3;inc12")
    assert inc12.kind == "inciso"
    assert "incidente de segurança" in inc12.text.lower()
    assert "evento adverso confirmado" in inc12.text


def test_res_15_art6_par2_has_12_incs(res_15_chunks):
    """§ 2º do art. 6 lists 12 mandatory information items (I-XII) for
    the comunicação. This is what a controlador has to provide to ANPD."""
    for i in range(1, 13):
        partition = f"~art6;par2;inc{i}"
        matches = [u for u in res_15_chunks if u.endswith(partition)]
        assert len(matches) == 1, f"missing art.6;par2;inc{i}"


def test_res_15_art5_criterios_de_risco(res_15_chunks):
    """Art. 5 lists 6 criteria (I-VI) for what counts as 'risco relevante'."""
    for i in range(1, 7):
        partition = f"~art5;inc{i}"
        matches = [u for u in res_15_chunks if u.endswith(partition)]
        assert len(matches) == 1, f"missing art.5;inc{i}"


def test_res_15_audit_metadata_in_jsonl():
    """Audit-metadata invariant: every chunk in the JSONL MUST carry
    source + source_pdf_sha256 + ingestion_method + ingestion_provenance.

    This is the Phase 4.3.a contract. When 4.3.b replaces the parser
    body, source flips from 'claude-code-*' to 'pdfplumber-vN'; this
    test will be updated to expect either, but the FIELDS must always
    be present."""
    import json

    jsonl_path = PROJECT_ROOT / "data" / "chunks" / "tier-3" / "anpd_res_15_2024.jsonl"
    assert jsonl_path.exists()

    audit_fields = {"source", "source_pdf_sha256", "ingestion_method", "ingestion_provenance"}
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            missing = audit_fields - set(obj.keys())
            assert not missing, (
                f"chunk {obj.get('urn')} missing audit fields: {missing}"
            )
            # Phase 4.3.a — source tag must indicate claude-code provenance
            assert obj["source"].startswith("claude-code-"), (
                f"unexpected source tag: {obj['source']!r}"
            )


def test_res_15_capitulo_navigation(res_15_chunks):
    """Nav must carry capítulo + (where applicable) seção for retrieval
    context. Reader's structure is preserved."""
    # Art. 6 is in Capítulo III, Seção II
    art6 = _find_chunk(res_15_chunks, "~art6")
    assert "CAPÍTULO III" in art6.nav.get("capitulo", "")
    assert "Seção II" in art6.nav.get("secao", "")


def test_res_15_anpd_pdf_parser_raises_for_unknown_urn():
    """Defensive: AnpdPdfParser must fail loud (not silently return [])
    when asked for a URN whose JSONL doesn't exist. This is the v0
    failure mode for the gated 1/2021, 2/2022, 4/2023 resoluções."""
    parser = AnpdPdfParser()
    with pytest.raises(FileNotFoundError, match="No tier-3 JSONL"):
        parser.parse(
            "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2099-01-01;99",
            "",
        )
