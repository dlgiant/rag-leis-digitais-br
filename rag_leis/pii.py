"""PII redactor — input sanitization before query → Voyage / LLM.

Reviewer round 2 item 8: the system describes LGPD and itself doesn't
comply. A query like "vazaram o CPF 123.456.789-00 do João Silva, qual
o procedimento?" sends dados pessoais sensíveis verbatim to Anthropic
(US-hosted) and Voyage (US-hosted), violating both the spirit of LGPD
and our own ToS-as-a-legal-tech-product story.

This module is the input sanitizer: replace PII tokens with
`[TYPE#N]` placeholders BEFORE the query crosses any provider
boundary. The redactor lives in the pipeline as a pre-retrieval +
pre-LLM step. Doc embeddings (Voyage, public law text) are unaffected.

Categories covered (per LGPD art. 5, II — "dado pessoal sensível" and
art. 5, I — "dado pessoal" identifiável):

  - CPF       (Cadastro de Pessoa Física): formatted (000.000.000-00)
              and unformatted (00000000000) — 11 digits
  - CNPJ      (empresa): formatted (00.000.000/0000-00) and unformatted
              — 14 digits
  - email     standard RFC-ish, case-insensitive
  - phone     BR landline + mobile, common formats; allows (DD), space,
              dash variants
  - CEP       postal code, 5+3 digits with optional dash
  - RG        regional ID, 8-9 digits (loose match — RG formats vary
              by UF)

Phase 18.5 additions — drained from Phase 14 audit findings (lawyer-
review checklist 🟡 #6); these show up in lawyer queries with non-
trivial frequency and are LGPD "dado pessoal" by art. 5, I (any data
identifying a natural person):

  - OAB             Brazilian Bar Association lawyer license —
                    "OAB/SP 123.456" / "OAB-RJ 234567"
  - CRM             Medical license (Conselho Regional de Medicina) —
                    "CRM/SP 12345" / "CRM-MG 67890"
  - processo_cnj    Unified case number (Resolução CNJ 65/2008) —
                    "1234567-89.2020.8.26.0001" (NNNNNNN-DD.AAAA.J.TR.OOOO)
  - titulo_eleitor  Voter registration ID — "1234 5678 9012" (4-4-4
                    spaced form only; bare 12-digit blob too generic)

NER for nomes próprios is deliberately separate (rag_leis.pii_ner), in
an optional dep group. Regex is precision-heavy by design: it MUST NOT
overmatch (false-redaction in a legal context is itself an LGPD-relevant
data quality issue) and SHOULD overmatch slightly when in doubt (under-
redaction is a residency leak).

Order of application matters: CPF (11 digits) must be matched BEFORE
CNPJ (14 digits) — actually they don't overlap because CNPJ pattern
requires exactly 14 digits or the formatted variant — but ordering is
preserved for safety. Email matched first to consume `@` sequences
that might otherwise look like phone fragments.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PIIMatch:
    """One PII detection. `placeholder` is the substitution token that
    appears in the redacted text. `position` is the offset in the
    ORIGINAL text (useful for audit log reconstruction; the redacted
    text's offsets differ once placeholders replace originals)."""

    pii_type: str           # "cpf" | "cnpj" | "email" | "phone" | "cep" | "rg"
    original: str
    placeholder: str
    position: int


@dataclass(frozen=True)
class RedactedQuery:
    """Result of redact(). `redacted_text` is what gets sent to providers.

    `pii_types_found` is the deduplicated set of types — handy for the
    audit log and for one-line summaries in observability.

    `original_hash` is SHA-256 of the input text — lets the audit log
    record "we processed query X" without storing X itself. The reverse
    is impossible (can't recover original from hash), satisfying the
    LGPD principle of data minimization on telemetry.
    """

    redacted_text: str
    matches: list[PIIMatch]
    pii_types_found: frozenset[str] = field(default_factory=frozenset)
    original_hash: str = ""


# ----------------------------------------------------------------------------
# Patterns — order is the application order
# ----------------------------------------------------------------------------

# Email FIRST to consume "@" sequences before phone/CEP patterns get to them.
# Standard simple email regex; intentionally non-RFC-complete (we accept
# the rare false-negative on edge-case mail addresses; production gain
# outweighs the marginal coverage).
_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+\b",
)

