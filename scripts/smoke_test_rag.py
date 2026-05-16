"""Post-merge smoke test (Phase 7.5).

Runs 10 canonical RAG queries through the production pipeline (Voyage
retrieval + Sabiá generation per study/llm-provider-decision-2026-05-15).
Exits 0 on full success, 1 on any failure mode:

  - pipeline crash (uncaught exception)
  - empty answer text on an in-scope query
  - unexpected refusal on a query that has documented in-scope coverage
  - all queries refused (suggests systemic problem)

Not a metric gate — that's the weekly refresh's job. This is a
"does the production path still WORK end-to-end?" check, the kind of
regression that bypasses unit tests but breaks real usage.

Uso:
  uv run python -m scripts.smoke_test_rag
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

# 10 canonical in-scope queries. Mix of types so the pipeline exercises
# different code paths. None should refuse; all should produce non-empty
# answers with at least one citation.
SMOKE_QUERIES = [
    "qual a definição de dado pessoal na LGPD?",
    "quais são as hipóteses legais para tratar dados pessoais sem consentimento?",
    "o que é neutralidade de rede no Marco Civil da Internet?",
    "por quanto tempo um provedor de conexão precisa guardar os logs?",
    "quais sanções administrativas a ANPD pode aplicar?",
    "o que diz a Súmula 227 do STJ?",
    "existe direito ao esquecimento no Brasil?",
    "qual a regra do Código Civil sobre o uso da imagem da pessoa?",
    "transferiram dinheiro da minha conta sem permissão, qual o crime?",
    "como faço pra pedir uma informação pra uma prefeitura?",
]


@dataclass
class QueryResult:
    query: str
    ok: bool
    reason: str  # short marker: "ok", "crash", "empty", "refused", "no_citations"
    answer_preview: str = ""


def _run_one(pipe, query: str) -> QueryResult:
    try:
        ans = pipe.answer(query)
    except Exception as e:
        return QueryResult(query=query, ok=False, reason=f"crash: {type(e).__name__}: {e}")

    if ans.refused:
        return QueryResult(
            query=query, ok=False, reason=f"refused: {ans.refusal_reason or '(no reason)'}"
        )
    if not ans.answer or not ans.answer.strip():
        return QueryResult(query=query, ok=False, reason="empty answer text")
    if not getattr(ans, "verified_citations", None) and not getattr(ans, "citations", None):
        return QueryResult(query=query, ok=False, reason="no_citations")
    return QueryResult(
        query=query, ok=True, reason="ok",
        answer_preview=(ans.answer[:120] + "…") if len(ans.answer) > 120 else ans.answer,
    )


def main() -> int:
    from rag_leis.rag import load_pipeline

    project = Path(__file__).resolve().parents[1]
    print(f"[smoke] loading pipeline (Voyage + Sabiá production stack)...")
    try:
        pipe = load_pipeline(
            chunks_dir=project / "data" / "chunks",
            index_dir=project / "data" / "index",
            llm_provider="maritaca",  # production generator
        )
    except Exception as e:
        traceback.print_exc()
        print(f"\n[smoke] EXIT 1: pipeline load failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"[smoke] pipeline loaded; running {len(SMOKE_QUERIES)} canonical queries...\n")

    results = [_run_one(pipe, q) for q in SMOKE_QUERIES]
    for i, r in enumerate(results, 1):
        mark = "OK  " if r.ok else "FAIL"
        print(f"  [{i:2}/{len(results)}] [{mark}] {r.query[:70]}")
        if not r.ok:
            print(f"           reason: {r.reason}")
        elif r.answer_preview:
            print(f"           answer: {r.answer_preview}")

    failed = [r for r in results if not r.ok]
    print()
    if failed:
        print(f"[smoke] EXIT 1: {len(failed)}/{len(results)} queries failed:", file=sys.stderr)
        for r in failed:
            print(f"  - {r.query!r}: {r.reason}", file=sys.stderr)
        return 1

    print(f"[smoke] EXIT 0: all {len(results)} queries passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
