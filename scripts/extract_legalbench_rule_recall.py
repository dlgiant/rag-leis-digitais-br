"""Extract rule-recall eval from celsowm/legalbench.br closed_book_qa.

Phase 7.5.4 — external-anchored citation precision metric.

Source format (closed_book_qa task, 160 rows total across 8 areas):
  Question: "Qual é o artigo do [code] com o texto: '[verbatim article text]'?"
  Answer:   article number as string, e.g. "69" → CF/88 art.69

Target metric: given the verbatim text of an article, can our pipeline (a)
retrieve the chunk containing that text and (b) cite the correct URN?

In-corpus areas (only these are testable):
  - Direito Constitucional → CF/88 (full coverage)
  - Direito Penal           → CP (full coverage)
  - Direito Civil           → CC arts.11-21 ONLY in our corpus; 0/20 CC
                              questions fall in that range, so skipped

OUT of corpus areas (5 skipped):
  Tributário, Trabalhista, Administrativo, Ambiental, Processual Civil.
  Their closed_book_qa rows reference CTN, CLT, etc. — not indexed.

Output: eval/legalbench_br_rule_recall.yaml with 40 rows (20 CF + 20 CP),
category="rule_recall" (new in run_concurso_eval.py for this phase).
Each row's gold_urns has ONE entry: the parsed URN of the target article.

Uso:
    uv run python -m scripts.extract_legalbench_rule_recall
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from datasets import load_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = PROJECT_ROOT / "eval" / "legalbench_br_rule_recall.yaml"

# Map legal_area → document_urn for laws we index in full.
# CC is intentionally absent: only arts.11-21 indexed; legalbench.br
# closed_book_qa CC rows all reference arts outside that range.
AREA_TO_DOC_URN: dict[str, str] = {
    "Direito Constitucional": "urn:lex:br:federal:constituicao:1988-10-05;1988",
    "Direito Penal":           "urn:lex:br:federal:decreto.lei:1940-12-07;2848",
}


def main() -> int:
    print("Loading celsowm/legalbench.br ...")
    ds = load_dataset("celsowm/legalbench.br")["train"]
    cbqa = [r for r in ds if r["type"] == "closed_book_qa"]
    print(f"closed_book_qa rows total: {len(cbqa)}")

    rows_out: list[dict] = []
    skipped_unparseable: list[str] = []
    for row in cbqa:
        area = row["legal_area"]
        doc_urn = AREA_TO_DOC_URN.get(area)
        if doc_urn is None:
            continue  # out of corpus
        # answer is the article number as string (sometimes with trailing
        # comma noise). Parse defensively.
        ans = row["answer"].strip().split(",")[0].strip()
        if not ans.replace("-", "").isalnum() or not any(c.isdigit() for c in ans):
            skipped_unparseable.append(f"{row['id']}/{area}/{row['answer']!r}")
            continue
        # Build URN — partition is `art{N}` (no inciso/parágrafo for this
        # closed-book task; the question targets the article itself).
        # Normalize: lowercase letter suffix (art154-A → art154-a) to match
        # our parser's convention.
        art_norm = ans.lower()
        partition = f"art{art_norm}"
        gold_urn = f"{doc_urn}~{partition}"

        # The question text is the user message (messages[1]).
        user_msg = row["messages"][1]["content"]
        rows_out.append({
            "source_id": f"celsowm/legalbench.br/{row['id']}",
            "category": "rule_recall",
            "question_type": "citacao-literal",  # canonical type-match for the eval
            "legal_area": area,
            "query": user_msg,
            "gold_urns": [gold_urn],
            "notes": (
                f"Rule recall: given verbatim text of {area} article, pipeline "
                f"must retrieve+cite {gold_urn}. answer_key={row['answer']!r}."
            ),
        })

    print(f"In-corpus rule recall rows: {len(rows_out)}")
    if skipped_unparseable:
        print(f"Skipped {len(skipped_unparseable)} unparseable answers:")
        for s in skipped_unparseable[:5]:
            print(f"  {s}")

    # Count per area in output
    from collections import Counter
    print("\nBy area in output:")
    for a, c in sorted(Counter(r["legal_area"] for r in rows_out).items()):
        print(f"  {a:35} {c}")

    header = (
        "# legalbench.br rule recall — Phase 7.5.4 (2026-05-17).\n"
        "#\n"
        "# Source: celsowm/legalbench.br, closed_book_qa task, CC BY-SA 4.0.\n"
        "# Filter: legal_area in {Constitucional, Penal} — areas where the\n"
        "#         underlying law (CF/88, CP) is fully indexed in our corpus.\n"
        "#         Direito Civil rows skipped — all reference articles outside\n"
        "#         our 11-21 indexed range. Other 5 areas (Tributário,\n"
        "#         Trabalhista, Administrativo, Ambiental, Processual Civil)\n"
        "#         reference codes not in corpus (CTN, CLT, CPC, etc.).\n"
        "#\n"
        f"# Total: {len(rows_out)} rule-recall rows (20 CF + 20 CP).\n"
        "#\n"
        "# Each row's `query` is the original prompt (\"Qual é o artigo do\n"
        "# [code] com o texto: '[verbatim]' ?\"). Gold = single URN for the\n"
        "# target article. Scoring (in run_concurso_eval.py rule_recall\n"
        "# category): pipeline must include the gold URN in its citations\n"
        "# (any-position; rank doesn't matter for this strict-match metric).\n"
        "#\n"
        "# This is an EXTERNAL-ANCHORED citation precision metric — gold\n"
        "# comes from a third-party benchmark, not from our self-curation.\n"
        "# Complements the internal cit_precision metric in answer_queries.yaml.\n"
        "#\n"
        "# Reproduce: uv run python -m scripts.extract_legalbench_rule_recall\n"
        "\n"
    )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        header + yaml.dump(rows_out, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"\nWrote {len(rows_out)} rows → {OUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
