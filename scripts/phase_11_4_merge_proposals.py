"""Phase 11.4 — operator merge tool.

Walks through pending review proposals (kind='review' or 'new_row')
from Postgres, prompts the operator to accept/reject/skip each, and
applies accepted ones to `eval/queries.yaml`. After acceptance, the
proposal is marked merged via proposals.mark_merged() so it doesn't
appear in `/proposals` or in this tool's queue again.

Runs locally on the OPERATOR's workstation — not on Fly. The operator
points DATABASE_URL at the production Neon DB (read from .env).
Writes only happen to the LOCAL eval/queries.yaml + the Neon
merged_proposals table.

Workflow:

    $ uv run python scripts/phase_11_4_merge_proposals.py

    Pending proposals: 3
    ────────────────────────────────────────────────────────

    [1/3] kind=review  reviewer=lawyer@example.com
    Query: "qual a definição de dado pessoal na LGPD?"
    Verdict: incorrect
    Notes: "Gold URN should be art 5;inc2 (sensitive data), not inc1"
    Suggested gold URNs:
      - urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2
    Current row in eval/queries.yaml:
      relevant: ["urn:lex:br:federal:lei:2018-08-14;13709~art5;inc1"]

    [a]ccept / [r]eject / [s]kip / [q]uit: a
    ✓ Updated row's `relevant` to the suggested URN.
    ✓ Marked merged in DB.

    ...

    Done. 2 accepted, 0 rejected, 1 skipped. Don't forget to:
        git diff eval/queries.yaml
        git commit -am "merge phase 11.4 proposals"
        git push

The tool does NOT auto-commit/push — the operator reviews the YAML
diff manually before committing. That's intentional: the merge tool
edits a git-tracked file; the operator owns the commit.

Supported proposal kinds in 11.4 MVP:
  - `review`   — verdict + optional suggested_gold_urns / suggested_classified_type
                  → updates the existing eval row's `relevant` / `type` fields
                  → no-op merge for verdict=correct with no suggestions
                  → no-op merge for verdict=needs_followup (operator's
                    follow-up triggers a new proposal)
  - `new_row`  — adds a new eval row from new_query_text + new_qtype +
                  new_core_urns + new_supporting_urns

Phase 11.3 update:
  - `refinement` — proposals from the inline-refinement UI now treated
                    same as `new_row` on accept: the refined_query_text
                    becomes the new row's query; new_core_urns (which
                    the refine endpoint pre-populated from the
                    retriever's actual top-k hits) become the new row's
                    `relevant`. The operator can still skip+merge
                    refinements without promotion if they want to keep
                    them as informational notes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import IO

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

from rag_leis import db
from rag_leis.eval_loader import query_id as derive_query_id
from rag_leis.proposals import Proposal, load_pending_proposals, mark_merged

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_PATH = PROJECT_ROOT / "eval" / "queries.yaml"
DEFAULT_OVERLAYS_PATH = PROJECT_ROOT / "data" / "vigencia" / "overlays.yaml"


# ---------------------------------------------------------------------------
# YAML editing (pure functions — testable without DB / stdin)
# ---------------------------------------------------------------------------


def _yaml() -> YAML:
    """ruamel.yaml configured for round-trip + sensible defaults
    matching the existing eval/queries.yaml hand-written style."""
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 100
    return y


def load_eval(path: Path | None = None) -> list[dict]:
    """Read eval/queries.yaml as a round-trippable list of dict rows."""
    p = path or DEFAULT_EVAL_PATH
    with p.open("r", encoding="utf-8") as f:
        return _yaml().load(f)


def save_eval(data: list[dict], path: Path | None = None) -> None:
    """Write the modified rows back, preserving comments + style."""
    p = path or DEFAULT_EVAL_PATH
    with p.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)


def find_row_by_query_id(rows: list[dict], qid: str) -> tuple[int, dict] | None:
    """Linear scan for the row whose normalized query text hashes to qid.
    Returns (index, row) or None if not found."""
    for i, row in enumerate(rows):
        query_text = row.get("query")
        if not isinstance(query_text, str):
            continue
        if derive_query_id(query_text) == qid:
            return i, row
    return None


def apply_review_to_yaml(rows: list[dict], proposal: Proposal) -> str:
    """Apply a kind='review' proposal to the in-memory rows list.

    Returns a short human-readable description of what changed (for
    the CLI's confirmation message). Raises ValueError if the
    proposal can't be applied (e.g., query_id not found).
    """
    if not proposal.query_id:
        raise ValueError("review proposal missing query_id")
    located = find_row_by_query_id(rows, proposal.query_id)
    if located is None:
        raise ValueError(
            f"query_id {proposal.query_id} not found in eval/queries.yaml "
            f"(was the row deleted or its text edited?)"
        )
    _, row = located

    changes: list[str] = []

    if proposal.suggested_gold_urns:
        # Replace the row's `relevant` field with the suggested URNs.
        # Use double-quoted strings to match the existing file's style.
        row["relevant"] = [DQ(u) for u in proposal.suggested_gold_urns]
        changes.append(
            f"`relevant` updated to {len(proposal.suggested_gold_urns)} suggested URN(s)"
        )

    if proposal.suggested_classified_type:
        # `type` in queries.yaml is unquoted (a YAML "plain scalar").
        # Just assign the string.
        row["type"] = proposal.suggested_classified_type
        changes.append(f"`type` updated to {proposal.suggested_classified_type!r}")

    if not changes:
        # verdict=correct with no suggestions, or verdict=needs_followup.
        # Still mark merged so it doesn't sit in the queue.
        return "no YAML change (verdict acknowledged; row left as-is)"

    return "; ".join(changes)


def load_overlays_yaml(path: Path | None = None) -> list[dict]:
    """Load `data/vigencia/overlays.yaml` as a round-trippable list.

    The file is a top-level YAML list (each entry is a dict with urn /
    status / fundamento / desde / descricao_curta). Comments above
    section headers (sub_judice, suspenso, etc.) are preserved by
    ruamel's round-trip.
    """
    p = path or DEFAULT_OVERLAYS_PATH
    with p.open("r", encoding="utf-8") as f:
        return _yaml().load(f)


def save_overlays_yaml(data: list[dict], path: Path | None = None) -> None:
    """Write back. Preserves comments + ordering."""
    p = path or DEFAULT_OVERLAYS_PATH
    with p.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)


def find_overlay_by_urn(rows: list[dict], urn: str) -> tuple[int, dict] | None:
    """Linear scan for the overlay row matching this chunk URN."""
    for i, row in enumerate(rows):
        if row.get("urn") == urn:
            return i, row
    return None


def apply_vigencia_to_yaml(rows: list[dict], proposal: Proposal) -> str:
    """Apply a kind='vigencia' proposal to overlays.yaml's rows list.

    If an overlay for this URN already exists, REPLACE its fields in
    place (preserving its position in the file so the section grouping
    stays clean). Otherwise, append a new entry at the end — the
    operator can manually reorder it into the right section comment
    block via `git diff` review before committing.

    Returns a short description of what changed.
    """
    if not proposal.vigencia_urn:
        raise ValueError("vigencia proposal missing vigencia_urn")
    if not proposal.vigencia_status:
        raise ValueError("vigencia proposal missing vigencia_status")
    if not proposal.vigencia_fundamento:
        raise ValueError("vigencia proposal missing vigencia_fundamento")
    if not proposal.vigencia_desde:
        raise ValueError("vigencia proposal missing vigencia_desde")
    if not proposal.vigencia_descricao_curta:
        raise ValueError("vigencia proposal missing vigencia_descricao_curta")

    located = find_overlay_by_urn(rows, proposal.vigencia_urn)
    new_entry = {
        "urn": DQ(proposal.vigencia_urn),
        "status": proposal.vigencia_status,
        "fundamento": DQ(proposal.vigencia_fundamento),
        "desde": proposal.vigencia_desde,
        "descricao_curta": proposal.vigencia_descricao_curta,
    }
    if located is None:
        rows.append(new_entry)
        return (
            f"appended new vigência overlay for "
            f"{proposal.vigencia_urn} (status={proposal.vigencia_status})"
        )
    idx, _ = located
    rows[idx] = new_entry
    return (
        f"replaced existing overlay for {proposal.vigencia_urn} "
        f"(now status={proposal.vigencia_status})"
    )


def apply_refinement_to_yaml(rows: list[dict], proposal: Proposal) -> str:
    """Apply a kind='refinement' proposal: promote to a new eval row.

    Treats the refinement's `refined_query_text` as the new row's
    query and its `new_core_urns` (captured at refine-time by the
    retriever) as the new row's `relevant`. Reuses
    `apply_new_row_to_yaml` by constructing an equivalent new_row-
    shaped Proposal on the fly.

    Raises ValueError if refined_query_text or new_core_urns are
    missing.
    """
    if not proposal.refined_query_text:
        raise ValueError("refinement proposal missing refined_query_text")
    if not proposal.new_core_urns:
        raise ValueError(
            "refinement proposal missing new_core_urns "
            "(should have been captured by the refine endpoint)"
        )
    # Synthesize a new_row-shaped proposal so we get identical YAML
    # emission semantics (DoubleQuotedScalarString URNs, optional
    # graded form, notes carry-over).
    synthetic = Proposal(
        id=proposal.id,
        ts=proposal.ts,
        reviewer_email=proposal.reviewer_email,
        is_operator=proposal.is_operator,
        kind="new_row",
        new_query_text=proposal.refined_query_text,
        # The original query's classified_type isn't on the refinement
        # proposal; leave new_qtype empty so the operator can fill it
        # in via a manual edit later, OR (better) extend the refine
        # endpoint to copy the original row's type. For now: missing.
        new_qtype=None,
        new_core_urns=proposal.new_core_urns,
        notes=proposal.notes or "promoted from refinement proposal",
    )
    inner_msg = apply_new_row_to_yaml(rows, synthetic)
    return f"promoted refinement → {inner_msg}"


def apply_new_row_to_yaml(rows: list[dict], proposal: Proposal) -> str:
    """Apply a kind='new_row' proposal: append a new row to the list.

    Returns a short description. Raises ValueError if the proposal
    is missing required fields.
    """
    if not proposal.new_query_text:
        raise ValueError("new_row proposal missing new_query_text")

    new_row: dict = {
        "query": DQ(proposal.new_query_text),
    }
    if proposal.new_qtype:
        new_row["type"] = proposal.new_qtype
    if proposal.new_core_urns:
        new_row["relevant"] = [DQ(u) for u in proposal.new_core_urns]
        if proposal.new_supporting_urns:
            # Use the graded form when supporting URNs exist
            new_row["relevant"] = {
                "core": [DQ(u) for u in proposal.new_core_urns],
                "supporting": [DQ(u) for u in proposal.new_supporting_urns],
            }
    if proposal.notes:
        new_row["notes"] = proposal.notes

    rows.append(new_row)
    return (
        f"appended new row: {proposal.new_query_text[:60]}…  "
        f"({len(proposal.new_core_urns)} core URN(s))"
    )


# ---------------------------------------------------------------------------
# CLI rendering + interaction
# ---------------------------------------------------------------------------


def _hr(out: IO[str]) -> None:
    print("─" * 60, file=out)


def render_proposal(
    proposal: Proposal,
    rows: list[dict],
    out: IO[str],
) -> None:
    """Pretty-print one proposal to `out`, including context from the
    current YAML row if it's a review/refinement proposal."""
    print(file=out)
    print(f"  kind:         {proposal.kind}", file=out)
    print(f"  reviewer:     {proposal.reviewer_email}"
          f"{'  (operator)' if proposal.is_operator else ''}", file=out)
    print(f"  submitted:    {proposal.ts}", file=out)
    print(f"  proposal id:  {proposal.id[:12]}", file=out)

    if proposal.query_id:
        print(f"  query_id:     {proposal.query_id}", file=out)
        located = find_row_by_query_id(rows, proposal.query_id)
        if located:
            _, row = located
            print(f"  query:        {row.get('query', '?')}", file=out)
            print(f"  current type: {row.get('type', '—')}", file=out)
            current_relevant = row.get("relevant")
            print(f"  current relevant:  {current_relevant}", file=out)
        else:
            print("  ⚠  query_id NOT found in eval/queries.yaml", file=out)

    if proposal.verdict:
        print(f"  verdict:      {proposal.verdict}", file=out)
    if proposal.notes:
        print(f"  notes:        {proposal.notes}", file=out)

    if proposal.suggested_gold_urns:
        print(f"  SUGGESTED URNs ({len(proposal.suggested_gold_urns)}):", file=out)
        for u in proposal.suggested_gold_urns:
            print(f"    → {u}", file=out)
    if proposal.suggested_classified_type:
        print(f"  SUGGESTED type:  {proposal.suggested_classified_type}", file=out)

    if proposal.kind == "new_row":
        print(f"  new_query_text:   {proposal.new_query_text}", file=out)
        print(f"  new_qtype:        {proposal.new_qtype}", file=out)
        print(f"  new_core_urns:    {list(proposal.new_core_urns)}", file=out)
        if proposal.new_supporting_urns:
            print(f"  new_supporting:   {list(proposal.new_supporting_urns)}", file=out)


def prompt_action(prompt: str = "[a]ccept / [r]eject / [s]kip / [q]uit: ") -> str:
    """Read one keystroke-ish input. Loops until a valid choice."""
    while True:
        try:
            choice = input(prompt).strip().lower()
        except EOFError:
            return "q"
        if choice in {"a", "accept"}:
            return "accept"
        if choice in {"r", "reject"}:
            return "reject"
        if choice in {"s", "skip"}:
            return "skip"
        if choice in {"q", "quit"}:
            return "quit"
        print("  (please enter a / r / s / q)")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval", type=Path, default=DEFAULT_EVAL_PATH,
        help="Path to eval/queries.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--overlays", type=Path, default=DEFAULT_OVERLAYS_PATH,
        help="Path to data/vigencia/overlays.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what WOULD be applied; don't write YAML or mark merged.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N proposals (useful for testing).",
    )
    args = parser.parse_args()

    if not db.database_url():
        print("ERROR: DATABASE_URL is not set. Source .env first.", file=sys.stderr)
        return 2
    db.init_pool()

    pending = load_pending_proposals()
    if args.limit:
        pending = pending[: args.limit]

    if not pending:
        print("No pending proposals. Nothing to merge.")
        return 0

    print(f"Pending proposals: {len(pending)}")
    _hr(sys.stdout)

    rows = load_eval(args.eval)
    overlay_rows = load_overlays_yaml(args.overlays)
    accepted = rejected = skipped = 0
    eval_dirty = False
    overlays_dirty = False

    for i, p in enumerate(pending, start=1):
        print(f"\n[{i}/{len(pending)}]", end="")
        render_proposal(p, rows, sys.stdout)

        if p.kind == "refinement":
            print(
                "  ℹ  Accept → promotes refined_query_text + captured retrieved URNs "
                "into a new eval row. Reject → discard. Skip → leave pending.",
                file=sys.stderr,
            )
        if p.kind == "vigencia":
            print(
                "  ℹ  Accept → writes overlay entry to data/vigencia/overlays.yaml. "
                "Reject → discard. Skip → leave pending.",
                file=sys.stderr,
            )

        action = prompt_action()
        if action == "quit":
            print("\nQuitting. Unprocessed proposals remain pending.")
            break
        if action == "skip":
            skipped += 1
            continue
        if action == "reject":
            # Mark merged anyway — rejected proposals are processed.
            # Future enhancement: store a rejection reason.
            if not args.dry_run:
                mark_merged(p.id, merged_by="operator-cli", commit_sha=None)
            print("  ✗ Rejected. (Marked merged so it won't reappear in the queue.)")
            rejected += 1
            continue

        # action == "accept"
        try:
            if p.kind == "review":
                msg = apply_review_to_yaml(rows, p)
                eval_dirty = True
            elif p.kind == "new_row":
                msg = apply_new_row_to_yaml(rows, p)
                eval_dirty = True
            elif p.kind == "refinement":
                msg = apply_refinement_to_yaml(rows, p)
                eval_dirty = True
            elif p.kind == "vigencia":
                msg = apply_vigencia_to_yaml(overlay_rows, p)
                overlays_dirty = True
            else:
                msg = f"unsupported kind {p.kind!r}"
                raise ValueError(msg)
        except ValueError as e:
            print(f"  ✗ Cannot apply: {e}", file=sys.stderr)
            skipped += 1
            continue

        print(f"  ✓ {msg}")
        if not args.dry_run:
            mark_merged(p.id, merged_by="operator-cli", commit_sha=None)
            print("  ✓ Marked merged in DB.")
        accepted += 1

    if eval_dirty and not args.dry_run:
        save_eval(rows, args.eval)
        print(f"\n✓ Wrote {args.eval}")
    if overlays_dirty and not args.dry_run:
        save_overlays_yaml(overlay_rows, args.overlays)
        print(f"\n✓ Wrote {args.overlays}")

    _hr(sys.stdout)
    print(f"Summary: {accepted} accepted, {rejected} rejected, {skipped} skipped.")
    if accepted > 0 and not args.dry_run:
        affected: list[Path] = []
        if eval_dirty:
            affected.append(args.eval)
        if overlays_dirty:
            affected.append(args.overlays)
        diff_paths = " ".join(str(p) for p in affected)
        print(
            f"\nNext steps:\n"
            f"   git diff {diff_paths}\n"
            f"   git commit -am 'merge phase 11.4 proposals'\n"
            f"   git push\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
