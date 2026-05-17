"""Concurso/OAB eval runner — parallel to run_answer_eval but adapted to
the OAB MCQ schema (`eval/oab_concurso_pilot.yaml`).

Three buckets of rows, three different scoring rules:

  inscope  — pipeline should answer non-refused. Cited URNs must "cover"
             gold_urns (any-overlap, not strict-equal). The Brazilian OAB
             question has ONE correct alternative legally supported by
             specific articles; we measure whether the pipeline found
             AT LEAST one of those articles in its citations.

             metrics: inscope_answer_rate (not-refused), inscope_coverage_rate
             (cited ∩ gold non-empty), inscope_coverage_jaccard (avg).

  oos_a    — clearly other-domain (TAXES, LABOUR-PROCEDURE, INTERNATIONAL).
             Pipeline must refuse (refused=True).
             metrics: oos_a_refusal_rate.

  oos_b    — adjacent-without-coverage. Topic touches our corpus' adjacency
             (internet/dados) but operative norm not indexed (ECA, Código
             Ética OAB). Pipeline must refuse — but this is the harder case
             where the model might over-answer.
             metrics: oos_b_refusal_rate.

Uso:
    uv run python -m rag_leis.run_concurso_eval
    uv run python -m rag_leis.run_concurso_eval --output eval/runs/concurso-baseline.json

Pre-req: cached Voyage index + secrets (MARITACA_API_KEY for the production
generator; VOYAGE_API_KEY for index loading).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from rag_leis.rag import (
    DEFAULT_EMBEDDER,
    DEFAULT_OOS_THRESHOLD,
    DEFAULT_TEXT_MODE,
    DEFAULT_TOP_K,
    RAGAnswer,
    load_pipeline,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"
DEFAULT_EVAL_PATH = PROJECT_ROOT / "eval" / "oab_concurso_pilot.yaml"


@dataclass
class ConcursoRow:
    source_id: str
    category: str  # "inscope" | "oos_a" | "oos_b"
    query: str
    question_type: str | None = None
    expected_oos_subtype: str | None = None
    gold_urns: frozenset[str] = frozenset()
    correct_alternative_text: str = ""
    notes: str = ""


@dataclass
class ConcursoEvalRecord:
    row: ConcursoRow
    answer: RAGAnswer
    # Per-row computed signals (None when not applicable to category)
    refused_correctly: bool = False
    coverage: float | None = None  # |cited ∩ gold| / |gold| for inscope
    coverage_jaccard: float | None = None
    any_gold_cited: bool | None = None  # binary "at least one hit"


@dataclass
class ConcursoAggregate:
    n_total: int
    n_inscope: int
    n_oos_a: int
    n_oos_b: int
    # In-scope metrics
    inscope_answer_rate: float = 0.0       # not-refused / inscope
    inscope_any_gold_cited_rate: float = 0.0  # at-least-one-gold-URN / inscope
    inscope_coverage_mean: float = 0.0      # avg recall-style coverage
    inscope_coverage_jaccard_mean: float = 0.0
    # OOS metrics
    oos_a_refusal_rate: float = 0.0
    oos_b_refusal_rate: float = 0.0
    # Combined refusal accuracy (oos_a + oos_b should refuse; inscope should not)
    overall_refusal_accuracy: float = 0.0


def load_rows(path: Path) -> list[ConcursoRow]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[ConcursoRow] = []
    for item in data:
        out.append(ConcursoRow(
            source_id=item["source_id"],
            category=item["category"],
            query=item["query"],
            question_type=item.get("question_type"),
            expected_oos_subtype=item.get("expected_oos_subtype"),
            gold_urns=frozenset(item.get("gold_urns") or []),
            correct_alternative_text=item.get("correct_alternative_text", ""),
            notes=item.get("notes", ""),
        ))
    return out


def _score_inscope(row: ConcursoRow, ans: RAGAnswer) -> ConcursoEvalRecord:
    """In-scope row: should be answered (not refused) AND citations should
    cover gold."""
    cited = set(ans.citations)
    gold = set(row.gold_urns)
    if not gold:
        coverage = None
        jaccard = None
        any_hit = None
    else:
        hits = cited & gold
        coverage = len(hits) / len(gold) if gold else 0.0
        union = cited | gold
        jaccard = len(hits) / len(union) if union else 0.0
        any_hit = bool(hits)
    # In-scope: refused_correctly is True if NOT refused
    refused_correctly = not ans.refused
    return ConcursoEvalRecord(
        row=row,
        answer=ans,
        refused_correctly=refused_correctly,
        coverage=coverage,
        coverage_jaccard=jaccard,
        any_gold_cited=any_hit,
    )


def _score_oos(row: ConcursoRow, ans: RAGAnswer) -> ConcursoEvalRecord:
    """OOS row: should be refused."""
    return ConcursoEvalRecord(
        row=row,
        answer=ans,
        refused_correctly=ans.refused,
    )


def aggregate(records: list[ConcursoEvalRecord]) -> ConcursoAggregate:
    inscope = [r for r in records if r.row.category == "inscope"]
    oos_a = [r for r in records if r.row.category == "oos_a"]
    oos_b = [r for r in records if r.row.category == "oos_b"]

    def _safe_mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return ConcursoAggregate(
        n_total=len(records),
        n_inscope=len(inscope),
        n_oos_a=len(oos_a),
        n_oos_b=len(oos_b),
        inscope_answer_rate=_safe_mean([1.0 if not r.answer.refused else 0.0 for r in inscope]),
        inscope_any_gold_cited_rate=_safe_mean(
            [1.0 if r.any_gold_cited else 0.0 for r in inscope if r.any_gold_cited is not None]
        ),
        inscope_coverage_mean=_safe_mean(
            [r.coverage for r in inscope if r.coverage is not None]
        ),
        inscope_coverage_jaccard_mean=_safe_mean(
            [r.coverage_jaccard for r in inscope if r.coverage_jaccard is not None]
        ),
        oos_a_refusal_rate=_safe_mean([1.0 if r.refused_correctly else 0.0 for r in oos_a]),
        oos_b_refusal_rate=_safe_mean([1.0 if r.refused_correctly else 0.0 for r in oos_b]),
        overall_refusal_accuracy=_safe_mean(
            [1.0 if r.refused_correctly else 0.0 for r in records]
        ),
    )


def print_report(records: list[ConcursoEvalRecord], agg: ConcursoAggregate) -> None:
    print(f"\nConcurso pilot eval — {agg.n_total} rows ({agg.n_inscope} inscope, "
          f"{agg.n_oos_a} oos_a, {agg.n_oos_b} oos_b)")

    print(f"\n{'#':>2}  {'category':<10}  {'src_id':<35}  {'refused':>7}  "
          f"{'cov':>5}  {'gold-hit':>8}  query[:60]")
    for i, r in enumerate(records, 1):
        cat = r.row.category
        ref = "Y" if r.answer.refused else "N"
        cov_str = f"{r.coverage:.2f}" if r.coverage is not None else "  -  "
        hit_str = "Y" if r.any_gold_cited else ("N" if r.any_gold_cited is False else "-")
        ok = "✓" if r.refused_correctly else "✗"
        print(f"{i:>2}  [{ok}] {cat:<6}  {r.row.source_id[-30:]:<30}  {ref:>7}  "
              f"{cov_str:>5}  {hit_str:>8}  {r.row.query[:60]}")

    print(f"\n--- IN-SCOPE ---")
    print(f"  answer_rate (not-refused):          {agg.inscope_answer_rate:.3f}  "
          f"({agg.n_inscope} rows)")
    print(f"  any_gold_cited_rate:                {agg.inscope_any_gold_cited_rate:.3f}")
    print(f"  coverage_mean (|cited∩gold|/|gold|):{agg.inscope_coverage_mean:.3f}")
    print(f"  coverage_jaccard_mean:              {agg.inscope_coverage_jaccard_mean:.3f}")
    print(f"\n--- OOS ---")
    print(f"  oos_a refusal_rate (other domain):  {agg.oos_a_refusal_rate:.3f}  "
          f"({agg.n_oos_a} rows)")
    print(f"  oos_b refusal_rate (adjacent):      {agg.oos_b_refusal_rate:.3f}  "
          f"({agg.n_oos_b} rows)")
    print(f"\n--- OVERALL ---")
    print(f"  overall_refusal_accuracy:           {agg.overall_refusal_accuracy:.3f}")


def serialize_record(r: ConcursoEvalRecord) -> dict[str, Any]:
    """JSON-serializable per-row record for the run log."""
    return {
        "row": {
            "source_id": r.row.source_id,
            "category": r.row.category,
            "query": r.row.query,
            "question_type": r.row.question_type,
            "expected_oos_subtype": r.row.expected_oos_subtype,
            "gold_urns": sorted(r.row.gold_urns),
            "notes": r.row.notes,
        },
        "answer": {
            "text": r.answer.answer,
            "citations": r.answer.citations,
            "refused": r.answer.refused,
            "refusal_reason": r.answer.refusal_reason,
            "rejected_citations": r.answer.rejected_citations,
            "unverified_claims": r.answer.unverified_claims,
            "hierarchy_warning": r.answer.hierarchy_warning,
        },
        "scoring": {
            "refused_correctly": r.refused_correctly,
            "coverage": r.coverage,
            "coverage_jaccard": r.coverage_jaccard,
            "any_gold_cited": r.any_gold_cited,
        },
    }


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--eval", default=str(DEFAULT_EVAL_PATH))
    p.add_argument("--output", default=None,
                   help="Write full per-row report to this JSON file.")
    p.add_argument("--llm-provider", default="maritaca",
                   help="LLM provider for the generator (default: maritaca, "
                        "matching production).")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    args = p.parse_args()

    eval_path = Path(args.eval)
    rows = load_rows(eval_path)
    print(f"Loaded {len(rows)} rows from {eval_path.relative_to(PROJECT_ROOT)}")

    print(f"Building pipeline (Voyage + {args.llm_provider}, "
          f"text_mode={DEFAULT_TEXT_MODE}, top_k={args.top_k}) ...")
    pipe = load_pipeline(
        chunks_dir=CHUNKS_DIR,
        index_dir=INDEX_DIR,
        llm_provider=args.llm_provider,
        top_k=args.top_k,
    )

    records: list[ConcursoEvalRecord] = []
    for i, row in enumerate(rows, 1):
        print(f"  [{i:>2}/{len(rows)}] [{row.category}] {row.source_id} ...", end="", flush=True)
        ans = pipe.answer(row.query)
        if row.category == "inscope":
            rec = _score_inscope(row, ans)
        else:
            rec = _score_oos(row, ans)
        records.append(rec)
        mark = "✓" if rec.refused_correctly else "✗"
        print(f" {mark} refused={ans.refused}")

    agg = aggregate(records)
    print_report(records, agg)

    if args.output:
        # Resolve to absolute so the run can be invoked from any cwd; only
        # use relative_to when the output is actually under PROJECT_ROOT
        # (typical case: eval/runs/*.json).
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = (PROJECT_ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "config": {
                        "embedder": DEFAULT_EMBEDDER,
                        "text_mode": DEFAULT_TEXT_MODE,
                        "llm_provider": args.llm_provider,
                        "top_k": args.top_k,
                        "oos_threshold": DEFAULT_OOS_THRESHOLD,
                    },
                    "aggregate": asdict(agg),
                    "records": [serialize_record(r) for r in records],
                },
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            shown = out_path.relative_to(PROJECT_ROOT)
        except ValueError:
            shown = out_path
        print(f"\nWrote report → {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
