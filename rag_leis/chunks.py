from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ChunkKind = Literal["artigo", "paragrafo", "inciso", "alinea", "item"]


@dataclass(frozen=True)
class Chunk:
    document_urn: str
    partition: str
    kind: ChunkKind
    label: str
    text: str
    parent_partition: str | None
    nav: dict[str, str] = field(default_factory=dict)

    @property
    def urn(self) -> str:
        return f"{self.document_urn}~{self.partition}"
