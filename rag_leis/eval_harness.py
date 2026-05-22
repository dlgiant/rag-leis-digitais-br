from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from rag_leis.embeddings import Embedder, Vec
from rag_leis.legal_rank import DEFAULT_RANK, effective_legal_rank
from rag_leis.vigencia import Vigencia

# Phase 5.7: Emenda Constitucional reference patterns in chunk.notes.
# Parser already strips "(Incluído pela EC nº X, de YYYY)" / "(Redação dada
# pela EC nº X, de YYYY)" into the notes list at parse time. This regex
# extracts the EC number+year into a structured form.
_EC_NOTE_RE = re.compile(
    r"(?:Inclu[ií]d[ao] pela|Reda[çc][ãa]o dada pela)\s+"
    r"Emenda Constitucional\s+n[º°o]?\s*"
    r"(\d+)\s*,\s*de\s*(\d{4})",
    re.IGNORECASE,
)


def _extract_amended_by(notes: list[str]) -> list[str]:
    """Parse parser-emitted notes for Emenda Constitucional references.

    Returns short tokens like ["EC-115/2022", "EC-45/2004"] sorted by year
    descending (most recent amendment first). Empty list when no EC
    references found — covers original CF/88 dispositivos and
    non-constitutional documents.
    """
    out: list[tuple[int, int, str]] = []
    for note in notes:
        for m in _EC_NOTE_RE.finditer(note):
            num = int(m.group(1))
            year = int(m.group(2))
            token = f"EC-{num}/{year}"
            out.append((year, num, token))
    # Sort: most recent year first, ties by EC number desc
    out.sort(key=lambda t: (-t[0], -t[1]))
    # Dedup preserving order
    seen: set[str] = set()
    result: list[str] = []
    for _, _, tok in out:
        if tok not in seen:
            seen.add(tok)
            result.append(tok)
    return result


@dataclass(frozen=True)
class IndexChunk:
    urn: str
    text: str
    nav_text: str
    caput_text: str  # concatenation of all ancestor caput texts (artigo→…→parent), "" for top-level chunks
    citation: str  # joined label chain ("Art. 7, I" / "Art. 18, § 2") — empty for top-level if label missing
    vigencia: Vigencia | None = None  # overlay metadata; None means default "vigente"
    # Brazilian normative hierarchy rank (1=CF, 5=infralegal). Computed
    # from the document URN type at load time. Used by RAGPipeline to
    # detect when the LLM cites lower-rank sources while higher-rank
    # ones were available in top-K.
    legal_rank: int = DEFAULT_RANK
    # Phase 5.5: ISO date (YYYY-MM-DD) the document's chunks were last
    # updated on disk. Computed from the JSONL file's mtime as a proxy
    # for the fetch+parse date. Used by RAGPipeline to render
    # "consultado em DD/MM/AAAA" footers — practitioner transparency.
    fetched_at: str = ""
    # Phase 5.7: Emendas Constitucionais que introduziram ou alteraram o
    # dispositivo. Empty for original CF text and non-CF documents.
    # Extracted from chunk.notes at load time (parser already strips
    # "(Incluído pela EC nº X)" patterns into notes).
    amended_by: tuple[str, ...] = ()
    # Phase 6.6 r4 (post-audit): document title (e.g., "Marco Civil da
    # Internet (Lei 12.965/2014)") looked up from corpus.py TIER lists by
    # document_urn. Used only by the `title+...` text-mode to disambiguate
    # cross-corpus literal-article-number collisions (MISS 2: art.13 MCI vs
    # Decreto 8.771 art.13). Empty when document not in any TIER (e.g.,
    # synthetic test fixtures).
    document_title: str = ""
    # Phase 17.6 — when this chunk's document is a regulamento (decreto,
    # resolução) that implements a parent lei, these carry the parent
    # lei's URN + human-readable label. Empty for original legislation
    # and for regulamentos not yet in the registry.
    # Rendered as `regulamenta_urn=` + `regulamenta_label=` attributes
    # on the `<fonte>` tag by rag.py:_build_context. The SYSTEM_PROMPT
    # (rule 7) tells the LLM not to refuse on an orphaned regulamento
    # — the registry entry tells it explicitly that the parent lei
    # exists, even though the parent lei's chunks aren't necessarily
    # in the retrieved context. Structural fix for the Decreto-8.771-
    # class false-refusal that sabia-4 currently masks.
    regulamenta_urn: str = ""
    regulamenta_label: str = ""


