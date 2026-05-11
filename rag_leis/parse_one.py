from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rag_leis.parser import parse


def main() -> int:
    p = argparse.ArgumentParser(description="Parse one Planalto HTML into chunks.")
    p.add_argument("html_path", help="Path to HTML file")
    p.add_argument("urn", help="Document URN")
    p.add_argument(
        "--filter", help="Show only chunks whose partition starts with this prefix"
    )
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--text-width", type=int, default=180)
    args = p.parse_args()

    html = Path(args.html_path).read_text(encoding="utf-8")
    chunks = parse(args.urn, html)

    shown = 0
    for c in chunks:
        if args.filter and not c.partition.startswith(args.filter):
            continue
        shown += 1
        if shown > args.limit:
            break
        text = c.text
        if len(text) > args.text_width:
            text = text[: args.text_width] + "..."
        print(
            json.dumps(
                {
                    "partition": c.partition,
                    "kind": c.kind,
                    "label": c.label,
                    "text": text,
                },
                ensure_ascii=False,
            )
        )

    by_kind: dict[str, int] = {}
    for c in chunks:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
    print(f"\nTotal chunks: {len(chunks)}", file=sys.stderr)
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind:10} {count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
