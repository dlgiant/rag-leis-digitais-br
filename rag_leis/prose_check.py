"""Prose-citation verification — close the gap between cited URNs and
the human-rendered citations in the answer text.

Reviewer round 2 item 6: `verify_citations()` checks the JSON
`citations[]` URN list against the corpus + top-K context. But the
`answer` prose can say "Art. 5º, **XII**" while the URN is `art5;inc10`.
The reader sees "XII"; the verifier never knew. That's an unmonitored
hallucination surface.

This module:

  1. **Extracts** structured citations from prose
     (Art. N, § M, Roman, alínea letter)
  2. **Maps** each prose citation to its expected URN partition path
     (e.g., "Art. 5, XII" → "art5;inc12")
  3. **Cross-checks** against the verified citations: each prose
     reference must match the suffix of at least one cited URN
  4. **Surfaces mismatches** as ProseMismatch records — the pipeline
     uses them to trigger reject-and-reprompt (Phase 5.3.c) and the
     final RAGAnswer carries them for downstream observability

Disambiguation: "Art. 5, XII" alone is ambiguous (CF? LGPD? CDC?). The
disambiguation comes from the verified citations list — we compute
the expected partition and look for it as the URN suffix among the
URNs the model already cited. If none match, the prose is wrong
relative to the structured contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Roman numeral patterns up to LXXXIX (standard CF/LGPD ranges easily fit)
_ROMAN_MAP: dict[str, int] = {}
for i in range(1, 100):
    n = i
    s = ""
    for value, numeral in [
        (90, "XC"), (50, "L"), (40, "XL"), (10, "X"),
        (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]:
        while n >= value:
            s += numeral
            n -= value
    _ROMAN_MAP[s] = i


def roman_to_int(s: str) -> int | None:
    return _ROMAN_MAP.get(s.upper())


# --- Extraction regex ---
# Matches: "Art. 5", "Art. 5º", "art. 154-A", "Art. 5, XII", "Art. 5º, X",
#          "Art. 7, § 6º", "Art. 7, § 6, II", "Art. 5, LXXII"
# Optional alínea letter is omitted from this regex (rare in answers; can
# extend later if needed without breaking the tuple shape).
_PROSE_CITATION_RE = re.compile(
    r"\b[Aa]rt(?:igo)?\.?\s*"           # Art. / Artigo / art.
    r"(\d+(?:-[A-Z])?)"                  # group 1: article number (e.g., "5", "154-A")
    r"\s*[º°]?"                          # optional ordinal indicator
    r"(?:"                                # optional § or inciso block
    r"\s*,?\s*"
    r"(?:§\s*(\d+)\s*[º°]?)?"           # group 2: § number (optional)
    r"\s*,?\s*"
    r"([IVXLCDM]+)?"                     # group 3: roman inciso (optional)
    r")?"
)


@dataclass(frozen=True)
class ProseCitation:
    """One cite extracted from answer prose. `surface` is the literal text
    span in the answer (useful for highlighting in UIs / error messages).

    `partition_path` is the LCP-95 partition path the prose maps to —
    e.g., "art5;inc12" or "art7;par6". Compared against the URN suffix
    of verified citations to decide match/mismatch.
    """
    surface: str
    article_num: str
    paragraph_num: str | None
    inciso_roman: str | None
    inciso_num: int | None
    span_start: int
    span_end: int

    @property
    def partition_path(self) -> str:
        """LCP-95 partition path for this prose citation.

        Examples:
          Art. 5            → "art5"
          Art. 5, XII       → "art5;inc12"
          Art. 7, § 6, I    → "art7;par6;inc1"
          Art. 7, § 6       → "art7;par6"
        """
        parts = [f"art{self.article_num.lower()}"]
        if self.paragraph_num is not None:
            parts.append(f"par{self.paragraph_num}")
        if self.inciso_num is not None:
            parts.append(f"inc{self.inciso_num}")
        return ";".join(parts)


@dataclass(frozen=True)
class ProseMismatch:
    """One prose citation that doesn't map to any verified URN.

    `expected_partition` is what the prose said (e.g., "art5;inc12").
    `nearest_cited_urn` (when available) helps the LLM understand what
    URN it actually cited that's closest to the prose claim — useful
    for the reject-and-reprompt loop.
    """
    surface: str          # the literal "Art. 5, XII" text
    expected_partition: str
    span_start: int
    span_end: int
    nearest_cited_urn: str | None  # Best guess at what the model meant


def extract_prose_citations(text: str) -> list[ProseCitation]:
    """Return all article-citation references in prose order.

    Iterates over `_PROSE_CITATION_RE` matches. The regex is intentionally
    permissive (catches "Art. 5", "art. 5", "Art. 154-A", with/without
    ordinal indicator) — false positives are filtered downstream by the
    verified-citation cross-check.
    """
    out: list[ProseCitation] = []
    for m in _PROSE_CITATION_RE.finditer(text):
        article_num = m.group(1)
        par_num = m.group(2)
        inc_roman = m.group(3)
        # If neither § nor roman were captured, the regex's optional block
        # gave us None for both — that's just "Art. N". Skip if the
        # match is too narrow (e.g., "art" alone with no following digit).
        inc_num = roman_to_int(inc_roman) if inc_roman else None
        out.append(
            ProseCitation(
                surface=m.group(0).strip(),
                article_num=article_num,
                paragraph_num=par_num,
                inciso_roman=inc_roman,
                inciso_num=inc_num,
                span_start=m.start(),
                span_end=m.end(),
            )
        )
    return out


def check_prose_vs_citations(
    answer_text: str,
    cited_urns: list[str],
) -> list[ProseMismatch]:
    """Find prose citations that DON'T match any of the verified URNs.

    For each `ProseCitation` extracted from `answer_text`:
      - Compute its `partition_path` (e.g., "art5;inc12")
      - Check if any cited URN ends with `~{partition_path}` — exact
        suffix match anchored on `~` to avoid "art5" matching "art50"
      - If no match, record a ProseMismatch + best-effort nearest_cited_urn

    Empty result = no prose-vs-cited mismatch detected. This is the
    happy-path; production pipelines log it as observability metric.
    """
    out: list[ProseMismatch] = []
    prose_cites = extract_prose_citations(answer_text)

    for pc in prose_cites:
        # Prefix match anchored on `~`: prose path P matches any cited URN
        # that ends with `~P` (exact) OR contains `~P;` (deeper partition).
        # Example:
        #   prose "Art. 5"     (path=art5)        matches ~art5, ~art5;inc1, ~art5;inc1;ali-a
        #   prose "Art. 5, XII" (path=art5;inc12) matches ~art5;inc12, ~art5;inc12;ali-a
        #   prose "Art. 5, XII" does NOT match ~art5;inc10 (specific mismatch)
        # This is correct: a prose reference is a partial path; any cited
        # URN whose partition starts with that path is a valid grounding.
        anchored = "~" + pc.partition_path
        matched = any(
            urn.endswith(anchored) or (anchored + ";") in urn
            for urn in cited_urns
        )
        if matched:
            continue

        # Find nearest — same article, possibly different inciso/§
        # to give the reprompt LLM context about what was actually cited.
        article_prefix = f"~art{pc.article_num.lower()}"
        nearest = None
        for urn in cited_urns:
            if article_prefix in urn:
                nearest = urn
                break

        out.append(
            ProseMismatch(
                surface=pc.surface,
                expected_partition=pc.partition_path,
                span_start=pc.span_start,
                span_end=pc.span_end,
                nearest_cited_urn=nearest,
            )
        )
    return out


def build_reprompt_message(mismatches: list[ProseMismatch]) -> str:
    """Construct a message for the LLM explaining the mismatches and
    asking for a corrected answer. Used by the pipeline reject-and-reprompt
    loop (Phase 5.3.c)."""
    if not mismatches:
        return ""
    lines = [
        "ATENÇÃO — sua resposta tem inconsistências entre o texto e as URNs citadas:",
    ]
    for m in mismatches:
        if m.nearest_cited_urn:
            lines.append(
                f"  • Você escreveu '{m.surface}' (partição esperada: {m.expected_partition}), "
                f"mas a URN mais próxima nas suas citations[] é {m.nearest_cited_urn}. "
                f"Reescreva a referência no answer pra coincidir com a URN citada, "
                f"OU adicione/troque a URN em citations[] para coincidir com o texto."
            )
        else:
            lines.append(
                f"  • Você escreveu '{m.surface}' (partição esperada: {m.expected_partition}), "
                f"mas nenhuma URN em citations[] referencia essa partição. "
                f"Corrija a referência no texto para algo presente em citations[]."
            )
    lines.append(
        "Re-emita a resposta com texto e citations[] consistentes. "
        "Se você não consegue sustentar a referência com uma URN do contexto, "
        "remova a referência da prosa."
    )
    return "\n".join(lines)
