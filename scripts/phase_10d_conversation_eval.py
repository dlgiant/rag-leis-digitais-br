"""Phase 10d — live eval of the rewriter against eval/conversation_queries.yaml.

For each of the 10 rows, calls the LIVE Maritaca rewriter (sabia-4)
with the row's prior_turns + current turn_2, then scores:

  1. classify_match — does classify_query(rewrite) equal the row's
     expected_classified_type_turn_2?
  2. preserves_oos_shape — for the OOS-follow-up row (conv-09), does
     the rewrite still NOT match any in-corpus citação-literal? (i.e.,
     the rewriter didn't launder the scope violation by inlining
     prior on-corpus entities)
  3. topic_shift_drop — for the topic-shift row (conv-04), does the
     rewrite NOT contain entities from turn_1?

Cost: ~$0.003 per pass (10 Maritaca rewrites at sabia-4 rates).
Latency: ~3-5s. Designed for one-shot operator runs after a prompt
iteration, NOT continuous CI.

Run:
    uv run python scripts/phase_10d_conversation_eval.py

Output:
    eval/runs/phase-10d-conversation-eval.json + stdout summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = PROJECT_ROOT / "eval" / "conversation_queries.yaml"

load_dotenv(PROJECT_ROOT / ".env", override=False)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out-json", type=Path,
        default=PROJECT_ROOT / "eval" / "runs" / "phase-10d-conversation-eval.json",
    )
    p.add_argument(
        "--llm-provider", default="maritaca",
        help="LLM provider (default: maritaca, matching production).",
    )
    args = p.parse_args()

    # Lazy import so dotenv loads first.
    from rag_leis.llm import get_llm
    from rag_leis.query_type import classify_query, rewrite_for_classification

    llm = get_llm(provider=args.llm_provider)
    rows = yaml.safe_load(EVAL_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(rows)} rows from {EVAL_PATH.relative_to(PROJECT_ROOT)}")
    print(f"Rewriter LLM: {args.llm_provider} ({llm.name})")
    print()

    results: list[dict[str, Any]] = []
    for r in rows:
        sid = r["source_id"]
        prior = [("user", r["turn_1"])]
        turn_2 = r["turn_2"]
        expected_type = r["expected_classified_type_turn_2"]

        print(f"  [{sid}] rewriting…", end="", flush=True)
        rewrite = rewrite_for_classification(prior, turn_2, llm=llm)
        actual_type = classify_query(rewrite)
        classify_ok = actual_type == expected_type
        # Crude content checks for the two special rows:
        oos_preserved = True
        topic_shift_dropped = True
        if sid == "conv-09-oos-follow-up-jurisprudence":
            # OOS query MUST still mention "STF" or "jurisprudência" (the
            # OOS-shape signal). If those terms got dropped, the rewrite
            # laundered the scope.
            oos_preserved = (
                "stf" in rewrite.lower() or "jurisprudência" in rewrite.lower()
            )
        if sid == "conv-04-topic-shift-explicit":
            # Topic-shift: rewrite MUST NOT contain "dado pessoal" or "LGPD"
            # (the turn_1 topic). Marco Civil entities are fine.
            lower = rewrite.lower()
            topic_shift_dropped = (
                "lgpd" not in lower
                and "dado pessoal" not in lower
            )

        passed = classify_ok and oos_preserved and topic_shift_dropped
        print(f" {'✓' if passed else '✗'}")
        if not passed:
            print(f"    expected_type={expected_type}  actual_type={actual_type}")
            if not oos_preserved:
                print("    OOS shape NOT preserved (STF/jurisprudência missing)")
            if not topic_shift_dropped:
                print("    topic shift NOT dropped (LGPD/dado pessoal leaked)")
            print(f"    expected_rewrite_turn_2: {r.get('expected_rewrite_turn_2', '?')}")
            print(f"    actual rewrite:          {rewrite}")

        results.append({
            "source_id": sid,
            "turn_2": turn_2,
            "expected_type": expected_type,
            "actual_type": actual_type,
            "classify_ok": classify_ok,
            "oos_preserved": oos_preserved,
            "topic_shift_dropped": topic_shift_dropped,
            "passed": passed,
            "rewrite": rewrite,
            "reference_rewrite": r.get("expected_rewrite_turn_2", ""),
        })

    n_total = len(results)
    n_classify_ok = sum(1 for r in results if r["classify_ok"])
    n_oos_ok = sum(1 for r in results if r["oos_preserved"])
    n_topic_ok = sum(1 for r in results if r["topic_shift_dropped"])
    n_passed = sum(1 for r in results if r["passed"])

    print()
    print("=" * 50)
    print(f"classify_match:       {n_classify_ok}/{n_total}")
    print(f"oos_preserved:        {n_oos_ok}/{n_total}")
    print(f"topic_shift_dropped:  {n_topic_ok}/{n_total}")
    print(f"OVERALL passed:       {n_passed}/{n_total}")
    print("=" * 50)

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps({
            "config": {
                "llm_provider": args.llm_provider,
                "llm_name": getattr(llm, "name", "?"),
                "n_rows": n_total,
            },
            "summary": {
                "classify_match": n_classify_ok,
                "oos_preserved": n_oos_ok,
                "topic_shift_dropped": n_topic_ok,
                "passed": n_passed,
            },
            "rows": results,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote {args.out_json.relative_to(PROJECT_ROOT)}")
    return 0 if n_passed == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