# CNPJ — 14 digits. Matched before CPF because formatted CNPJ contains
# a "/" that isn't in CPF; unformatted CNPJ has 14 digits while CPF
# has 11, so they never overlap on the same input substring.
_CNPJ_RE = re.compile(
    r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b|\b\d{14}\b",
)

# CPF — 11 digits formatted or unformatted. WARNING: unformatted variant
# (\d{11}) also matches phone numbers starting with 9 (11-digit mobile
# without DDD prefix is unusual but possible). The phone pattern below
# is anchored on parentheses or specific length groupings that exclude
# this case; CPF wins ties because the production LGPD-residency win is
# bigger than the rare false-positive on a phone written as 11 raw digits.
_CPF_RE = re.compile(
    r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b",
)

# Phone BR — landline ((11) 9999-9999) + mobile ((11) 99999-9999).
# Allows optional parens, spaces, dashes. NOT matching pure 11-digit
# blobs (those were caught by CPF — see warning above).
_PHONE_RE = re.compile(
    r"\(?\b\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b",
)

# CEP — 8 digits with optional dash after 5th
_CEP_RE = re.compile(
    r"\b\d{5}-\d{3}\b",
)

# RG — variable format by UF; common: 8-9 digits with optional dashes
# and check-digit X. Loose intentionally — RG vai-e-vem entre estados.
_RG_RE = re.compile(
    r"\b\d{1,2}\.\d{3}\.\d{3}-?[\dxX]\b",
)

# Phase 18.5 — Brazilian professional + judicial + voter identifiers.

# OAB — Brazilian Bar Association number. Formats vary:
#   "OAB/SP 123.456", "OAB-SP 123456", "OAB nº 123.456/SP", "OAB 234567"
# Anchored on "OAB" so the bare-number false-positive surface is zero;
# state code is optional (legally required but practitioners drop it).
# ID accepts 4-8 digits, with optional 3.3 / 3.4 dot grouping that
# many official renderings use.
_OAB_RE = re.compile(
    r"\bOAB[\s/.-]*(?:n[°º.]?\s*)?(?:[A-Z]{2}\s*[/-]?\s*)?"
    r"(?:\d{1,3}\.\d{3,5}|\d{4,8})(?:\s*[/-]?\s*[A-Z]{2})?\b",
    re.IGNORECASE,
)

# CRM — Conselho Regional de Medicina (medical license). Same anchor
# strategy as OAB; smaller-jurisdiction IDs historically can be just
# 3 digits, so the digit floor is lower than OAB.
_CRM_RE = re.compile(
    r"\bCRM[\s/.-]*(?:n[°º.]?\s*)?(?:[A-Z]{2}\s*[/-]?\s*)?"
    r"(?:\d{1,3}\.\d{3,5}|\d{3,7})(?:\s*[/-]?\s*[A-Z]{2})?\b",
    re.IGNORECASE,
)

# Processo CNJ — unified 20-digit case number set by Resolução CNJ
# 65/2008. Format: NNNNNNN-DD.AAAA.J.TR.OOOO. The punctuation pattern
# (7-digit, dash, 2-digit, dot, 4-digit, dot, 1-digit, dot, 2-digit,
# dot, 4-digit) is so distinctive that false-positives are effectively
# impossible — no other identifier shape in PT-BR uses it.
_PROCESSO_CNJ_RE = re.compile(
    r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b",
)

# Título de eleitor — Brazilian voter registration ID. 12 digits,
# rendered as "0000 0000 0000" (4-4-4 spaced) in nearly all official
# uses. Bare 12-digit blob is intentionally NOT matched here — too
# generic, would catch account numbers and other unrelated identifiers.
# The "Título nº 123456789012" contextual variant can be added by a
# future iteration if Phase 14 audit shows it surfacing in queries.
_TITULO_ELEITOR_RE = re.compile(
    r"\b\d{4}\s\d{4}\s\d{4}\b",
)


