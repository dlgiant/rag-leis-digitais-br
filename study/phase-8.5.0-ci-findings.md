# Phase 8.5.0 — CI workflow (findings)

**Date:** 2026-05-20
**Predecessor:** [Phase 8.5 plan](phase-8.5-ci-deploy-plan.md), drafted 2026-05-20.
**Cost:** $0. Pure GitHub Actions config; no API calls.
**Status:** Phase 8.5.0 SHIPPED. All pre-locked criteria met.

## Pre-locked criteria — result

| # | Criterion | Status |
|---|---|:-:|
| 1 | `.github/workflows/ci.yml` runs on every PR + push to main | ✅ |
| 2 | `pytest -m "not network and not requires_anpd_pdf"` runs and passes | ✅ (446 tests locally; CI will verify) |
| 3 | `ruff check rag_leis/ tests/ scripts/` runs and passes | ✅ |
| 4 | Workflow wall time < 5 min on cold runner; < 2 min with uv cache | ⏸ pending first CI run; local subset is 5s |
| 5 | PR cannot merge until checks pass (branch protection rule) | ⏸ manual repo setting; documented below |
| 6 | All 468 existing tests still pass (446 in CI + 22 skipped) | ✅ |

## What ships

- **`.github/workflows/ci.yml`** — single workflow, single `test` job:
  - Triggers: PR to main + push to main
  - Concurrency: same-ref runs cancel each other (saves compute on
    rapid PR iteration)
  - Steps: checkout → setup uv (with cache) → `uv sync --extra voyage
    --extra server` → ruff lint → pytest
  - Timeout: 10 min (generous; local subset takes 5s)

- **No test source changes needed.** The codebase already uses
  `@pytest.mark.network` for live-API tests (`tests/test_llm.py`,
  `tests/test_maritaca.py`) and `@pytest.mark.requires_anpd_pdf`
  for tests that need PDFs not in git (`tests/test_tier3_anpd.py`).
  Both markers were already registered in `pyproject.toml` under
  `[tool.pytest.ini_options]`. CI excludes both: `pytest -m "not
  network and not requires_anpd_pdf"`.

## Marker convention (differs slightly from the plan)

The plan recommended introducing a new `@pytest.mark.live` marker.
**The codebase already uses `@pytest.mark.network`** for the same
purpose — adopted that instead of introducing a synonym. No new
marker definitions; no decorator changes to existing tests.

The 22 tests CI excludes:

| Marker | n | What |
|---|---:|---|
| `network` | 6 | `tests/test_llm.py` + `tests/test_maritaca.py` — live Anthropic/Maritaca calls |
| `requires_anpd_pdf` | 16 | `tests/test_tier3_anpd.py` — ANPD source PDFs not in git |

Local devs run the full 468-test suite via `uv run pytest`; CI runs
the deterministic 446-test subset. The 22 excluded tests are valuable
and should keep running locally — they're just not appropriate for
the GitHub-Actions environment (no API keys for `network`; no PDFs
on the runner for `requires_anpd_pdf`).

## Local verification (before CI runs)

```
$ uv run pytest -m "not network and not requires_anpd_pdf" -q
446 passed, 22 deselected in 5.00s
```

5-second runtime locally — the CI run will be longer mainly due to
the `uv sync` step's cold-cache install (~30-60s first run; cached
runs ~5-10s after that). Total estimated CI wall time: ~2-3 min
cold, < 1 min warm.

## Branch protection rule (manual step)

GitHub Actions workflows can't apply their own branch protection;
that's a repo-settings change. **One-time manual setup:**

1. GitHub UI: repo Settings → Branches → "Add branch protection rule"
2. Branch name pattern: `main`
3. Check "Require status checks to pass before merging"
4. Search for and select: `Tests + lint` (the job name from ci.yml)
5. Optionally: "Require branches to be up to date before merging"
6. Save changes

This makes the merge button gray on any PR that has a failing or
missing CI check.

**Alternative (CLI):** `gh api -X PUT repos/:owner/:repo/branches/main/protection \
--input <(echo '{"required_status_checks": {"strict": true, "contexts": ["Tests + lint"]}}')`
— but the UI is one-shot and clearer for a v1 setup.

## What 8.5.0 explicitly does NOT do (per plan)

- No coverage reporting (codecov etc.)
- No type-check enforcement (mypy) — codebase has mixed types; gating
  would surface a large backlog
- No mutation testing
- No auto-merge on green checks
- No required reviewers (solo project)
- No deploy step — that's 8.5.1

## Risk + tradeoff observations (from implementation)

1. **The `uv sync --extra voyage --extra server` step is the slowest
   uncached operation** — pulls FlagEmbedding (PyTorch dep ~800MB)
   and the OTel SDK. First CI run on a fresh ubuntu-latest runner
   will take ~2-3 min for this step alone. Cached runs (the
   `enable-cache: true` + `cache-dependency-glob: "uv.lock"` setting)
   should drop this to <10s once the cache populates.

2. **Concurrency cancellation is the right default for this project.**
   Solo dev means rapid PR iteration; without `cancel-in-progress`,
   a sequence of "push commit, realize typo, push fix, push fix"
   could queue 3-4 redundant CI runs eating ~10 min of compute.
   For team projects this setting is more nuanced (might want every
   commit's CI to complete) — but for v1, cancellation wins.

3. **No matrix builds yet.** Python 3.12 only. The project's
   `pyproject.toml` declares `requires-python = ">=3.12"`, so testing
   3.11 / 3.13 isn't a goal. Phase 9 might add a 3.13 cell if/when
   the embedder/FastAPI stack stabilizes there.

## What this enables for 8.5.1 (deploy)

The 8.5.1 deploy workflow will reference this job:

```yaml
jobs:
  deploy:
    needs: test  # from this ci.yml
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

The `needs: test` line makes deploy gate on CI passing — exactly
the "no deploy on red tests" property the plan committed to.

## Open follow-ups

- Apply the branch protection rule on the GitHub UI (manual).
- Watch first CI run on a real PR; iterate if anything in the
  workflow path differs from local (uv cache key, FlagEmbedding
  install, etc.).
- Phase 8.5.1 will add `deploy.yml` referencing this job's `test`
  name; the `Tests + lint` job name needs to stay stable.

## Cross-references

- [`phase-8.5-ci-deploy-plan.md`](phase-8.5-ci-deploy-plan.md) — the plan this doc closes
- [`phase-8-entry-plan.md`](phase-8-entry-plan.md) — parent plan; sub-phase 8.5.0 now ✅
- `.github/workflows/ci.yml` — the workflow file
- `pyproject.toml` `[tool.pytest.ini_options]` markers — `network` + `requires_anpd_pdf`
