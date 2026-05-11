from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from rag_leis.corpus import TIER_1
from rag_leis.parser import parse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "tier-1"
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks" / "tier-1"


def urn_to_filename(urn: str) -> str:
    return urn.replace("urn:lex:", "").replace(":", "_").replace(";", "_")


def main() -> int:
    if not RAW_DIR.exists():
        print(f"Missing {RAW_DIR}. Run fetch_tier1 first.", file=sys.stderr)
        return 1

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Parsing {len(TIER_1)} documents from {RAW_DIR}...")
    print()

    totals = {"artigo": 0, "paragrafo": 0, "inciso": 0, "alinea": 0}

    for doc in TIER_1:
        base = urn_to_filename(doc.urn)
        html_path = RAW_DIR / f"{base}.html"
        if not html_path.exists():
            print(f"[MISS]   {doc.urn}")
            continue

        html = html_path.read_text(encoding="utf-8")
        chunks = parse(doc.urn, html)

        out_path = CHUNKS_DIR / f"{base}.jsonl"
        with out_path.open("w", encoding="utf-8") as f:
            for c in chunks:
                payload = asdict(c)
                payload["urn"] = c.urn
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        by_kind: dict[str, int] = {}
        for c in chunks:
            by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
            totals[c.kind] = totals.get(c.kind, 0) + 1

        summary = "  ".join(f"{k}={by_kind.get(k, 0):>4}" for k in ("artigo", "paragrafo", "inciso", "alinea"))
        print(f"[OK]     {len(chunks):>5} chunks  {summary}  {doc.urn}")

    print()
    print("TOTAL:")
    for k, n in totals.items():
        print(f"  {k:10} {n:>5}")
    print(f"  {'all':10} {sum(totals.values()):>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