# Order matters: each pattern's matches are extracted before the next,
# substituted with a unique placeholder, and the substituted text is
# what subsequent patterns scan. This avoids one pattern's match landing
# inside another's tokens. Phase 18.5 patterns are appended at the end
# so the established CPF/CNPJ/RG/CEP/phone ordering invariants are
# preserved — the new patterns are either prefix-anchored (OAB, CRM)
# or precision-anchored (CNJ, voter 4-4-4) so overlap with bare-digit
# patterns is structurally impossible.
_PATTERN_PIPELINE: list[tuple[str, re.Pattern[str]]] = [
    ("email", _EMAIL_RE),
    ("cnpj", _CNPJ_RE),
    ("cpf", _CPF_RE),
    ("rg", _RG_RE),
    ("cep", _CEP_RE),
    ("phone", _PHONE_RE),
    ("processo_cnj", _PROCESSO_CNJ_RE),
    ("oab", _OAB_RE),
    ("crm", _CRM_RE),
    ("titulo_eleitor", _TITULO_ELEITOR_RE),
]


# ----------------------------------------------------------------------------
# Core redact()
# ----------------------------------------------------------------------------


def redact(text: str) -> RedactedQuery:
    """Return a RedactedQuery with PII replaced by `[TYPE#N]` placeholders.

    The original text is hashed (SHA-256) for the audit log — the hash
    is recoverable only by recomputing it on a known input, so we can
    verify "did this query happen?" without retaining the query.

    Placeholder format: `[CPF#1]`, `[EMAIL#1]`, etc. Numbered per-type
    starting at 1, so a query mentioning two CPFs gets `[CPF#1]` and
    `[CPF#2]` — distinguishable downstream without leaking ordering
    of arrival.
    """
    if not text:
        return RedactedQuery(
            redacted_text=text,
            matches=[],
            pii_types_found=frozenset(),
            original_hash=hashlib.sha256(b"").hexdigest(),
        )

    original_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    redacted = text
    matches: list[PIIMatch] = []
    counters: dict[str, int] = {}

    for pii_type, pattern in _PATTERN_PIPELINE:
        # Iterate over the CURRENT state of `redacted` (after previous
        # patterns have substituted). This is the only way to guarantee
        # one pattern can't re-trigger on another's placeholder remnants
        # — though our placeholders look like [CPF#1], not like digits,
        # so accidental overlap is unlikely.
        found = list(pattern.finditer(redacted))
        if not found:
            continue
        # Substitute back-to-front so positions of remaining matches
        # don't shift.
        for m in reversed(found):
            counters[pii_type] = counters.get(pii_type, 0) + 1
            placeholder = f"[{pii_type.upper()}#{counters[pii_type]}]"
            matches.append(
                PIIMatch(
                    pii_type=pii_type,
                    original=m.group(0),
                    placeholder=placeholder,
                    position=m.start(),
                )
            )
            redacted = redacted[: m.start()] + placeholder + redacted[m.end():]

    return RedactedQuery(
        redacted_text=redacted,
        matches=matches,
        pii_types_found=frozenset(m.pii_type for m in matches),
        original_hash=original_hash,
    )


def unredact(text: str, matches: list[PIIMatch]) -> str:
    """Best-effort reverse: substitute placeholders back with originals.

    Useful when a UI needs to render the redacted answer alongside the
    original query for context (the user typed their CPF; the LLM never
    saw it; the UI wants to show "we treated your CPF as [CPF#1]
    throughout").

    Caveat: if the LLM output text rephrases the placeholder (rare;
    usually it preserves verbatim), the unredact won't catch it. This
    is acceptable for the current use case — placeholders aren't
    sensitive, so a verbatim survival is desirable.
    """
    out = text
    # Apply in reverse-discovery order so longer placeholders ([CPF#10])
    # match before shorter ones ([CPF#1]) — only relevant once there
    # are 10+ of one type, but harmless in the common case.
    for m in sorted(matches, key=lambda x: -len(x.placeholder)):
        out = out.replace(m.placeholder, m.original)
    return out


# ----------------------------------------------------------------------------
# Convenience
# ----------------------------------------------------------------------------


def summarize(rq: RedactedQuery) -> str:
    """One-line summary for logs / debug. No PII leaked."""
    if not rq.matches:
        return f"no PII (hash={rq.original_hash[:8]})"
    counts = {}
    for m in rq.matches:
        counts[m.pii_type] = counts.get(m.pii_type, 0) + 1
    parts = ", ".join(f"{n}x{t}" for t, n in sorted(counts.items()))
    return f"{len(rq.matches)} PII matches ({parts}); hash={rq.original_hash[:8]}"
