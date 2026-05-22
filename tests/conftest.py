"""Phase 17.3 — module-scoped dotenv loader for the test suite.

Before Phase 17.3, `rag_leis.llm` (+ `.maritaca`) called `load_dotenv()`
at module-import time. That side effect was load-bearing for tests
that transitively imported the LLM stack — they could rely on
ANTHROPIC_API_KEY, MARITACA_API_KEY, VOYAGE_API_KEY, etc., being in
`os.environ` after any `from rag_leis.* import …`. The trade-off
was test isolation breakage: a `monkeypatch.delenv("CLERK_AUDIENCE")`
followed by a later transitive `import rag_leis.llm` would re-
populate the key from `.env`, causing intermittent 401s mid-test
(see the Phase 13 fix-up comment in `tests/test_admin_endpoints.py`).

Phase 17.3 moves dotenv loading to entry points. This conftest is the
test-suite's entry point — pytest imports it before collecting any
test modules, so loading `.env` at MODULE IMPORT TIME (not in a
fixture) ensures collection-time `@pytest.mark.skipif("X" not in
os.environ, …)` decorators see the loaded env. A session-scoped
fixture is too late — fixtures run after collection.

`override=False` keeps anything already in `os.environ` (e.g., CI
secrets) in place; `.env` only fills the gaps.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Module-level — runs at conftest-import time, before collection.
# Mirrors the entry-point pattern used by `rag_leis.server`
# (lifespan), `rag_leis.run_eval`, and the scripts/ in `scripts/`.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env", override=False)
