from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

ChunkKind = Literal["artigo", "paragrafo", "inciso", "alinea", "item"]


class Parser(Protocol):
    """Source-agnostic parser interface.

    A parser takes a document's canonical URN and its raw source (HTML, PDF
    text, JSON, etc.) and returns a flat list of Chunks. Concrete impls so
    far:
      - `PlanaltoHtmlParser` (Lei/Decreto/Constituição HTML from Planalto)
      - planned: `AnpdPdfParser` (ANPD resoluções as PDFs)

    Implementations should respect the LCP-95 hierarchy where applicable and
    set `is_revoked` on placeholder chunks at emission time.
    """

    name: str

    def parse(self, document_urn: str, source: str) -> list["Chunk"]: ...


# Placeholder patterns for chunks with no operative text: revogados, vetados,
# suprimidos, or empty stubs. Detected at parse time so load_chunks doesn't
# rely on a brittle text-length proxy.
_PLACEHOLDER_RE = re.compile(
    r"^\s*[.;]?\s*$"                                # only punctuation
    r"|^\s*\(Vetad[ao]\)\.?\s*[.;]?\s*$"            # (Vetado)
    r"|^\s*\(Revogad[ao][^)]*\)\.?\s*[.;]?\s*$"     # (Revogado pela Lei X)
    r"|^\s*\(Suprimid[ao][^)]*\)\.?\s*[.;]?\s*$"    # (Suprimido)
    r"|^\s*Revogado pela",                          # starts with 'Revogado pela'
    re.IGNORECASE,
)


def is_revoked_text(text: str) -> bool:
    """True if `text` is a placeholder (revogado / vetado / suprimido / stub).

    Used by parsers when emitting chunks and by load_chunks as a fallback for
    JSONL written before the flag existed.
    """
    return bool(_PLACEHOLDER_RE.match(text))


@dataclass(frozen=True)
class Chunk:
    document_urn: str
    partition: str
    kind: ChunkKind
    label: str
    text: str
    parent_partition: str | None
    nav: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    is_revoked: bool = False  # placeholder content (revogado/vetado/suprimido/stub)

    @property
    def urn(self) -> str:
        return f"{self.document_urn}~{self.partition}"
