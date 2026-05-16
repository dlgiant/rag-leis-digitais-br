"""Filter CC parser output → only arts. 11-21 (Cap. II Direitos da Personalidade).

The Código Civil tem ~2.789 chunks parseados; indexar tudo adiciona noise
ao corpus de leis digitais. Esse script aplica filtragem cirúrgica para
manter apenas o capítulo dos Direitos da Personalidade — pilar de queries
sobre imagem, intimidade, honra, nome.

Uso:
  uv run python scripts/filter_cc_personalidade.py

Pré-requisito: data/raw/tier-2/<base>.html já existe (rode `fetch_tier --tier 2`).

Saída: data/chunks/tier-2/cc_personalidade.jsonl (15 chunks: 11 artigos +
4 parágrafos únicos em arts. 12, 13, 14, 20).

Re-aplicar sempre que parse_all_tier --tier 2 for executado, porque o
parser sobrescreve o JSONL com TODO o CC.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

from rag_leis.fetch_tier import urn_to_filename
from rag_leis.parser import parse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CC_URN = "urn:lex:br:federal:lei:2002-01-10;10406"
KEEP_PATTERN = re.compile(r"^art(1[1-9]|2[01])(;|$)")


def main() -> int:
    base = urn_to_filename(CC_URN)
    html_path = PROJECT_ROOT / "data" / "raw" / "tier-2" / f"{base}.html"
    out_path = PROJECT_ROOT / "data" / "chunks" / "tier-2" / "cc_personalidade.jsonl"

    if not html_path.exists():
        print(f"ERRO: {html_path} não existe. Rode `uv run python -m rag_leis.fetch_tier --tier 2` antes.", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)

    html = html_path.read_text(encoding="utf-8")
    all_chunks = parse(CC_URN, html)
    filtered = [c for c in all_chunks if KEEP_PATTERN.match(c.partition)]

    with out_path.open("w", encoding="utf-8") as f:
        for c in filtered:
            payload = asdict(c)
            payload["urn"] = c.urn
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    print(f"CC parser produced {len(all_chunks)} chunks; kept {len(filtered)} (arts. 11-21).")
    print(f"Wrote {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
