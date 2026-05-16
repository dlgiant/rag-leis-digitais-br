from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from rag_leis.corpus import TIER_1, TIER_2, Document
from rag_leis.diff_audit import (
    DiffEntry,
    append_audit_log,
    format_diff_summary,
    make_diff_entry,
    read_prior_sha256,
)
from rag_leis.lexml_resolver import LexmlResolverClient, ResolverRecord
from rag_leis.planalto import PlanaltoDocument, PlanaltoScraper

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
AUDIT_LOG = DATA_DIR / "audit" / "corpus_updates.jsonl"

_TIERS: dict[str, tuple[tuple[Document, ...], str]] = {
    "1": (TIER_1, "tier-1"),
    "2": (TIER_2, "tier-2"),
}


def urn_to_filename(urn: str) -> str:
    return urn.replace("urn:lex:", "").replace(":", "_").replace(";", "_")


async def fetch_one(
    doc: Document,
    lexml: LexmlResolverClient,
    planalto: PlanaltoScraper,
) -> tuple[Document, ResolverRecord | None, PlanaltoDocument | None, str | None]:
    record: ResolverRecord | None = None
    html_doc: PlanaltoDocument | None = None
    error: str | None = None

    record_task = asyncio.create_task(_safe_lexml(lexml, doc.urn))
    html_task = asyncio.create_task(_safe_planalto(planalto, doc.planalto_url))

    record_result, html_result = await asyncio.gather(record_task, html_task)

    if isinstance(record_result, BaseException):
        error = f"lexml: {record_result}"
    else:
        record = record_result

    if isinstance(html_result, BaseException):
        prefix = "; " if error else ""
        error = f"{error or ''}{prefix}planalto: {html_result}"
    else:
        html_doc = html_result

    return doc, record, html_doc, error


async def _safe_lexml(
    client: LexmlResolverClient, urn: str
) -> ResolverRecord | None | BaseException:
    try:
        return await client.get_by_urn(urn)
    except Exception as e:
        return e


async def _safe_planalto(scraper: PlanaltoScraper, url: str) -> PlanaltoDocument | BaseException:
    try:
        return await scraper.fetch(url)
    except Exception as e:
        return e


def write_outputs(
    doc: Document,
    record: ResolverRecord | None,
    html_doc: PlanaltoDocument | None,
    error: str | None,
    raw_dir: Path,
    meta_dir: Path,
) -> DiffEntry | None:
    """Write HTML + metadata. Returns a DiffEntry capturing whether the
    fetched HTML differs from the previously-recorded SHA-256 (Phase 7.1).
    Returns None when the fetch failed (no HTML to hash).
    """
    base = urn_to_filename(doc.urn)
    meta_path = meta_dir / f"{base}.json"

    # Phase 7.1 — compute diff vs prior fetch BEFORE overwriting metadata.
    diff: DiffEntry | None = None
    prior_sha = read_prior_sha256(meta_path)
    prior_bytes: int | None = None
    if prior_sha is not None:
        try:
            prior_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            prior_bytes = (prior_meta.get("html") or {}).get("size_bytes")
        except (json.JSONDecodeError, OSError):
            pass

    if html_doc is not None:
        raw_path = raw_dir / f"{base}.html"
        raw_path.write_text(html_doc.html, encoding="utf-8")
        diff = make_diff_entry(doc.urn, html_doc.html, prior_sha, prior_bytes)

    new_sha = diff.new_sha if diff is not None else None
    new_bytes = diff.new_bytes if diff is not None else None

    # Phase 7 fix (2026-05-16): tracked metadata must be byte-identical
    # across local + CI for the diff system to work. Two sources of
    # non-determinism removed:
    #   - LexML enrichment (rate-limited from GitHub Actions IPs)
    #   - html.size_bytes (counts the RAW response including the F5
    #     anti-bot token, which varies in length between requests).
    # What survives in tracked metadata: urn, title, planalto_url,
    # html.sha256 (SHA is over the F5-stripped body → stable).
    # Per-fetch context (status_code, final_url, encoding, size_bytes)
    # still printed inline at fetch time for human visibility but not
    # persisted to disk.
    meta_path.write_text(
        json.dumps(
            {
                "urn": doc.urn,
                "title": doc.title,
                "planalto_url": doc.planalto_url,
                "html": {
                    "sha256": new_sha,  # Phase 7.1 — canonical state of doc
                },
                "error": error,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return diff


async def _fetch_one_tier(
    docs: tuple[Document, ...], tier_dir: str
) -> tuple[int, list[DiffEntry]]:
    """Fetch a tier and return (failure_count, diff_entries) for the
    caller to aggregate into the audit log and the run-wide summary.
    """
    raw_dir = DATA_DIR / "raw" / tier_dir
    meta_dir = DATA_DIR / "metadata" / tier_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {len(docs)} documents ({tier_dir})...")
    print(f"  Raw HTML  → {raw_dir.relative_to(PROJECT_ROOT)}")
    print(f"  Metadata  → {meta_dir.relative_to(PROJECT_ROOT)}")

    async with LexmlResolverClient() as lexml, PlanaltoScraper() as planalto:
        results = await asyncio.gather(*(fetch_one(doc, lexml, planalto) for doc in docs))

    failures = 0
    diffs: list[DiffEntry] = []
    for doc, record, html_doc, error in results:
        diff = write_outputs(doc, record, html_doc, error, raw_dir, meta_dir)
        if diff is not None:
            diffs.append(diff)
        if error and html_doc is None:
            marker = "[FAIL]"
            failures += 1
        elif error:
            marker = "[PARTIAL]"
        else:
            marker = "[OK]"
        size_kb = f"{len(html_doc.html.encode('utf-8')) // 1024} KB" if html_doc else "—"
        lexml_status = "✓" if record else "?"
        # Phase 7.1 — surface diff status inline so the operator sees changes
        # as the fetch progresses (CHANGED / NEW / UNCHANGED).
        diff_tag = f" [{diff.status.upper()}]" if diff is not None else ""
        print(f"{marker:9} html={size_kb:>8}  lexml={lexml_status}{diff_tag}  {doc.urn}")
        if error:
            print(f"          └─ {error}")

    print(f"Done {tier_dir}: {len(docs) - failures}/{len(docs)} downloaded.")
    print()
    return failures, diffs


async def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Fetch Planalto HTML + LexML metadata, per Tier."
    )
    p.add_argument(
        "--tier",
        choices=["1", "2", "all"],
        default="1",
        help="Which tier's documents to fetch (default: 1, for backward compat).",
    )
    args = p.parse_args()

    tiers_to_run = ["1", "2"] if args.tier == "all" else [args.tier]
    total_failures = 0
    all_diffs: list[DiffEntry] = []
    for t in tiers_to_run:
        docs, tier_dir = _TIERS[t]
        failures, diffs = await _fetch_one_tier(docs, tier_dir)
        total_failures += failures
        all_diffs.extend(diffs)

    # Phase 7.1 — diff summary + audit log append (CHANGED+NEW only;
    # UNCHANGED docs are skipped to keep the log signal-only).
    print(format_diff_summary(all_diffs))
    appended = append_audit_log(AUDIT_LOG, all_diffs)
    if appended:
        print(f"\nAppended {appended} entries to {AUDIT_LOG.relative_to(PROJECT_ROOT)}")

    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
