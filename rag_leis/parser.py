from __future__ import annotations

import html as html_module
import re

from rag_leis.chunks import Chunk

_ARTIGO_P = re.compile(
    r"<p\b[^>]*>(.*?)</p>",
    re.DOTALL | re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_NBSP = re.compile(r"\xa0")
_INNERMOST_BLOCKQUOTE = re.compile(
    r"<blockquote\b[^>]*>((?:(?!<blockquote\b).)*?)</blockquote>",
    re.DOTALL | re.IGNORECASE,
)
_ART_REFERENCE = re.compile(r"\bArt\.\s*\d+", re.IGNORECASE)

_ARTIGO_HEAD = re.compile(
    # Matches "Art. 1", "Art 1" (no period — Planalto inconsistency in CP arts
    # 187-189), "Art. 1º", "Art. 1º.", "Art. 154-A", etc.
    # - `\.?` after "Art" makes the period optional.
    # - Trailing `[º°]?\s*\.?` consumes optional ordinal marker AND optional final
    #   period — fixes leading "." remnant on CF ADCT art1.
    r"^\s*Art\.?\s*(\d+(?:-[A-Z])?)\s*[º°]?\s*\.?\s*",
    re.IGNORECASE,
)
_ARTIGO_NUM_CONTINUATION = re.compile(r"^(\d+)\.\s")
# Captures both `§ 2º` (number) and `§ 2º-A` (Lei 14.155/21-style sub-§).
# Group 1: integer; Group 2: optional uppercase letter suffix.
#
# Without the suffix capture the previous regex collapsed §2, §2-A, §2-B into
# the same partition `par2`, then `_dedup_keep_last` discarded all but the
# last — silently losing the sub-§ chunks (CP art.171 §2-A, art.155 §4-B etc).
#
# CRITICAL: the suffix lookahead `(?=[.\s,;:]|$)` distinguishes a real sub-§
# letter (`§ 2º-A.`) from Planalto's `§ Nº - Texto...` separator pattern
# (where the hyphen is followed by a regular sentence — "Se o criminoso é
# primário..." — and the first letter must NOT be captured as a suffix).
_PARAGRAFO_HEAD = re.compile(
    r"^\s*§\s*(\d+)\s*"                    # § num
    r"[º°]?\s*"                             # optional ordinal marker
    r"(?:[-–]([A-Z])(?=[.\s,;:]|$))?"      # optional letter suffix: hyphen and
                                            # letter must be ADJACENT (no space)
                                            # — distinguishes real Lei 14.155-style
                                            # `§ 2º-A.` from Planalto's separator
                                            # `§ 2º - O presidente`.
    r"\s*[-–]?\s*"                          # eat Planalto separator hyphen
                                            # `§ Nº - Texto…` when no suffix matched
    r"\.?\s*",                              # optional trailing period
    re.IGNORECASE,
)
_PAR_UNICO_HEAD = re.compile(r"^\s*Par[áa]grafo\s+[úu]nico\s*[.:]?\s*", re.IGNORECASE)
_INCISO_HEAD = re.compile(
    "^\\s*([IVXLCDM]+)\\s*[-\u2013]\\s*",
    re.IGNORECASE,
)
_ALINEA_HEAD = re.compile(r"^\s*([a-z])\)\s*", re.IGNORECASE)
_ITEM_HEAD = re.compile(r"^\s*(\d+)\.\s+")

_NAV_HEAD = re.compile(
    r"^\s*(LIVRO|PARTE|T[IÍ]TULO|CAP[IÍ]TULO|SUBSE[CÇ][AÃ]O|SE[CÇ][AÃ]O)\s+(.+)$",
    re.IGNORECASE,
)
_NAV_NUMBER_ONLY = re.compile(r"^[IVXLCDM]+\s*$|^[A-Z][A-Z\s]*$", re.IGNORECASE)

_LEVEL_MAP = {
    "livro": "livro",
    "parte": "parte",
    "título": "titulo",
    "titulo": "titulo",
    "capítulo": "capitulo",
    "capitulo": "capitulo",
    "seção": "secao",
    "secao": "secao",
    "seçao": "secao",
    "subseção": "subsecao",
    "subsecao": "subsecao",
}
_HIERARCHY = ["livro", "parte", "titulo", "capitulo", "secao", "subsecao"]

_ADCT_MARKER = re.compile(
    r"^\s*Ato\s+das\s+Disposi[çc][õo]es\s+Constitucionais\s+Transit[óo]rias",
    re.IGNORECASE,
)

_LEGAL_NOTE = re.compile(
    r"\(\s*(?:Reda[çc][ãa]o\s+dada"
    r"|Inclu[íi]d[oa]"
    r"|Revogad[oa]"
    r"|Renumerad[oa]"
    r"|Vide"
    r"|Vig[êe]ncia"
    r"|Regulamento"
    r"|Produ[çc][ãa]o\s+de\s+efeit[oa])"
    r"\b[^()]*\)",
    re.IGNORECASE,
)


def _strip_amendment_blockquotes(html: str) -> str:
    def maybe_strip(m: re.Match[str]) -> str:
        inner_plain = _TAG.sub(" ", m.group(1))
        if _ART_REFERENCE.search(inner_plain):
            return ""
        return m.group(0)

    while True:
        new_html = _INNERMOST_BLOCKQUOTE.sub(maybe_strip, html)
        if new_html == html:
            return html
        html = new_html


_BR_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _extract_paragraphs(html: str) -> list[str]:
    html = _strip_amendment_blockquotes(html)
    out: list[str] = []
    for m in _ARTIGO_P.finditer(html):
        raw = m.group(1)
        # Break on <br> tags BEFORE stripping all tags. CP (Decreto-Lei 2848)
        # packs multiple artigos + their Nomen iuris into a single <p>, separated
        # only by <br>; without this split the title of artN+1 ends up appended
        # to the text of artN.
        for chunk in _BR_TAG.split(raw):
            text = _TAG.sub("", chunk)
            text = html_module.unescape(text)
            text = _NBSP.sub(" ", text)
            text = _WS.sub(" ", text).strip()
            if text:
                out.extend(_split_embedded_artigos(text))
    return out


# Planalto occasionally emits malformed HTML where a <p> is closed with </div>,
# or stacks a "Nomen iuris" title in the same <p> as the artigo head. Symptoms:
#   1. Paragraph starts with "Parágrafo único." but contains embedded "Art. N." —
#      CF ADCT art119/120 boundary.
#   2. Paragraph starts with the crime name ("Violação de privilégio…") and the
#      artigo head ("Art 187.") follows in the same <p> — CP arts 187-194.
#
# Split heuristic: any "Art." or "Art" (period optional, Planalto inconsistency)
# preceded by a word char, `.`, or `)` — i.e., NOT at the start of the paragraph
# — is treated as a missed paragraph boundary. Lowercase `art. N` cross-references
# like "nos termos do art. 89" don't match because we require capital `A`.
_INTERNAL_ARTIGO_BREAK = re.compile(r"(?<=[\w.)])\s+(?=Art\.?\s+\d+[º°]?\.?)")


def _split_embedded_artigos(text: str) -> list[str]:
    """Split a paragraph at boundaries where a new artigo head appears mid-text."""
    parts = _INTERNAL_ARTIGO_BREAK.split(text)
    return [p.strip() for p in parts if p.strip()]


def _roman_to_int(roman: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in roman.upper()[::-1]:
        v = values[ch]
        total += -v if v < prev else v
        prev = v
    return total


def _level_key(keyword: str) -> str | None:
    return _LEVEL_MAP.get(keyword.lower())


def _reset_below(nav: dict[str, str], level: str) -> None:
    idx = _HIERARCHY.index(level)
    for lower in _HIERARCHY[idx + 1 :]:
        nav.pop(lower, None)


def _strip_notes(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []

    def capture(m: re.Match[str]) -> str:
        notes.append(m.group(0))
        return " "

    cleaned = _LEGAL_NOTE.sub(capture, text)
    cleaned = _WS.sub(" ", cleaned).strip()
    return cleaned, notes


def _is_legal_note_paragraph(text: str) -> bool:
    cleaned, _ = _strip_notes(text)
    return not cleaned


def _looks_like_section_title(text: str) -> bool:
    if len(text) > 200:
        return False
    return not any(
        r.match(text)
        for r in (
            _ARTIGO_HEAD,
            _PARAGRAFO_HEAD,
            _PAR_UNICO_HEAD,
            _INCISO_HEAD,
            _ALINEA_HEAD,
            _ITEM_HEAD,
            _NAV_HEAD,
        )
    )


def parse(document_urn: str, html: str) -> list[Chunk]:
    paragraphs = _extract_paragraphs(html)
    raw: list[Chunk] = []
    current_artigo: str | None = None
    current_inciso_parent: str | None = None
    current_inciso: str | None = None
    current_alinea: str | None = None
    nav: dict[str, str] = {}
    partition_prefix = ""

    i = 0
    while i < len(paragraphs):
        text = paragraphs[i]

        if (
            _ADCT_MARKER.match(text)
            and len(text) < 200
            and current_artigo is not None
        ):
            partition_prefix = "adct"
            nav = {"parte": "Ato das Disposições Constitucionais Transitórias"}
            current_artigo = None
            current_inciso_parent = None
            current_inciso = None
            current_alinea = None
            i += 1
            continue

        m_nav = _NAV_HEAD.match(text)
        if m_nav and len(text) < 120:
            level = _level_key(m_nav.group(1))
            if level is not None:
                body, _ = _strip_notes(m_nav.group(2).strip())
                if _NAV_NUMBER_ONLY.match(body):
                    j = i + 1
                    while j < len(paragraphs) and _is_legal_note_paragraph(
                        paragraphs[j]
                    ):
                        j += 1
                    if j < len(paragraphs) and _looks_like_section_title(
                        paragraphs[j]
                    ):
                        title, _ = _strip_notes(paragraphs[j])
                        nav[level] = f"{body} - {title}" if title else body
                        _reset_below(nav, level)
                        i = j + 1
                        continue
                nav[level] = body
                _reset_below(nav, level)
                i += 1
                continue

        m_art = _ARTIGO_HEAD.match(text)
        if m_art:
            art_num = m_art.group(1)
            remainder = text[m_art.end() :]
            m_continued = _ARTIGO_NUM_CONTINUATION.match(remainder)
            if m_continued:
                art_num = art_num + m_continued.group(1)
                remainder = remainder[m_continued.end() :]
            base_part = f"art{art_num.lower()}"
            partition = f"{partition_prefix};{base_part}" if partition_prefix else base_part
            cleaned, notes = _strip_notes(remainder.strip())
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="artigo",
                    label=f"Art. {art_num}",
                    text=cleaned,
                    parent_partition=None,
                    nav=dict(nav),
                    notes=notes,
                )
            )
            current_artigo = partition
            current_inciso_parent = partition
            current_inciso = None
            current_alinea = None
            i += 1
            continue

        m_par = _PARAGRAFO_HEAD.match(text)
        if m_par and current_artigo is not None:
            par_num = int(m_par.group(1))
            par_suffix = m_par.group(2)
            if par_suffix:
                partition = f"{current_artigo};par{par_num}-{par_suffix.lower()}"
                label = f"§ {par_num}º-{par_suffix.upper()}"
            else:
                partition = f"{current_artigo};par{par_num}"
                label = f"§ {par_num}º"
            cleaned, notes = _strip_notes(text[m_par.end() :].strip())
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="paragrafo",
                    label=label,
                    text=cleaned,
                    parent_partition=current_artigo,
                    nav=dict(nav),
                    notes=notes,
                )
            )
            current_inciso_parent = partition
            current_inciso = None
            current_alinea = None
            i += 1
            continue

        m_par_u = _PAR_UNICO_HEAD.match(text)
        if m_par_u and current_artigo is not None:
            partition = f"{current_artigo};par1"
            cleaned, notes = _strip_notes(text[m_par_u.end() :].strip())
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="paragrafo",
                    label="Parágrafo único",
                    text=cleaned,
                    parent_partition=current_artigo,
                    nav=dict(nav),
                    notes=notes,
                )
            )
            current_inciso_parent = partition
            current_inciso = None
            current_alinea = None
            i += 1
            continue

        m_inc = _INCISO_HEAD.match(text)
        if m_inc and current_inciso_parent is not None:
            roman = m_inc.group(1).upper()
            inc_num = _roman_to_int(roman)
            partition = f"{current_inciso_parent};inc{inc_num}"
            cleaned, notes = _strip_notes(text[m_inc.end() :].strip())
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="inciso",
                    label=roman,
                    text=cleaned,
                    parent_partition=current_inciso_parent,
                    nav=dict(nav),
                    notes=notes,
                )
            )
            current_inciso = partition
            current_alinea = None
            i += 1
            continue

        m_ali = _ALINEA_HEAD.match(text)
        if m_ali and current_inciso is not None:
            letter = m_ali.group(1).lower()
            partition = f"{current_inciso};ali-{letter}"
            cleaned, notes = _strip_notes(text[m_ali.end() :].strip())
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="alinea",
                    label=letter,
                    text=cleaned,
                    parent_partition=current_inciso,
                    nav=dict(nav),
                    notes=notes,
                )
            )
            current_alinea = partition
            i += 1
            continue

        m_item = _ITEM_HEAD.match(text)
        if m_item and current_alinea is not None:
            item_num = int(m_item.group(1))
            partition = f"{current_alinea};item{item_num}"
            cleaned, notes = _strip_notes(text[m_item.end() :].strip())
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="item",
                    label=str(item_num),
                    text=cleaned,
                    parent_partition=current_alinea,
                    nav=dict(nav),
                    notes=notes,
                )
            )
            i += 1
            continue

        i += 1

    return _mark_revoked(_dedup_keep_last(raw))


