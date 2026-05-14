from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from rag_leis.corpus import TIER_1, TIER_2, Document
from rag_leis.lexml_resolver import LexmlResolverClient, ResolverRecord
from rag_leis.planalto import PlanaltoDocument, PlanaltoScraper

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

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
) -> None:
    base = urn_to_filename(doc.urn)

    if html_doc is not None:
        raw_path = raw_dir / f"{base}.html"
        raw_path.write_text(html_doc.html, encoding="utf-8")

    meta_path = meta_dir / f"{base}.json"
    meta_path.write_text(
        json.dumps(
            {
                "urn": doc.urn,
                "title": doc.title,
                "planalto_url": doc.planalto_url,
                "lexml": {
                    "matched": record is not None,
                    "title": record.title if record else None,
                    "date": record.date if record else None,
                    "ementa": record.ementa if record else None,
                    "apelidos": list(record.apelidos) if record else [],
                    "locality": record.locality if record else None,
                    "authority": record.authority if record else None,
                    "publication_date": record.publication_date if record else None,
                    "fields": record.fields if record else {},
                },
                "html": {
                    "status_code": html_doc.status_code if html_doc else None,
                    "encoding": html_doc.encoding if html_doc else None,
                    "final_url": html_doc.final_url if html_doc else None,
                    "size_bytes": len(html_doc.html.encode("utf-8")) if html_doc else None,
                },
                "error": error,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


async def _fetch_one_tier(
    docs: tuple[Document, ...], tier_dir: str
) -> int:
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
    for doc, record, html_doc, error in results:
        write_outputs(doc, record, html_doc, error, raw_dir, meta_dir)
        if error and html_doc is None:
            marker = "[FAIL]"
            failures += 1
        elif error:
            marker = "[PARTIAL]"
        else:
            marker = "[OK]"
        size_kb = f"{len(html_doc.html.encode('utf-8')) // 1024} KB" if html_doc else "—"
        lexml_status = "✓" if record else "?"
        print(f"{marker:9} html={size_kb:>8}  lexml={lexml_status}  {doc.urn}")
        if error:
            print(f"          └─ {error}")

    print(f"Done {tier_dir}: {len(docs) - failures}/{len(docs)} downloaded.")
    print()
    return failures


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
    for t in tiers_to_run:
        docs, tier_dir = _TIERS[t]
        total_failures += await _fetch_one_tier(docs, tier_dir)

    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
