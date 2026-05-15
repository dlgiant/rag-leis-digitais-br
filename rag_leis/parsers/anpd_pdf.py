"""Phase 4.3.b — real pdfplumber-backed parser for ANPD resoluções.

Replaces the Phase 4.3.a stub body. Same `Parser` protocol contract
(parse(document_urn, source) → list[Chunk]); same JSONL format on
disk; same audit-metadata fields. The difference: chunks now come from
running pdfplumber on the PDF instead of re-reading a hand-curated
JSONL.

How it works:

1. **Per-document config registry** (`ANPD_PARSE_CONFIG`). Each ANPD URN
   maps to its bundle PDF + the page range where the regulamento lives.
   ANPD distributes resoluções as multi-hundred-page SEI bundles
   (ofícios + notas técnicas + minuta); the regulamento is always
   present but at a different offset in each bundle. The page range is
   human-determined once per document and treated as static metadata.

2. **Text extraction via pdfplumber**, page-by-page, footer stripped.

3. **Light cleanup**: SEI footer (`Anexo [...]_Minuta (...) SEI ...`),
   page-break artifacts, occasional missing-space bugs (e.g.,
   "aqueleque" → "aquele que").

4. **Structure detection via regex**: CAPÍTULO / Seção (nav), Art. N
   (artigo), § N (parágrafo), Roman numeral incisos, letter alíneas.
   Re-uses the LCP-95 patterns from rag_leis.parser where appropriate.

5. **Audit metadata** flipped from manual transcription to
   `pdfplumber-v1`. The PDF SHA-256 is hashed at parse time and embedded
   in every chunk.

Fallback: if a URN isn't in ANPD_PARSE_CONFIG, the parser falls back to
loading from data/chunks/tier-3/<slug>.jsonl produced by the manual
transcription script (Phase 4.3.a path). Res. 15/2024 stays on the
manual path; Res. 4/2023 moves to the real parser; Res. 1/2021 and
2/2022 are still gated (config not yet built).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from rag_leis.chunks import Chunk

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIER3_CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks" / "tier-3"
TIER3_RAW_DIR = PROJECT_ROOT / "data" / "raw" / "tier-3"


# ----------------------------------------------------------------------------
# Per-document registry — page ranges, titles, etc.
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class AnpdParseConfig:
    pdf_filename: str
    # 1-indexed inclusive page range of the regulamento in the bundle
    page_range: tuple[int, int]
    title: str
    # Slug used for JSONL output filename
    output_slug: str


# Each entry is a URN → config map. ANPD bundles vary in length; the
# regulamento section is found by manual inspection once per doc.
ANPD_PARSE_CONFIG: dict[str, AnpdParseConfig] = {
    "urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2023-02-24;4": AnpdParseConfig(
        pdf_filename="res_4_2023_part1.pdf",
        page_range=(98, 108),
        title=(
            "Resolução CD/ANPD nº 4/2023 — Regulamento de Dosimetria e "
            "Aplicação de Sanções Administrativas"
        ),
        output_slug="anpd_res_4_2023",
    ),
}


# ----------------------------------------------------------------------------
# Cleanup helpers
# ----------------------------------------------------------------------------


# SEI footer attached to every page of the bundle:
# "Anexo [030]-3333593_Minuta (0016460) SEI 00261.000358/2021-02 / pg. 43"
_SEI_FOOTER_RE = re.compile(
    r"Anexo \[\d+\]-?\d+_\S+ \(\d+\) SEI \d+\.\d+/\d+-\d+\s*/?\s*pg\.\s*\d+\s*$",
    re.MULTILINE,
)

# "aqueleque" → "aquele que" (single missing space we observed)
# Conservative list — only the cases proven in the source.
_MISSING_SPACE_FIXES = [
    (re.compile(r"\baqueleque\b"), "aquele que"),
    # § number followed immediately by "e" without space, e.g. "§§2ºe 3º"
    (re.compile(r"(\d+º)e\s"), r"\1 e "),
]


def _clean_page_text(text: str) -> str:
    """Apply per-page text cleanup. Strips the SEI footer that appears
    on every bundle page; fixes the few observed missing-space artifacts.

    Whitespace normalization is deferred to the chunk-building stage
    (line breaks carry structural meaning at the page level).
    """
    text = _SEI_FOOTER_RE.sub("", text)
    for pattern, repl in _MISSING_SPACE_FIXES:
        text = pattern.sub(repl, text)
    return text


# ----------------------------------------------------------------------------
# Structure detection — LCP-95 patterns
# ----------------------------------------------------------------------------

# CAPÍTULO I, II, III, ...  (line by itself, ALL CAPS body title typically on next line)
_CAPITULO_RE = re.compile(r"^CAPÍTULO\s+([IVXLCDM]+)\s*$")
# Seção I, II, III ... (Title case)
_SECAO_RE = re.compile(r"^Seção\s+([IVXLCDM]+)\s*$")
# Art. N or Art. N-A (with optional ordinal indicator)
_ARTIGO_RE = re.compile(r"^Art\.\s*(\d+(?:-[A-Z])?)\s*[º°]?\s*(.*)$")
# § N — note pdfplumber gives "§ 1º" with space; also "§1º"
_PARAGRAFO_RE = re.compile(r"^§\s*(\d+)\s*[º°]?\s*(.*)$")
# Inciso: Roman + " - " + text
_INCISO_RE = re.compile(r"^([IVXLCDM]+)\s*-\s*(.*)$")
# Alínea: letter + ") " + text
_ALINEA_RE = re.compile(r"^([a-z])\)\s*(.*)$")


_ROMAN_MAP = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
    "XXI": 21, "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25,
    "XXVI": 26, "XXVII": 27, "XXVIII": 28, "XXIX": 29, "XXX": 30,
}


# ----------------------------------------------------------------------------
# Parser body
# ----------------------------------------------------------------------------


class AnpdPdfParser:
    """Phase 4.3.b: real pdfplumber-backed parser.

    Falls back to JSONL re-loading for URNs not in ANPD_PARSE_CONFIG
    (preserves the Phase 4.3.a path for Res. 15/2024 manual transcription).
    """

    name: str = "anpd-pdf-v1"

    def parse(self, document_urn: str, source: str) -> list[Chunk]:
        """`source` is currently ignored — the PDF path is resolved from
        ANPD_PARSE_CONFIG by URN. Reserved for future use (Phase 7+ may
        pass PDF bytes for streaming/temp-file scenarios)."""
        del source  # explicit unused

        config = ANPD_PARSE_CONFIG.get(document_urn)
        if config is None:
            # Fallback: JSONL-only path (Phase 4.3.a) for URNs not yet
            # configured for real parsing.
            return self._load_from_jsonl(document_urn)

        pdf_path = TIER3_RAW_DIR / config.pdf_filename
        if not pdf_path.exists():
            raise FileNotFoundError(
                f"PDF not found for {document_urn!r}: {pdf_path}. "
                f"Run fetch step or check ANPD_PARSE_CONFIG."
            )

        pdf_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        raw_text = self._extract_pages(pdf_path, config.page_range)
        cleaned = _clean_page_text(raw_text)
        return self._build_chunks(
            cleaned, document_urn, config, pdf_sha256,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pages(pdf_path: Path, page_range: tuple[int, int]) -> str:
        """Concatenate text from `page_range` (1-indexed inclusive)."""
        start, end = page_range
        chunks: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for i in range(start - 1, end):
                if i >= len(pdf.pages):
                    break
                page_text = pdf.pages[i].extract_text() or ""
                chunks.append(page_text)
        return "\n".join(chunks)

    # ------------------------------------------------------------------

    def _build_chunks(
        self,
        text: str,
        document_urn: str,
        config: AnpdParseConfig,
        pdf_sha256: str,
    ) -> list[Chunk]:
        """Parse cleaned text into LCP-95 hierarchy.

        State machine: walk line-by-line, recognizing structural markers
        (CAPÍTULO/Seção/Art./§/Inciso/Alínea). Body text gets appended to
        the current open atom until the next marker fires.
        """
        chunks: list[Chunk] = []
        lines = text.split("\n")

        # Current nav state
        cap_label: str | None = None
        cap_title: str | None = None
        sec_label: str | None = None
        sec_title: str | None = None
        nav_title = config.title

        # Current open atom we're accumulating into
        open_partition: str | None = None
        open_kind: str | None = None
        open_label: str | None = None
        open_text: list[str] = []
        open_parent: str | None = None

        # Counters for nested elements
        cur_article: str | None = None
        cur_par: str | None = None  # most recent §
        cur_inc_under: str | None = None  # parent of current inciso
        cur_alinea_under: str | None = None  # parent of current alínea (sticky)

        def flush_open() -> None:
            """Emit the currently-open atom as a Chunk and reset."""
            nonlocal open_partition, open_kind, open_label, open_text, open_parent
            if open_partition is None:
                return
            full_text = " ".join(_normalize_text(s) for s in open_text).strip()
            if not full_text:
                # Don't emit empty atoms (avoids stub chunks for headers
                # that had no body text yet)
                open_partition = open_kind = open_label = open_parent = None
                open_text = []
                return
            nav = {"titulo": nav_title}
            if cap_label and cap_title:
                nav["capitulo"] = f"CAPÍTULO {cap_label} — {cap_title}"
            if sec_label and sec_title:
                nav["secao"] = f"Seção {sec_label} — {sec_title}"
            chunks.append(
                Chunk(
                    document_urn=document_urn,
                    partition=open_partition,
                    kind=open_kind,  # type: ignore[arg-type]
                    label=open_label or "",
                    text=full_text,
                    parent_partition=open_parent,
                    nav=nav,
                    notes=[],
                    is_revoked=False,
                )
            )
            open_partition = open_kind = open_label = open_parent = None
            open_text = []

        # Pre-walk: skip until we hit "CAPÍTULO I" (start of regulamento body)
        i = 0
        while i < len(lines):
            if _CAPITULO_RE.match(lines[i].strip()):
                break
            i += 1

        # If never hit a CAPÍTULO, abort — config page range is wrong
        if i >= len(lines):
            raise ValueError(
                f"No CAPÍTULO marker found in extracted text for {document_urn!r}. "
                f"page_range={config.page_range} may be incorrect."
            )

        # Main walk
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            if not line:
                continue

            # Skip the ANEXO header line that sometimes appears mid-extract
            if line == "ANEXO" or "REGULAMENTO DE DOSIMETRIA" in line:
                continue

            m_cap = _CAPITULO_RE.match(line)
            if m_cap:
                flush_open()
                cap_label = m_cap.group(1)
                # Next non-empty line is the capítulo title (ALL CAPS heading)
                while i < len(lines) and not lines[i].strip():
                    i += 1
                if i < len(lines):
                    cap_title = lines[i].strip()
                    i += 1
                # Capítulo resets seção
                sec_label = sec_title = None
                continue

            m_sec = _SECAO_RE.match(line)
            if m_sec:
                flush_open()
                sec_label = m_sec.group(1)
                while i < len(lines) and not lines[i].strip():
                    i += 1
                if i < len(lines):
                    sec_title = lines[i].strip()
                    i += 1
                continue

            m_art = _ARTIGO_RE.match(line)
            if m_art:
                flush_open()
                num = m_art.group(1)
                rest = m_art.group(2).strip()
                cur_article = f"art{num.lower()}"
                cur_par = None
                cur_inc_under = cur_article
                cur_alinea_under = None
                open_partition = cur_article
                open_kind = "artigo"
                open_label = f"Art. {num}"
                open_parent = None
                if rest:
                    open_text.append(rest)
                continue

            m_par = _PARAGRAFO_RE.match(line)
            if m_par and cur_article:
                flush_open()
                par_num = m_par.group(1)
                rest = m_par.group(2).strip()
                cur_par = f"{cur_article};par{par_num}"
                cur_inc_under = cur_par
                cur_alinea_under = None
                open_partition = cur_par
                open_kind = "paragrafo"
                open_label = f"§ {par_num}º"
                open_parent = cur_article
                if rest:
                    open_text.append(rest)
                continue

            m_inc = _INCISO_RE.match(line)
            if m_inc and cur_inc_under:
                # Filter out Roman numerals that aren't actually article incisos
                # (capítulo / seção headers won't reach here because they're
                # captured above)
                roman = m_inc.group(1)
                if roman not in _ROMAN_MAP:
                    open_text.append(line)
                    continue
                flush_open()
                rest = m_inc.group(2).strip()
                num = _ROMAN_MAP[roman]
                open_partition = f"{cur_inc_under};inc{num}"
                open_kind = "inciso"
                open_label = roman
                open_parent = cur_inc_under
                # The current inciso becomes the parent for any alíneas
                # that follow until the next inciso/§/art change
                cur_alinea_under = open_partition
                if rest:
                    open_text.append(rest)
                continue

            m_ali = _ALINEA_RE.match(line)
            if m_ali and cur_alinea_under:
                flush_open()
                letter = m_ali.group(1)
                rest = m_ali.group(2).strip()
                # Alíneas hang off the most recent inciso (cur_alinea_under),
                # which is set when an inciso fires and reset on § / Art changes.
                open_partition = f"{cur_alinea_under};ali-{letter}"
                open_kind = "alinea"
                open_label = letter
                open_parent = cur_alinea_under
                if rest:
                    open_text.append(rest)
                continue

            # Plain continuation of the current open atom
            if open_partition:
                open_text.append(line)

        flush_open()
        return chunks

    # ------------------------------------------------------------------

    @staticmethod
    def _load_from_jsonl(document_urn: str) -> list[Chunk]:
        """Phase 4.3.a fallback: read pre-produced JSONL.

        Used for URNs not in ANPD_PARSE_CONFIG (e.g., Res. 15/2024 produced
        via manual Claude Code transcription)."""
        # Filename convention from build_res_15_2024.py:
        # urn = `...:resolucao.cd:YYYY-MM-DD;N` → file = `anpd_res_N_YYYY.jsonl`
        try:
            tail = document_urn.split(":")[-1]
            date_part, num_part = tail.split(";")
            year = date_part.split("-")[0]
            jsonl_path = TIER3_CHUNKS_DIR / f"anpd_res_{num_part}_{year}.jsonl"
        except (ValueError, IndexError) as e:
            raise ValueError(
                f"Cannot derive JSONL filename from URN: {document_urn!r}"
            ) from e

        if not jsonl_path.exists():
            raise FileNotFoundError(
                f"No tier-3 source for {document_urn!r}. "
                f"Either add it to ANPD_PARSE_CONFIG (for real parsing) or "
                f"run the manual transcription script for "
                f"{jsonl_path.name!r}."
            )

        chunks: list[Chunk] = []
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                chunks.append(
                    Chunk(
                        document_urn=obj["document_urn"],
                        partition=obj["partition"],
                        kind=obj["kind"],
                        label=obj["label"],
                        text=obj["text"],
                        parent_partition=obj.get("parent_partition"),
                        nav=obj.get("nav", {}),
                        notes=obj.get("notes", []),
                        is_revoked=obj.get("is_revoked", False),
                    )
                )
        return chunks


def _normalize_text(s: str) -> str:
    """Collapse internal whitespace, strip leading/trailing."""
    return re.sub(r"\s+", " ", s).strip()


def write_jsonl_with_audit(
    chunks: list[Chunk],
    document_urn: str,
    output_path: Path,
    pdf_sha256: str,
    parser_version: str = "pdfplumber-v1",
) -> None:
    """Write chunks to JSONL with Phase 4.3.b audit-metadata fields.

    These fields distinguish parser-produced chunks (`source="pdfplumber-v1"`)
    from Phase 4.3.a manual transcription chunks (`source="claude-code-..."`).
    Phase 4.3.b's DIFF script (future) compares the two for documents that
    have both paths.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            payload = {
                "document_urn": c.document_urn,
                "partition": c.partition,
                "kind": c.kind,
                "label": c.label,
                "text": c.text,
                "parent_partition": c.parent_partition,
                "nav": c.nav,
                "notes": c.notes,
                "is_revoked": c.is_revoked,
                "urn": c.urn,
                # Phase 4.3.b audit metadata
                "source": parser_version,
                "source_pdf_sha256": pdf_sha256,
                "ingestion_method": "pdfplumber-extraction",
                "ingestion_provenance": (
                    "rag_leis.parsers.anpd_pdf.AnpdPdfParser, "
                    "ANPD_PARSE_CONFIG-driven page-range extraction"
                ),
            }
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