class PlanaltoHtmlParser:
    """Parses Planalto.gov.br HTML pages (Lei / Decreto / Constituição).

    Implements the `Parser` protocol from rag_leis.chunks. Wraps the
    module-level `parse()` function so the regex-heavy implementation can stay
    as procedural code while the call site uses a polymorphic interface.

    Use this when other parsers exist alongside (e.g. AnpdPdfParser) and the
    caller wants to dispatch based on URN scheme or source format.
    """

    name: str = "planalto-html"

    def parse(self, document_urn: str, source: str) -> list[Chunk]:
        return parse(document_urn, source)


def _mark_revoked(chunks: list[Chunk]) -> list[Chunk]:
    """Set Chunk.is_revoked for placeholder chunks (revogado/vetado/suprimido/stub).

    Run after dedup so the flag reflects the chunk that survives. Single pass —
    avoids touching the 6 Chunk() construction sites individually.
    """
    from dataclasses import replace

    from rag_leis.chunks import is_revoked_text

    return [replace(c, is_revoked=is_revoked_text(c.text)) for c in chunks]


def _dedup_keep_last(chunks: list[Chunk]) -> list[Chunk]:
    """Keep the last chunk for each partition slug.

    Dedup firing means the parser emitted >1 chunk with the same partition
    URN — typically a sign of a regex bug or unexpected HTML shape. Logs a
    warning per duplicate so silent bugs surface during corpus expansion.
    """
    import logging

    log = logging.getLogger(__name__)
    seen: dict[str, Chunk] = {}
    dupes: list[tuple[str, str]] = []  # (partition, dropped_label)
    for c in chunks:
        if c.partition in seen:
            dupes.append((c.partition, seen[c.partition].label))
        seen[c.partition] = c
    if dupes:
        log.warning(
            "dedup_keep_last fired on %d duplicates (kept last): %s",
            len(dupes),
            ", ".join(f"{p}={lbl!r}" for p, lbl in dupes[:5])
            + ("..." if len(dupes) > 5 else ""),
        )
    return list(seen.values())