@dataclass(frozen=True)
class Query:
    query: str
    core: frozenset[str]
    supporting: frozenset[str] = frozenset()
    qtype: str | None = None
    notes: str | None = None

    @property
    def relevant(self) -> frozenset[str]:
        # Union of graded levels — for binary metrics (recall, MRR) and back-compat.
        return self.core | self.supporting

    def relevance_of(self, urn: str) -> int:
        if urn in self.core:
            return 2
        if urn in self.supporting:
            return 1
        return 0


def _locate_fetched_at_registry(chunks_dir: Path) -> Path | None:
    """Phase 16.1 — auto-discover data/metadata/fetched_at.json by
    walking up from the chunks dir. Mirrors the overlays discovery
    pattern below so callers don't have to thread an extra path."""
    for ancestor in [chunks_dir, *chunks_dir.parents]:
        candidate = ancestor / "metadata" / "fetched_at.json"
        if candidate.exists():
            return candidate
    return None


def _locate_regulamentation_targets_registry(chunks_dir: Path) -> Path | None:
    """Phase 17.6 — auto-discover data/metadata/regulamentation_targets.json
    using the same walk-up pattern as the fetched_at registry. Returns
    None when the file isn't present; callers degrade to empty mapping
    (no regulamento chunks get their parent-lei attribute, which is the
    pre-17.6 behavior — non-breaking on fresh checkouts)."""
    for ancestor in [chunks_dir, *chunks_dir.parents]:
        candidate = ancestor / "metadata" / "regulamentation_targets.json"
        if candidate.exists():
            return candidate
    return None


