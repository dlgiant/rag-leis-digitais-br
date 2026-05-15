"""Stub PDF parser for ANPD resoluções (Phase 4.3.a).

This is the v0 hybrid path documented in study/post-review-plan.md Phase 4.3:

  4.3.a (now): Claude Code reads each ANPD PDF and produces structured
               JSONL in data/chunks/tier-3/. Each chunk carries audit
               metadata (source, source_pdf_sha256, ingestion_method) so
               the future parser's output can be DIFF'd against this v0.
  4.3.b (gated before Phase 8 production deploy): real pdfplumber-backed
               parser. Same Parser protocol; same JSONL output. Source
               metadata flips from "claude-code-*" to "pdfplumber-vN".

For 4.3.a, this class only needs to satisfy the `Parser` protocol so
`parse_all_tier --tier 3` works end-to-end. The "parsing" is just
re-reading the pre-produced JSONL files (the actual structured content
was produced by Claude Code, encoded in
`rag_leis/tier3_ingest/build_res_*.py` scripts).

This separation gives the project:
  1. Production-grade reproducibility: re-running parse_all_tier on the
     existing JSONL produces byte-identical output
  2. Auditable provenance: every chunk has source + ingestion_method
     so consumers can distinguish Claude-Code v0 from pdfplumber-v1
  3. A natural place for 4.3.b to plug in (replace body, keep interface)

When 4.3.b lands, the body of `parse()` is replaced with pdfplumber
extraction logic. Downstream consumers (corpus.py, parse_all_tier.py,
load_chunks) don't need to change.
"""

from __future__ import annotations

import json
from pathlib import Path

from rag_leis.chunks import Chunk

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIER3_CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks" / "tier-3"


class AnpdPdfParser:
    """Phase 4.3.a stub. Re-reads JSONL produced by the manual transcription
    scripts in rag_leis/tier3_ingest/. Phase 4.3.b replaces the body with
    real pdfplumber extraction; the interface stays identical."""

    name: str = "anpd-pdf-stub-v0"

    def parse(self, document_urn: str, source: str) -> list[Chunk]:
        """Return the chunks for `document_urn`.

        `source` is ignored in the stub (the manual transcription already
        ran; the JSONL lives on disk). When 4.3.b lands, `source` will be
        the PDF file path or bytes and this method will do real extraction.

        Raises `FileNotFoundError` if no JSONL exists for the URN — the
        manual transcription script for that URN hasn't been run yet,
        which is the correct production failure mode (don't silently
        return empty).
        """
        jsonl_path = self._jsonl_path_for(document_urn)
        if not jsonl_path.exists():
            raise FileNotFoundError(
                f"No tier-3 JSONL for {document_urn!r}. "
                f"Expected at: {jsonl_path}. "
                f"Run the manual transcription script first: "
                f"`uv run python -m rag_leis.tier3_ingest.build_<slug>`"
            )

        chunks: list[Chunk] = []
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                # Construct a Chunk from the JSONL row. The audit metadata
                # (source, source_pdf_sha256, ingestion_method,
                # ingestion_provenance) is preserved in the JSONL but NOT
                # carried into the Chunk dataclass — Chunk's schema is
                # stable across tiers. load_chunks() reads the raw JSONL
                # and uses the audit fields downstream if needed.
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

    @staticmethod
    def _jsonl_path_for(document_urn: str) -> Path:
        """Map a tier-3 URN to its JSONL file path.

        Convention: `urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:YYYY-MM-DD;N`
        → `data/chunks/tier-3/anpd_res_<N>_<YYYY>.jsonl`
        """
        # urn:lex:br:autoridade.nacional.protecao.dados:resolucao.cd:2024-04-24;15
        # We need: 15 and 2024 → anpd_res_15_2024.jsonl
        # Format: `:resolucao.cd:<date>;<num>` is the last segment
        try:
            tail = document_urn.split(":")[-1]  # "2024-04-24;15"
            date_part, num_part = tail.split(";")
            year = date_part.split("-")[0]
            return TIER3_CHUNKS_DIR / f"anpd_res_{num_part}_{year}.jsonl"
        except (ValueError, IndexError) as e:
            raise ValueError(
                f"Cannot derive JSONL filename from URN: {document_urn!r}"
            ) from e
