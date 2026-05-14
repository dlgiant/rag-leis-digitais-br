from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from rag_leis.corpus import TIER_1, TIER_2, Document
from rag_leis.parser import parse

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Tier registry — extend when Tier-3 lands. Each entry: (docs, dir-suffix).
_TIERS: dict[str, tuple[tuple[Document, ...], str]] = {
    "1": (TIER_1, "tier-1"),
    "2": (TIER_2, "tier-2"),
}


def urn_to_filename(urn: str) -> str:
    return urn.replace("urn:lex:", "").replace(":", "_").replace(";", "_")


def _parse_one_tier(docs: tuple[Document, ...], tier_dir: str) -> dict[str, int]:
    raw_dir = PROJECT_ROOT / "data" / "raw" / tier_dir
    chunks_dir = PROJECT_ROOT / "data" / "chunks" / tier_dir

    if not raw_dir.exists():
        print(f"[SKIP {tier_dir}] missing {raw_dir} — run fetch first.", file=sys.stderr)
        return {}

    chunks_dir.mkdir(parents=True, exist_ok=True)

    print(f"Parsing {len(docs)} documents from {raw_dir.relative_to(PROJECT_ROOT)}...")

    totals: dict[str, int] = {}
    for doc in docs:
        base = urn_to_filename(doc.urn)
        html_path = raw_dir / f"{base}.html"
        if not html_path.exists():
            print(f"[MISS]   {doc.urn}")
            continue

        html = html_path.read_text(encoding="utf-8")
        chunks = parse(doc.urn, html)

        out_path = chunks_dir / f"{base}.jsonl"
        with out_path.open("w", encoding="utf-8") as f:
            for c in chunks:
                payload = asdict(c)
                payload["urn"] = c.urn
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        by_kind: dict[str, int] = {}
        for c in chunks:
            by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
            totals[c.kind] = totals.get(c.kind, 0) + 1

        summary = "  ".join(
            f"{k}={by_kind.get(k, 0):>4}"
            for k in ("artigo", "paragrafo", "inciso", "alinea", "item")
            if by_kind.get(k, 0) > 0 or k in ("artigo", "paragrafo", "inciso", "alinea")
        )
        print(f"[OK]     {len(chunks):>5} chunks  {summary}  {doc.urn}")
    return totals


def main() -> int:
    p = argparse.ArgumentParser(
        description="Parse fetched Planalto HTML into JSONL chunks, per Tier."
    )
    p.add_argument(
        "--tier",
        choices=["1", "2", "all"],
        default="1",
        help="Which tier's documents to parse (default: 1, for backward compat).",
    )
    args = p.parse_args()

    tiers_to_run = ["1", "2"] if args.tier == "all" else [args.tier]
    grand_total: dict[str, int] = {}
    for t in tiers_to_run:
        docs, tier_dir = _TIERS[t]
        tier_totals = _parse_one_tier(docs, tier_dir)
        for k, v in tier_totals.items():
            grand_total[k] = grand_total.get(k, 0) + v
        print()

    print("GRAND TOTAL:")
    for k, n in grand_total.items():
        print(f"  {k:10} {n:>5}")
    print(f"  {'all':10} {sum(grand_total.values()):>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
