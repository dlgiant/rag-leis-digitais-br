from __future__ import annotations

import html as html_module
import re
from collections.abc import Iterator

from rag_leis.chunks import Chunk

_ARTIGO_P = re.compile(
    r"<p\b[^>]*>(.*?)</p>",
    re.DOTALL | re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_NBSP = re.compile(r"\xa0")

_ARTIGO_HEAD = re.compile(
    r"^\s*Art\.\s*(\d+(?:-[A-Z])?)\s*[º°.]?\s*",
    re.IGNORECASE,
)
_PARAGRAFO_HEAD = re.compile(r"^\s*§\s*(\d+)\s*[º°.]?\s*", re.IGNORECASE)
_PAR_UNICO_HEAD = re.compile(r"^\s*Par[áa]grafo\s+[úu]nico\s*[.:]?\s*", re.IGNORECASE)
_INCISO_HEAD = re.compile(
    "^\\s*([IVXLCDM]+)\\s*[-\u2013]\\s*",
    re.IGNORECASE,
)
_ALINEA_HEAD = re.compile(r"^\s*([a-z])\)\s*", re.IGNORECASE)
_ITEM_HEAD = re.compile(r"^\s*(\d+)\.\s+")


def _extract_artigo_paragraphs(html: str) -> Iterator[str]:
    for m in _ARTIGO_P.finditer(html):
        raw = m.group(1)
        text = _TAG.sub("", raw)
        text = html_module.unescape(text)
        text = _NBSP.sub(" ", text)
        text = _WS.sub(" ", text).strip()
        if text:
            yield text


def _roman_to_int(roman: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in roman.upper()[::-1]:
        v = values[ch]
        total += -v if v < prev else v
        prev = v
    return total


def parse(document_urn: str, html: str) -> list[Chunk]:
    raw: list[Chunk] = []
    current_artigo: str | None = None
    current_inciso_parent: str | None = None
    current_inciso: str | None = None
    current_alinea: str | None = None

    for text in _extract_artigo_paragraphs(html):
        m_art = _ARTIGO_HEAD.match(text)
        if m_art:
            art_num = m_art.group(1)
            partition = f"art{art_num.lower()}"
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="artigo",
                    label=f"Art. {art_num}",
                    text=text[m_art.end() :].strip(),
                    parent_partition=None,
                )
            )
            current_artigo = partition
            current_inciso_parent = partition
            current_inciso = None
            current_alinea = None
            continue

        m_par = _PARAGRAFO_HEAD.match(text)
        if m_par and current_artigo is not None:
            par_num = int(m_par.group(1))
            partition = f"{current_artigo};par{par_num}"
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="paragrafo",
                    label=f"§ {par_num}º",
                    text=text[m_par.end() :].strip(),
                    parent_partition=current_artigo,
                )
            )
            current_inciso_parent = partition
            current_inciso = None
            current_alinea = None
            continue

        m_par_u = _PAR_UNICO_HEAD.match(text)
        if m_par_u and current_artigo is not None:
            partition = f"{current_artigo};par1"
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="paragrafo",
                    label="Parágrafo único",
                    text=text[m_par_u.end() :].strip(),
                    parent_partition=current_artigo,
                )
            )
            current_inciso_parent = partition
            current_inciso = None
            current_alinea = None
            continue

        m_inc = _INCISO_HEAD.match(text)
        if m_inc and current_inciso_parent is not None:
            roman = m_inc.group(1).upper()
            inc_num = _roman_to_int(roman)
            partition = f"{current_inciso_parent};inc{inc_num}"
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="inciso",
                    label=roman,
                    text=text[m_inc.end() :].strip(),
                    parent_partition=current_inciso_parent,
                )
            )
            current_inciso = partition
            current_alinea = None
            continue

        m_ali = _ALINEA_HEAD.match(text)
        if m_ali and current_inciso is not None:
            letter = m_ali.group(1).lower()
            partition = f"{current_inciso};ali-{letter}"
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="alinea",
                    label=letter,
                    text=text[m_ali.end() :].strip(),
                    parent_partition=current_inciso,
                )
            )
            current_alinea = partition
            continue

        m_item = _ITEM_HEAD.match(text)
        if m_item and current_alinea is not None:
            item_num = int(m_item.group(1))
            partition = f"{current_alinea};item{item_num}"
            raw.append(
                Chunk(
                    document_urn=document_urn,
                    partition=partition,
                    kind="item",
                    label=str(item_num),
                    text=text[m_item.end() :].strip(),
                    parent_partition=current_alinea,
                )
            )
            continue

    return _dedup_keep_last(raw)


def _dedup_keep_last(chunks: list[Chunk]) -> list[Chunk]:
    by_partition: dict[str, Chunk] = {}
    for c in chunks:
        by_partition[c.partition] = c
    return list(by_partition.values())
