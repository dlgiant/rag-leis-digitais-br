"""URN validity for chunks on disk.

Walks every JSONL under `data/chunks/**` and verifies that:

  1. `document_urn` matches the LexML URN LEX shape (RFC 9676): `urn:lex:<jurisdição>:<autoridade>:<tipo>:<data>;<id>`.
  2. `document_urn` is one of the canonical TIER_1 documents (no orphan corpora slipped in).
  3. `partition` is a ';'-separated chain of valid segments (`adct`, `artN[-X]`, `parN`, `incN`, `ali-X`, `itemN`).
  4. `urn` == `f"{document_urn}~{partition}"` — the on-disk URN is consistent with its parts.
  5. URNs are globally unique.
  6. When `parent_partition` is set, that partition exists in the same document.
  7. `kind` matches the last segment of the partition.

These are corpus-level invariants — the test reads the chunks themselves (not the parser), so it stays valid across parser refactors.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from rag_leis.corpus import TIER_1, TIER_2, TIER_3, TIER_4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"

# urn:lex:<jurisdição>:<autoridade>:<tipo>:<YYYY-MM-DD>;<id>
# jurisdição: 'br' opcionalmente seguido de ';<unidade>'
# autoridade/tipo: tokens com pontos (ex.: 'decreto.lei', 'autoridade.nacional.protecao.dados')
# Forma 1: legislação — sempre tem data + id
# Forma 2: jurisprudência tipo 'tema' STF — id universal sem data (`tema:786`)
DOC_URN_RE = re.compile(
    r"^urn:lex:"
    r"br(?:;[a-z0-9._-]+)*:"        # jurisdição
    r"[a-z0-9._-]+:"                # autoridade
    r"[a-z0-9._-]+:"                # tipo (lei, decreto, sumula.vinculante, tema, ...)
    r"(?:\d{4}-\d{2}-\d{2};)?"      # data ISO opcional (Phase 6 — tema STF dispensa)
    r"[A-Za-z0-9._-]+$"             # identificador
)

PARTITION_SEGMENT_RE = re.compile(
    r"^(?:adct"
    r"|art\d+(?:-[a-z])?"
    r"|par\d+"
    r"|inc\d+"
    r"|ali-[a-z]"
    r"|item\d+"
    # Phase 6 — jurisprudência: chunks atômicos (uma tese / um enunciado / uma ementa).
    r"|tese"
    r"|enunciado"
    r"|ementa)$"
)

# Maps the partition segment prefix to the expected `kind` value.
_KIND_BY_TAIL = (
    (re.compile(r"^art\d+(?:-[a-z])?$"), "artigo"),
    (re.compile(r"^par\d+$"), "paragrafo"),
    (re.compile(r"^inc\d+$"), "inciso"),
    (re.compile(r"^ali-[a-z]$"), "alinea"),
    (re.compile(r"^item\d+$"), "item"),
    # Phase 6 — jurisprudência atômica.
    (re.compile(r"^(?:tese|enunciado|ementa)$"), "jurisprudencia"),
)

KNOWN_DOC_URNS = (
    {d.urn for d in TIER_1}
    | {d.urn for d in TIER_2}
    | {d.urn for d in TIER_3}
    | {d.urn for d in TIER_4}
)


@pytest.fixture(scope="module")
def chunks() -> list[tuple[Path, int, dict[str, Any]]]:
    rows: list[tuple[Path, int, dict[str, Any]]] = []
    for jsonl in sorted(CHUNKS_DIR.glob("**/*.jsonl")):
        with jsonl.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                rows.append((jsonl, lineno, json.loads(line)))
    if not rows:
        pytest.skip(f"Sem chunks em {CHUNKS_DIR} (rode parse_all_tier antes).")
    return rows


def _fmt(violations: list[str], limit: int = 20) -> str:
    head = "\n  ".join(violations[:limit])
    tail = f"\n  … (+{len(violations) - limit} mais)" if len(violations) > limit else ""
    return f"\n  {head}{tail}"


def test_document_urn_format(chunks):
    bad = [
        f"{p.name}:{n} → {obj['document_urn']!r}"
        for p, n, obj in chunks
        if not DOC_URN_RE.match(obj["document_urn"])
    ]
    assert not bad, f"document_urn fora do padrão LexML:{_fmt(bad)}"


def test_document_urn_is_in_tier1(chunks):
    unknown = sorted({
        obj["document_urn"]
        for _, _, obj in chunks
        if obj["document_urn"] not in KNOWN_DOC_URNS
    })
    assert not unknown, (
        "document_urn fora do conjunto TIER_1∪TIER_2 — corpus contém doc desconhecido:\n  "
        + "\n  ".join(unknown)
    )


def test_partition_is_well_formed(chunks):
    bad: list[str] = []
    for p, n, obj in chunks:
        partition = obj["partition"]
        if not partition:
            bad.append(f"{p.name}:{n} → partition vazia")
            continue
        for seg in partition.split(";"):
            if not PARTITION_SEGMENT_RE.match(seg):
                bad.append(f"{p.name}:{n} → segmento {seg!r} em {partition!r}")
                break
    assert not bad, f"partition mal-formada:{_fmt(bad)}"


def test_chunk_urn_matches_doc_plus_partition(chunks):
    mismatches = [
        f"{p.name}:{n} → urn={obj['urn']!r} esperado={obj['document_urn']}~{obj['partition']}"
        for p, n, obj in chunks
        if obj["urn"] != f"{obj['document_urn']}~{obj['partition']}"
    ]
    assert not mismatches, f"urn != document_urn~partition:{_fmt(mismatches)}"


def test_urns_are_unique(chunks):
    seen: dict[str, tuple[Path, int]] = {}
    dupes: list[str] = []
    for p, n, obj in chunks:
        urn = obj["urn"]
        if urn in seen:
            prev_p, prev_n = seen[urn]
            dupes.append(f"{urn!r}: {prev_p.name}:{prev_n} & {p.name}:{n}")
        else:
            seen[urn] = (p, n)
    assert not dupes, f"URNs duplicadas:{_fmt(dupes)}"


def test_parent_partition_resolves(chunks):
    by_doc: dict[str, set[str]] = {}
    for _, _, obj in chunks:
        by_doc.setdefault(obj["document_urn"], set()).add(obj["partition"])

    orphans = [
        f"{p.name}:{n} → parent={obj['parent_partition']!r} ausente em {obj['document_urn']}"
        for p, n, obj in chunks
        if obj.get("parent_partition") is not None
        and obj["parent_partition"] not in by_doc.get(obj["document_urn"], set())
    ]
    assert not orphans, f"parent_partition aponta para chunk inexistente:{_fmt(orphans)}"


def test_kind_matches_partition_tail(chunks):
    mismatches: list[str] = []
    for p, n, obj in chunks:
        tail = obj["partition"].rsplit(";", 1)[-1]
        expected = next((k for rx, k in _KIND_BY_TAIL if rx.match(tail)), None)
        if expected is None:
            # 'adct' as a standalone partition is a prefix marker, not a chunk.
            # Any chunk emitted on disk should have a typed tail; flag if not.
            mismatches.append(f"{p.name}:{n} → tail {tail!r} não tem kind esperado")
            continue
        if obj["kind"] != expected:
            mismatches.append(
                f"{p.name}:{n} → kind={obj['kind']!r} mas tail={tail!r} sugere {expected!r}"
            )
    assert not mismatches, f"kind diverge da partition:{_fmt(mismatches)}"
