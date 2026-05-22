"""Vigência overlays — curatorial layer above the parser.

Reviewer round 2 (legal-domain) flagged that `is_revoked_text` only catches
Planalto markers `(Revogado)` / `(Vetado)` / `(Suprimido)`. It misses the
load-bearing categories: revogação tácita, suspensão por liminar, sub
judice, vacatio legis parcial, eficácia limitada por regulamentação.

Without these, the RAG commits the parecerista's worst error: treating
formally-vigente text as applicable while ignoring active controversy.

This module is the curatorial layer: a hand-curated YAML overlay attaches
a `Vigencia` record to URNs whose status is not the default "vigente".
Applied at chunk-load time, propagated into the IndexChunk → renders into
the `<fonte>` XML the LLM sees → SYSTEM_PROMPT instructs the model to
flag in the answer with a leading "⚠️ Atenção:" sentence.

Status taxonomy (the YAML's controlled vocabulary):

    vigente                      default; not overlaid
    sub_judice                   controvérsia constitucional pendente
    suspenso                     eficácia suspensa por liminar
    vacatio_legis                promulgado mas ainda não em vigor
    eficacia_limitada            depende de regulamentação infralegal
    revogado_tacito              incompatível com norma posterior
    alterado_por_ec              constitucional, EC modificadora (informativo)
    alterado_por_jurisprudencia  STF/STJ fixou tese que altera aplicação
                                 (Phase 16.2 — distinct from sub_judice;
                                 a tese has been *fixed*, not is pending)
    atualizado_recentemente      lei alteradora recente (informativo)

Operator-facing field `proxima_revisao` (ISO date, optional) tracks
when an entry should be re-audited. Phase 16.2 introduced this to
prevent the Tema-987-class staleness: a `sub_judice` overlay that
never got re-checked after STF fixed the tese on 2024-06-26.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VALID_STATUSES = frozenset({
    "vigente",
    "sub_judice",
    "suspenso",
    "vacatio_legis",
    "eficacia_limitada",
    "revogado_tacito",
    "alterado_por_ec",
    "alterado_por_jurisprudencia",
    "atualizado_recentemente",
})


@dataclass(frozen=True)
class Vigencia:
    """Per-URN vigência metadata. None means "vigente" (no overlay)."""
    status: str
    fundamento: str
    desde: str           # ISO date (YYYY-MM-DD)
    descricao_curta: str
    proxima_revisao: str = ""  # ISO date; Phase 16.2 — quarterly audit cadence

    def short_label(self) -> str:
        """One-line summary for the <fonte> XML attribute."""
        return f"{self.status} ({self.fundamento})"


def load_overlays(path: Path) -> dict[str, Vigencia]:
    """Load overlays.yaml into a urn → Vigencia map.

    Validates each entry's `status` is in `VALID_STATUSES`. Raises with the
    URN of the offending entry on validation failure — callers should not
    swallow this; a typo'd status silently turns into "vigente" downstream.
    Duplicate URNs raise ValueError (data error, not application error).
    """
    if not path.exists():
        return {}
    raw: list[dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8")) or []

    out: dict[str, Vigencia] = {}
    for i, item in enumerate(raw):
        urn = item.get("urn")
        if not urn:
            raise ValueError(f"overlay entry {i} missing 'urn' field")
        if urn in out:
            raise ValueError(f"duplicate overlay URN at entry {i}: {urn}")
        status = item.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(
                f"invalid status {status!r} for {urn} — "
                f"valid: {sorted(VALID_STATUSES)}"
            )
        out[urn] = Vigencia(
            status=status,
            fundamento=str(item.get("fundamento", "")),
            desde=str(item.get("desde", "")),
            descricao_curta=str(item.get("descricao_curta", "")).strip(),
            proxima_revisao=str(item.get("proxima_revisao", "")),
        )
    return out


def vigencia_warning(vig: Vigencia) -> str:
    """Render the warning string the LLM should emit when citing a flagged
    chunk. Anchored on '⚠️ Atenção:' so it's visually unmissable in the
    answer prose and easy to assert in tests."""
    return (
        f"⚠️ Atenção: dispositivo com vigência ressalvada — "
        f"{vig.descricao_curta} (Status: {vig.status}; "
        f"Fundamento: {vig.fundamento}; Desde: {vig.desde}.)"
    )
