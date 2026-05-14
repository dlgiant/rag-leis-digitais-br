"""Live-fetch each document URN against the LexML resolver.

For every URN in `TIER_1`, hit `https://www.lexml.gov.br/urn/<urn>` and assert
the resolver returns a 2XX response. Throttled to ≤ 1 request/second to stay
polite to lexml.gov.br (the resolver is a public service and the corpus is
small enough that this is fine).

Marked `network` so the default `pytest` run skips it. To run explicitly:

    uv run pytest tests/test_urn_resolves.py -m network -v

Why this matters: URNs are the project's citation primary key. If a document
URN no longer resolves on the canonical LexML endpoint, citations downstream
become unverifiable. This test is the canary.
"""

from __future__ import annotations

import time

import httpx
import pytest

from rag_leis.corpus import TIER_1

RESOLVER_BASE = "https://www.lexml.gov.br/urn"
REQUEST_INTERVAL_SECONDS = 1.0
TIMEOUT_SECONDS = 30.0

USER_AGENT = (
    "Mozilla/5.0 (compatible; rag-leis-digitais-br-tests/0.1; "
    "+https://github.com/dlgiant/rag-leis-digitais-br)"
)


@pytest.mark.network
def test_every_tier1_urn_resolves() -> None:
    """Each TIER_1 document URN must return 2XX from the LexML resolver."""
    failures: list[str] = []
    with httpx.Client(
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        follow_redirects=True,
    ) as client:
        last_request_at = 0.0
        for doc in TIER_1:
            # Throttle to ≤ 1 req/sec. We measure from request *start* so the
            # interval is bounded even when the server is fast.
            elapsed = time.monotonic() - last_request_at
            if elapsed < REQUEST_INTERVAL_SECONDS:
                time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)
            last_request_at = time.monotonic()

            url = f"{RESOLVER_BASE}/{doc.urn}"
            try:
                resp = client.get(url)
            except httpx.HTTPError as e:
                failures.append(f"{doc.urn} → erro de transporte: {e!r}")
                continue

            if not (200 <= resp.status_code < 300):
                failures.append(
                    f"{doc.urn} → HTTP {resp.status_code} em {resp.url}"
                )

    assert not failures, "URNs que não resolveram:\n  " + "\n  ".join(failures)
