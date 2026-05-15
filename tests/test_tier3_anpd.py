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
    when asked for a URN that's neither in ANPD_PARSE_CONFIG nor has
    a fallback JSONL."""
    parser = AnpdPdfParser()
    with pytest.raises(FileNotFoundError, match="No tier-3 source"):
        parser.parse(
            "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2099-01-01;99",
            "",
        )


# ============================================================================
# Phase 4.3.b — pdfplumber-backed parser for Res 4/2023
# ============================================================================

RES_4_URN = "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2023-02-24;4"


@pytest.fixture(scope="module")
def res_4_chunks() -> dict:
    """Load Res. 4/2023 chunks via the real parser. Includes a side
    effect: re-runs the pdfplumber extraction (fast, ~1 sec)."""
    chunks = AnpdPdfParser().parse(RES_4_URN, "")
    return {c.urn: c for c in chunks}


def test_res_4_chunk_count(res_4_chunks):
    """Res. 4/2023 regulamento has 29 articles. Per-kind counts pinned to
    catch regressions in the parser logic (e.g., if a structural marker
    detection breaks, the counts shift)."""
    artigos = [c for c in res_4_chunks.values() if c.kind == "artigo"]
    assert len(artigos) == 29, f"expected 29 artigos, got {len(artigos)}"


def test_res_4_art3_sancao_enumeration(res_4_chunks):
    """The 9 administrative sanctions of LGPD (art. 52 LGPD itself) are
    enumerated here in art.3 of the Regulamento de Dosimetria. The
    canonical 'multa simples' must be one of them."""
    art3_incs = [
        c for c in res_4_chunks.values()
        if c.partition.startswith("art3;inc")
        and c.kind == "inciso"
        and c.partition.count(";") == 1  # top-level (no nested under §§)
    ]
    assert len(art3_incs) == 9, f"art.3 must have 9 sanção incisos, got {len(art3_incs)}"
    # Find inc2 = multa simples
    inc2 = next(c for c in art3_incs if c.partition.endswith("inc2"))
    assert "multa simples" in inc2.text.lower()


def test_res_4_audit_metadata_pdfplumber():
    """Phase 4.3.b distinguishes its chunks from 4.3.a manual ones via
    the source tag. Res 4/2023 must say source=pdfplumber-v1."""
    import json

    jsonl_path = PROJECT_ROOT / "data" / "chunks" / "tier-3" / "anpd_res_4_2023.jsonl"
    assert jsonl_path.exists()

    audit_fields = {"source", "source_pdf_sha256", "ingestion_method", "ingestion_provenance"}
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            missing = audit_fields - set(obj.keys())
            assert not missing, f"chunk {obj.get('urn')} missing audit fields: {missing}"
            assert obj["source"] == "pdfplumber-v1", (
                f"Res. 4/2023 must be pdfplumber-extracted (source=pdfplumber-v1); "
                f"got source={obj['source']!r}"
            )
            assert obj["ingestion_method"] == "pdfplumber-extraction"


def test_res_4_capitulo_navigation(res_4_chunks):
    """Each chunk carries CAPÍTULO + Seção nav for retrieval context."""
    # art.1 is in CAPÍTULO I
    art1 = res_4_chunks[f"{RES_4_URN}~art1"]
    assert "CAPÍTULO I" in art1.nav.get("capitulo", "")
    # art.3 starts CAPÍTULO II Seção I
    art3 = res_4_chunks[f"{RES_4_URN}~art3"]
    assert "CAPÍTULO II" in art3.nav.get("capitulo", "")


def test_res_4_alineas_under_art3_par1_inc2():
    """art.3 §1, inc.II has alíneas a/b (má-fé / práticas irregulares).
    This is the only place with alíneas in Res. 4/2023 — pinning it
    proves the alínea parser path works."""
    chunks = AnpdPdfParser().parse(RES_4_URN, "")
    by_urn = {c.urn: c for c in chunks}

    ali_a = by_urn.get(f"{RES_4_URN}~art3;par1;inc2;ali-a")
    ali_b = by_urn.get(f"{RES_4_URN}~art3;par1;inc2;ali-b")
    assert ali_a is not None, "missing art.3;par1;inc2;ali-a (má-fé)"
    assert ali_b is not None, "missing art.3;par1;inc2;ali-b (práticas irregulares)"
    assert "má-fé" in ali_a.text.lower()
    assert "práticas irregulares" in ali_b.text.lower()


def test_anpd_parse_config_only_has_real_parser_urns():
    """Sanity: ANPD_PARSE_CONFIG should only contain URNs we've actually
    page-mapped + tested. Adding without testing would be a footgun."""
    from rag_leis.parsers.anpd_pdf import ANPD_PARSE_CONFIG

    assert RES_4_URN in ANPD_PARSE_CONFIG
    # The Res. 15/2024 URN should NOT be in config (it uses the JSONL
    # fallback path; Phase 4.3.a manual transcription is the canonical
    # source for that one until a future re-validation phase).
    assert RES_15_URN not in ANPD_PARSE_CONFIG
