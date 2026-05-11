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
    r"^\s*Art\.\s*(\d+(?:-[A-Z])?)\s*[º°.]?\s*",
    re.IGNORECASE,
)
_ARTIGO_NUM_CONTINUATION = re.compile(r"^(\d+)\.\s")
_PARAGRAFO_HEAD = re.compile(r"^\s*§\s*(\d+)\s*[º°.]?\s*", re.IGNORECASE)
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


def _extract_paragraphs(html: str) -> list[str]:
    html = _strip_amendment_blockquotes(html)
    out: list[str] = []
    for m in _ARTIGO_P.finditer(html):
        raw = m.group(1)
        text = _TAG.sub("", raw)
        text = html_module.unescape(text)
        text = _NBSP.sub(" ", text)
        text = _WS.sub(" ", text).strip()
        if text:
            out.append(text)
    return out


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
            partition = f"{current_artigo};par{par_num}"
            cleaned, notes = _strip_notes(text[m_par.end() :].strip())
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="paragrafo",
                    label=f"§ {par_num}º",
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

    return _dedup_keep_last(raw)


def _dedup_keep_last(chunks: list[Chunk]) -> list[Chunk]:
    by_partition: dict[str, Chunk] = {}
    for c in chunks:
        by_partition[c.partition] = c
    return list(by_partition.values())
