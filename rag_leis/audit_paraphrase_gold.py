"""Audit gold completeness for paraphrase queries.

For each Query with qtype="parafrase", retrieve top-K from voyage dense and
emit a markdown worksheet showing:
  - the query text
  - the current gold (core / supporting)
  - top-K retrieved chunks, each annotated with whether it's already in gold
  - the chunk text snippet (~200 chars) for human review

Output is saved to eval/paraphrase-gold-review.md by default. The user reviews
the worksheet, marks chunks that should be added to gold (e.g. by changing
"[ ]" to "[x]" on the suggested-add lines), and then re-imports those into
queries.yaml manually.

Usage:
    python -m rag_leis.audit_paraphrase_gold
    python -m rag_leis.audit_paraphrase_gold --qtype enumeracao  # other types
    python -m rag_leis.audit_paraphrase_gold --top-k 8            # show more
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag_leis.embeddings import get_embedder  # noqa: E402
from rag_leis.eval_harness import (  # noqa: E402
    format_texts,
    load_chunks,
    load_queries,
    mrr_at_k,
)
from rag_leis.run_eval import _load_dotenv  # noqa: E402

CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"


def _truncate(text: str, n: int = 200) -> str:
    text = " ".join(text.split())  # normalize whitespace
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="voyage-3-large")
    p.add_argument("--text-mode", default="label+nav+caput+text")
    p.add_argument("--qtype", default="parafrase", help="Filter queries by qtype")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--eval", default="eval/queries.yaml")
    p.add_argument("--out", default="eval/paraphrase-gold-review.md")
    args = p.parse_args()

    _load_dotenv(PROJECT_ROOT / ".env")

    safe = args.model.replace("/", "_")
    cache = INDEX_DIR / f"{safe}__{args.text_mode}.npz"
    if not cache.exists():
        print(f"Dense cache missing: {cache.name}. Run run_eval first.")
        return 1
    loaded = np.load(cache, allow_pickle=True)
    doc_vecs = loaded["vecs"].astype(np.float32)
    urns = list(loaded["urns"])

    chunks = load_chunks(CHUNKS_DIR)
    text_by_urn = dict(zip([c.urn for c in chunks], [c.text for c in chunks], strict=True))
    nav_by_urn = dict(zip([c.urn for c in chunks], [c.nav_text for c in chunks], strict=True))
    dict(
        zip([c.urn for c in chunks], format_texts(chunks, args.text_mode), strict=True)
    )

    embedder = get_embedder(args.model)
    queries = load_queries(PROJECT_ROOT / args.eval)
    target_queries = [q for q in queries if (q.qtype or "untagged") == args.qtype]
    print(f"Loaded {len(queries)} queries; {len(target_queries)} of type={args.qtype!r}")

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append(f"# Gold review — qtype={args.qtype} ({len(target_queries)} queries)")
    lines.append("")
    lines.append(f"Model: `{args.model}` / mode: `{args.text_mode}` / top-{args.top_k} per query.")
    lines.append("")
    lines.append("**Como usar este worksheet:**")
    lines.append("")
    lines.append("Pra cada query, leia o `current gold` e os `top-K retrieved`. Se um chunk")
    lines.append("retornado **NÃO** está no gold mas é uma resposta semanticamente válida")
    lines.append("(ou parcial), mude o checkbox correspondente:")
    lines.append("")
    lines.append("- `[ ] add as core` → trocar pra `[x] add as core` se o chunk responde a query principal")
    lines.append("- `[ ] add as supporting` → marcar se é contexto/regra adjacente que ajuda")
    lines.append("- Deixar em branco se não-relevante")
    lines.append("")
    lines.append("Depois eu (ou você) atualiza `eval/queries.yaml` baseado nas marcações.")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, q in enumerate(target_queries, 1):
        qv = embedder.embed_query(q.query)
        sims = doc_vecs @ qv
        top_idx = np.argsort(-sims)[: args.top_k]
        top_urns = [urns[i] for i in top_idx]
        top_scores = [float(sims[i]) for i in top_idx]

        # Compute current MRR for context.
        mrr = mrr_at_k(top_urns, q.relevant, 10)

        lines.append(f"## [{i}] {q.query}")
        lines.append("")
        lines.append(f"- **MRR@10 atual**: {mrr:.3f}  |  notes: {q.notes or '(none)'}")
        lines.append("")
        lines.append("**Current gold:**")
        lines.append("")
        if not q.core and not q.supporting:
            lines.append("- _(nenhum)_")
        for u in sorted(q.core):
            txt = _truncate(text_by_urn.get(u, "(missing)"), 150)
            lines.append(f"- `core` → `{u}` — {txt}")
        for u in sorted(q.supporting):
            txt = _truncate(text_by_urn.get(u, "(missing)"), 150)
            lines.append(f"- `supporting` → `{u}` — {txt}")
        lines.append("")
        lines.append(f"**Top-{args.top_k} retrieved (voyage dense):**")
        lines.append("")

        for rank, (u, s) in enumerate(zip(top_urns, top_scores, strict=True), 1):
            in_core = u in q.core
            in_supp = u in q.supporting
            mark = "★ core" if in_core else ("◐ supporting" if in_supp else "  ")
            txt = _truncate(text_by_urn.get(u, "(missing)"), 220)
            nav = nav_by_urn.get(u, "")
            lines.append(f"### Rank {rank}  (sim={s:.4f})  {mark}")
            lines.append(f"- URN: `{u}`")
            if nav:
                lines.append(f"- nav: {nav}")
            lines.append(f"- text: {txt}")
            if not (in_core or in_supp):
                lines.append("- `[ ] add as core`")
                lines.append("- `[ ] add as supporting`")
            lines.append("")

        lines.append("---")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(target_queries)} queries × top-{args.top_k} to {out_path}")
    print(f"Open {out_path.relative_to(PROJECT_ROOT)} to review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
