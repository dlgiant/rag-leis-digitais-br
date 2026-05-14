"""Cite-and-verify post-check for RAG answers.

A citation is **verified** iff its URN:

1. Exists in the corpus (we have an indexed chunk for it), AND
2. Was in the top-K context shown to the LLM for this query.

(1) catches outright hallucinations (made-up article numbers). (2) catches
the subtler failure mode where the LLM cites a real chunk that wasn't in
context — meaning it's drawing on training data, not the retrieved sources.

Policy: rejected citations are stripped from the final answer (not removed
from the answer prose) and surfaced in `RAGAnswer.rejected_citations` for
caller inspection. We don't refuse the whole answer on a single rejection —
that turns out too brittle when the LLM speculates on a marginal cite — but
the rejected count is a confidence signal a downstream UI should expose.
"""

from __future__ import annotations


def verify_citations(
    cited: list[str],
    retrieved_urns: frozenset[str],
    corpus_urns: frozenset[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Split `cited` into (verified, rejected).

    Rejection reasons:
      * "not-in-corpus" — URN doesn't resolve to any chunk we know about.
      * "not-in-context" — URN exists but wasn't in the top-K shown to the
        model on this query.

    Order in `verified` follows the order in `cited` (preserves any
    LLM-chosen citation ordering). Duplicates in `cited` are de-duplicated
    in `verified` but each occurrence shows up in `rejected` if invalid.
    """
    verified: list[str] = []
    seen: set[str] = set()
    rejected: list[tuple[str, str]] = []
    for u in cited:
        if u not in corpus_urns:
            rejected.append(("not-in-corpus", u))
        elif u not in retrieved_urns:
            rejected.append(("not-in-context", u))
        elif u in seen:
            continue
        else:
            verified.append(u)
            seen.add(u)
    return verified, rejected
