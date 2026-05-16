"""Per-query router: title-prefix vs baseline text-mode.

⚠️ EXPERIMENTAL — NOT WIRED INTO THE PRODUCTION PIPELINE.

Phase 6.6 r4 (2026-05-16) hypothesis test: route queries that mention a
specific Brazilian law name to the `title+label+nav+caput+text` index, and
everything else to the `label+nav+caput+text` baseline.

**Outcome (see scripts/eval_hybrid_router.py per-route audit on 104 queries):**
The hybrid was DOMINATED by pure title-prefix for our use case:

  pipeline               nDCG@10   Recall@20   MRR@10
  baseline               0.7031    0.8772      0.7785
  pure title-prefix      0.7223    0.8705      0.8040   ← production default
  hybrid (this router)   0.7155    0.8650      0.8066

Hybrid only wins MRR by +0.003 over pure title-prefix, while losing -0.007
nDCG and -0.012 Recall. The intuition that "title-prefix helps only when
the query names a law" was empirically wrong — title-prefix lifts metrics
across most query types, not just law-name queries.

This module is preserved for future experimentation only — e.g., probing
when a smarter router (per-query confidence-aware, per-tier routing,
embedding-clustering) might beat pure title-prefix. Don't use in
production without re-validating against current corpus.
"""

from __future__ import annotations

import re

# Patterns ordered by specificity. Word boundaries `\b` everywhere to avoid
# matching letters inside other words. Accented and unaccented variants
# explicit. Roman-numeral or generic 2-letter abbrevs (`CP`, `CC`, `CF`)
# excluded — too noisy in lay queries (`cc` matches "vcc", "facto cc.", etc.).
LAW_NAME_RE = re.compile(
    r"""\b(?:
        marco\s+civil(?:\s+da\s+internet)?
      | (?:lei\s+geral\s+de\s+prote(?:c|ç)(?:a|ã)o\s+de\s+dados(?:\s+pessoais)?)
      | lgpd
      | (?:c(?:o|ó)digo\s+penal)
      | (?:c(?:o|ó)digo\s+civil)
      | (?:c(?:o|ó)digo\s+de\s+defesa\s+do\s+consumidor)
      | (?:lei\s+do\s+software)
      | (?:lei\s+(?:de\s+)?direitos\s+autorais)
      | (?:lei\s+de\s+acesso\s+(?:(?:a|à)\s+)?informa(?:c|ç)(?:a|ã)o)
      | lai
      | anpd
      | constitui(?:c|ç)(?:a|ã)o(?:\s+federal)?
      | (?:s(?:u|ú)mula(?:\s+vinculante)?(?:\s+(?:n[º°]\.?\s*)?\d+)?)
      | (?:tema\s+\d+)
      | (?:lei\s+(?:n[º°]\.?\s*)?\d+(?:[./]\d+)?)
      | (?:decreto(?:-lei)?\s+(?:n[º°]\.?\s*)?\d+(?:[./]\d+)?)
      | habeas\s+data
      | habeas\s+corpus
      | marco\s+civil
    )\b""",
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)


def mentions_law_name(query: str) -> bool:
    """True if the query explicitly references a Brazilian law/code/súmula/tema.

    Use cases routed to title-prefix index:
      - "o que diz o art. 13 do Marco Civil?"           → True
      - "qual a definição de dado pessoal na LGPD?"     → True
      - "Lei 14.155/21 trouxe qual qualificadora?"      → True
      - "o que diz a Súmula 227 do STJ?"                → True
      - "STF Tema 786 e direito ao esquecimento"        → True

    Cases NOT routed (use baseline):
      - "preciso pedir autorização pra mandar e-mail?"  → False
      - "clonaram meu cartão pela internet"             → False
      - "minha empresa precisa nomear alguém?"          → False
    """
    return bool(LAW_NAME_RE.search(query))