def load_chunks(
    chunks_dir: Path,
    min_text_chars: int = 10,
    overlays_path: Path | None = None,
) -> list[IndexChunk]:
    """Load all chunks from `chunks_dir`, recursively.

    Accepts either a tier-specific dir (`data/chunks/tier-1`, legacy) or the
    chunks root (`data/chunks/`). Uses rglob so multi-tier layouts work
    transparently without callers touching paths.

    If `overlays_path` is provided (or the canonical path
    `data/vigencia/overlays.yaml` exists relative to the chunks dir), each
    matching chunk is annotated with its `Vigencia` record so downstream
    rendering can flag sub-judice / suspenso / etc. dispositivos.
    """
    # First pass: read all raw rows (before the empty-chunk filter) into a urn→row
    # map. We need the unfiltered set because a child's caput may itself be too
    # short to index (e.g. an artigo whose body is a colon and a list) but still
    # carries the parent context for its children.
    raw_by_urn: dict[str, dict[str, Any]] = {}
    # Phase 5.5 + 16.1: per-document fetched_at. Primary source is the
    # registry at data/metadata/fetched_at.json written by fetch_tier.py
    # on each successful HTTP fetch. Falls back to JSONL mtime when the
    # registry is absent (fresh checkouts) or doesn't cover a doc.
    import datetime as _dt

    fetched_at_by_doc: dict[str, str] = {}
    # Phase 16.1 — prefer the explicit fetched_at registry written by
    # fetch_tier.py over JSONL mtime. mtime is an unreliable proxy because
    # Docker COPY resets it to image-build time, causing the production
    # footer to report the deploy date instead of the actual Planalto
    # fetch date. The registry survives the rebuild because its content
    # (not its timestamp) carries the truth.
    registry_path = _locate_fetched_at_registry(chunks_dir)
    if registry_path is not None and registry_path.exists():
        try:
            fetched_at_by_doc = json.loads(registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            fetched_at_by_doc = {}
    for jsonl in sorted(chunks_dir.rglob("*.jsonl")):
        mtime = jsonl.stat().st_mtime
        date_iso = _dt.date.fromtimestamp(mtime).isoformat()
        with jsonl.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                raw_by_urn[obj["urn"]] = obj
                # mtime fallback: only fill when the registry didn't carry
                # this document. Once the registry catches up across all
                # tiers, the fallback is dead code — kept here as a graceful
                # degradation path for fresh checkouts.
                fetched_at_by_doc.setdefault(obj["document_urn"], date_iso)

    def _resolve_caput_chain(obj: dict[str, Any]) -> str:
        parent_part = obj.get("parent_partition")
        if not parent_part:
            return ""
        parts: list[str] = []
        doc_urn: str = obj["document_urn"]
        cur_part: str | None = parent_part
        # Walk up; cap at 8 levels as a safety net (artigo→§→inciso→alínea→item is 5).
        for _ in range(8):
            if cur_part is None:
                break
            parent_urn = f"{doc_urn}~{cur_part}"
            parent = raw_by_urn.get(parent_urn)
            if parent is None:
                break
            parts.append(parent["text"])
            cur_part = parent.get("parent_partition")
        # Outermost (artigo caput) first → innermost last, matching reading order.
        return " ".join(reversed(parts))

    def _resolve_citation(obj: dict[str, Any]) -> str:
        """Join this chunk's label with its ancestors' labels, outermost-first.

        Output: "Art. 7, I" / "Art. 18, § 2, III" / "Art. 7" (top-level artigo).
        Empty for chunks without any label in the chain.
        """
        labels: list[str] = []
        doc_urn: str = obj["document_urn"]
        cur: dict[str, Any] | None = obj
        for _ in range(8):
            if cur is None:
                break
            lbl = cur.get("label")
            if lbl:
                labels.append(lbl)
            parent_part = cur.get("parent_partition")
            if not parent_part:
                break
            cur = raw_by_urn.get(f"{doc_urn}~{parent_part}")
        return ", ".join(reversed(labels))

    from rag_leis.chunks import is_revoked_text
    from rag_leis.corpus import TIER_1, TIER_2, TIER_3, TIER_4
    from rag_leis.vigencia import load_overlays

    # urn → title lookup for title-prefix text-modes. Built once per
    # load_chunks call. Tier-4 jurisprudência titles come from TIER_4.
    title_by_doc_urn: dict[str, str] = {
        d.urn: d.title for d in (*TIER_1, *TIER_2, *TIER_3, *TIER_4)
    }

    # Phase 17.6 — load regulamentation_targets registry (doc-level
    # mapping of regulamento_urn → {regulamenta_urn, regulamenta_label}).
    # Empty dict when registry is absent; chunks degrade to empty
    # regulamenta_* fields (pre-17.6 behavior). Underscore-prefixed
    # entries in the JSON are documentation comments and are filtered
    # out at load time.
    reg_targets_by_doc: dict[str, dict[str, str]] = {}
    reg_registry_path = _locate_regulamentation_targets_registry(chunks_dir)
    if reg_registry_path is not None and reg_registry_path.exists():
        try:
            raw_reg = json.loads(reg_registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw_reg = {}
        # Filter out leading-underscore documentation keys; keep only
        # entries whose value is a mapping with the required fields.
        for k, v in raw_reg.items():
            if k.startswith("_") or not isinstance(v, dict):
                continue
            tgt_urn = v.get("regulamenta_urn", "")
            tgt_label = v.get("regulamenta_label", "")
            if tgt_urn and tgt_label:
                reg_targets_by_doc[k] = {
                    "urn": tgt_urn,
                    "label": tgt_label,
                }

    # Load overlays from explicit path, or auto-discover the canonical
    # location relative to this project. Empty dict if file absent — fresh
    # checkouts shouldn't crash.
    if overlays_path is None:
        # chunks_dir is typically <project>/data/chunks (or a child of it).
        # Walk up to the data/ ancestor and look for vigencia/overlays.yaml.
        for ancestor in [chunks_dir, *chunks_dir.parents]:
            candidate = ancestor / "vigencia" / "overlays.yaml"
            if candidate.exists():
                overlays_path = candidate
                break
    overlays = load_overlays(overlays_path) if overlays_path else {}

    out: list[IndexChunk] = []
    for obj in raw_by_urn.values():
        # Skip placeholders (revogado/vetado/suprimido/stub). Prefer the explicit
        # `is_revoked` flag set at parse time; fall back to text-pattern detection
        # for JSONL written before the flag existed.
        if obj.get("is_revoked", False) or is_revoked_text(obj["text"]):
            continue
        # Phase 16.3 — exclude Tier-4 stub Temas (e.g. 533/815/987) whose
        # `notes` flag the chunk's `text` as a curator summary, not the
        # verbatim STF tese. The chunks document their own hallucination
        # risk ("Confabulação esperada: LLM pode citar este chunk como se
        # fosse a tese") yet earlier gold pinned them as relevant. Gated
        # on D7 verbatim transcription (Phase 19.1).
        notes_list = obj.get("notes") or []
        if any(isinstance(n, str) and n.startswith("PENDENTE_") for n in notes_list):
            continue
        nav = obj.get("nav") or {}
        nav_text = " > ".join(_normalize_nav_casing(v) for v in nav.values() if v)
        caput_text = _resolve_caput_chain(obj)
        citation = _resolve_citation(obj)
        reg_tgt = reg_targets_by_doc.get(obj["document_urn"])
        out.append(
            IndexChunk(
                urn=obj["urn"],
                text=obj["text"],
                nav_text=nav_text,
                caput_text=caput_text,
                citation=citation,
                vigencia=overlays.get(obj["urn"]),
                legal_rank=effective_legal_rank(obj["document_urn"], obj.get("nav") or {}),
                fetched_at=fetched_at_by_doc.get(obj["document_urn"], ""),
                amended_by=tuple(_extract_amended_by(obj.get("notes", []))),
                document_title=title_by_doc_urn.get(obj["document_urn"], ""),
                regulamenta_urn=(reg_tgt or {}).get("urn", ""),
                regulamenta_label=(reg_tgt or {}).get("label", ""),
            )
        )
    return out


# Nav values from Planalto come in mixed casing: capítulos are usually ALL-UPPER
# ("I - DISPOSIÇÕES GERAIS"), seções/subseções are Title Case ("I - Da Digitalização").
# That inconsistency leaks into the embedded surface form (label+nav+caput+text),
# adding noise. Normalize ALL-UPPER segments to Title Case at load time;
# leave mixed-case alone. Independent from chunk text (we don't touch obj["text"]).
_PT_LOWERCASE_WORDS = frozenset(
    {"de", "da", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos",
     "com", "para", "por", "ou", "a", "o", "as", "os", "à", "às", "ao", "aos"}
)


def _normalize_nav_casing(value: str) -> str:
    """If `value` is mostly uppercase, convert to Portuguese Title Case.

    - Single uppercase letters and Roman numerals stay uppercase.
    - Connectives (de/da/do/das/dos/e/em/na/no/com/para/por) stay lowercase
      unless they're the first token.
    - Mixed-case input is left untouched.
    """
    alpha = [c for c in value if c.isalpha()]
    if not alpha:
        return value
    upper_ratio = sum(c.isupper() for c in alpha) / len(alpha)
    if upper_ratio < 0.7:
        return value  # already mixed/title case; don't touch.

    out_tokens: list[str] = []
    just_after_dash = False
    for i, tok in enumerate(value.split()):
        if not tok:
            continue
        # Preserve Roman numerals (II, III, IV, ..., LXXIX, etc.) and dashes.
        if all(c in "IVXLCDM-" for c in tok):
            just_after_dash = "-" in tok
            out_tokens.append(tok)
            continue
        lower = tok.lower()
        # Lowercase connectives unless they're the first content word OR they
        # follow a "-" delimiter (e.g. "I - Dos Princípios" should keep "Dos"
        # capitalized).
        if i > 0 and not just_after_dash and lower in _PT_LOWERCASE_WORDS:
            out_tokens.append(lower)
        else:
            out_tokens.append(lower[:1].upper() + lower[1:])
        just_after_dash = False
    return " ".join(out_tokens)


def load_queries(path: Path) -> list[Query]:
    raw: list[dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[Query] = []
    for item in raw:
        rel = item["relevant"]
        if isinstance(rel, list):
            # v1 (binary) schema — flat URN list. All gold treated as core (rel=2).
            core = frozenset(rel)
            supporting: frozenset[str] = frozenset()
        else:
            core = frozenset(rel.get("core", []))
            supporting = frozenset(rel.get("supporting", []))
        out.append(
            Query(
                query=item["query"],
                core=core,
                supporting=supporting,
                qtype=item.get("type"),
                notes=item.get("notes"),
            )
        )
    return out


def format_texts(chunks: list[IndexChunk], mode: str) -> list[str]:
    if mode == "text":
        return [c.text for c in chunks]
    if mode == "nav+text":
        return [f"{c.nav_text} :: {c.text}" if c.nav_text else c.text for c in chunks]
    if mode == "caput+text":
        return [f"{c.caput_text} {c.text}".strip() if c.caput_text else c.text for c in chunks]
    if mode == "nav+caput+text":
        out: list[str] = []
        for c in chunks:
            body = f"{c.caput_text} {c.text}".strip() if c.caput_text else c.text
            out.append(f"{c.nav_text} :: {body}" if c.nav_text else body)
        return out
    if mode == "label+nav+caput+text":
        # Prefixes the chunk's citation chain ("Art. 7, I") so that literal
        # article references in queries have an explicit token to match.
        out = []
        for c in chunks:
            body = f"{c.caput_text} {c.text}".strip() if c.caput_text else c.text
            mid = f"{c.nav_text} :: {body}" if c.nav_text else body
            out.append(f"{c.citation} :: {mid}" if c.citation else mid)
        return out
    if mode == "title+label+nav+caput+text":
        # Phase 6.6 r4: prefixes the document title (e.g., "Marco Civil da
        # Internet (Lei 12.965/2014)") to disambiguate cross-corpus literal
        # article-number collisions — the canonical MISS case is "art.13 do
        # Marco Civil" returning Decreto 8.771 art.13 (regulamento) instead
        # of MCI art.13 (lei). Title-prefix gives the dense embedder explicit
        # lei-vs-decreto signal at the start of every chunk.
        out = []
        for c in chunks:
            body = f"{c.caput_text} {c.text}".strip() if c.caput_text else c.text
            mid = f"{c.nav_text} :: {body}" if c.nav_text else body
            tail = f"{c.citation} :: {mid}" if c.citation else mid
            out.append(f"{c.document_title} :: {tail}" if c.document_title else tail)
        return out
    raise ValueError(f"Unknown text mode: {mode!r}")


def build_index(
    chunks: list[IndexChunk], embedder: Embedder, mode: str = "text"
) -> tuple[list[str], Vec]:
    texts = format_texts(chunks, mode)
    vecs = embedder.embed_docs(texts)
    urns = [c.urn for c in chunks]
    return urns, vecs


def search(query_vec: Vec, doc_vecs: Vec, k: int) -> list[int]:
    # Vectors are L2-normalized at index time → dot product = cosine similarity.
    sims = doc_vecs @ query_vec
    return list(np.argsort(-sims)[:k])


def recall_at_k(retrieved: list[str], relevant: frozenset[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for r in retrieved[:k] if r in relevant)
    return hits / len(relevant)


def ndcg_at_k(
    retrieved: list[str],
    gold: frozenset[str] | dict[str, int] | Query,
    k: int,
) -> float:
    """Normalized DCG with graded relevance (2^rel - 1 gain).

    `gold` accepts three forms for caller convenience:
      * frozenset[str] (legacy): every URN is treated as rel=1 (gain=1) —
        reduces to the binary nDCG formula since the gain factor cancels in
        the DCG/IDCG ratio.
      * dict[str, int]: explicit URN→relevance-level mapping.
      * Query: uses Query.core (rel=2) and Query.supporting (rel=1).
    """
    if isinstance(gold, Query):
        rels: dict[str, int] = {urn: 2 for urn in gold.core}
        for urn in gold.supporting:
            rels.setdefault(urn, 1)
    elif isinstance(gold, frozenset):
        rels = {urn: 1 for urn in gold}
    else:
        rels = dict(gold)

    dcg = 0.0
    for i, urn in enumerate(retrieved[:k]):
        rel = rels.get(urn, 0)
        if rel > 0:
            dcg += (2**rel - 1) / math.log2(i + 2)

    ideal = sorted(rels.values(), reverse=True)[:k]
    idcg = sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(ideal) if rel > 0)
    return dcg / idcg if idcg > 0 else 0.0


def mrr_at_k(retrieved: list[str], relevant: frozenset[str], k: int) -> float:
    for i, r in enumerate(retrieved[:k]):
        if r in relevant:
            return 1.0 / (i + 1)
    return 0.0
