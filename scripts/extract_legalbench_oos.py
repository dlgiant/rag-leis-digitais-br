"""Sample OOS queries from celsowm/legalbench.br for Phase 7.5.3.

Why: the OAB concurso pilot (2026-05-17) exposed that internal OOS test
surface was too small (9 rows) AND too easy (curated by us as "obviously"
OOS). External OOS questions from a benchmark we didn't construct stress-
test refusal behavior more honestly. Expected outcome: refusal_accuracy
CI tightens from ±15pp (n=9) to ±5pp (n=~60).

Source: celsowm/legalbench.br multiple_choice_qa task, filtered to legal
areas OUTSIDE our corpus (Tributário, Trabalhista, Processual Penal,
Processual Civil, Internacional, Ambiental, Previdenciário, Empresarial,
Eleitoral). 227 candidates available; we sample ~50 with stratification.

Copyright posture: same as scripts/extract_oab_pilot.py — store the
question stem (paraphrased from `Enunciado:` line) + source_id reference
to the HF dataset, not the verbatim full prompt. CC BY-SA 4.0 dataset,
so technically redistributable with attribution, but we keep the
posture-consistent.

Uso:
    uv run python -m scripts.extract_legalbench_oos
    → writes eval/legalbench_br_oos.yaml
"""

from __future__ import annotations

import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from datasets import load_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = PROJECT_ROOT / "eval" / "legalbench_br_oos.yaml"

# Areas OUTSIDE our corpus. Our corpus covers: CF/88, CC (arts.11-21),
# CP, MCI, LGPD, CDC, LDA, Lei Software, LAI, Lei 14.155, Lei 9.507,
# Lei 13.853 (ANPD), Lei 14.063, Lei 14.129, Lei 11.419, ANPD Res 4/15.
# Plus tier-4 jurisprudência (3 STJ súmulas + 4 STF temas).
#
# Listed areas have ZERO load-bearing chunks in the corpus — pipeline
# should refuse with subtype "a" (other domain entirely).
OOS_AREAS: tuple[str, ...] = (
    "Direito Tributário",
    "Direito Trabalhista",
    "Direito Ambiental",
    "Direito Previdenciário",
    "Direito Processual Penal",
    "Direito Processual Civil",
    "Direito Internacional",
    "Direito Eleitoral",
    "Direito Empresarial",
)

# Sample size per area target. We'd like ~50 total; some areas have few
# rows (Internacional=18, Eleitoral=1) so we cap at "min(target, available)".
PER_AREA_TARGET = 7  # 9 areas × 7 ≈ 63 cap; actual will be ~45-50

# Stable seed so re-runs produce same sample (operator reviews diff once).
SEED = 42


_ENUNCIADO_RE = re.compile(r"Enunciado:\s*(.+?)(?=\n\nAlternativas:|$)", re.DOTALL)


def extract_enunciado(user_msg: str) -> str | None:
    """Pull just the question stem from the structured user prompt.

    The legalbench.br MCQ format embeds the discipline name as a prefix
    ("Disciplina: Direito Tributário"). That prefix makes refusal trivial
    — model sees "Tributário" and bails on token match alone. For an
    honest OOS test we want the question semantics WITHOUT the domain
    hint. Returns the Enunciado text only.
    """
    m = _ENUNCIADO_RE.search(user_msg)
    if not m:
        return None
    return m.group(1).strip()


def main() -> int:
    rng = random.Random(SEED)
    print("Loading celsowm/legalbench.br ...")
    ds = load_dataset("celsowm/legalbench.br")["train"]
    print(f"Total: {len(ds)} rows")

    # Filter + group by area
    by_area: dict[str, list[dict]] = defaultdict(list)
    for row in ds:
        if row["type"] != "multiple_choice_qa":
            continue
        if row["legal_area"] not in OOS_AREAS:
            continue
        user_msg = row["messages"][1]["content"]
        enunciado = extract_enunciado(user_msg)
        if enunciado is None or len(enunciado) < 20:
            continue
        by_area[row["legal_area"]].append({
            "id": row["id"],
            "area": row["legal_area"],
            "enunciado": enunciado,
            "answer_key": row["answer"],
        })

    print(f"\nCandidates per area:")
    for a, rows in sorted(by_area.items(), key=lambda x: -len(x[1])):
        print(f"  {a:35} {len(rows)}")

    # Stratified sample: PER_AREA_TARGET each, or all if fewer
    sampled: list[dict] = []
    for area, rows in by_area.items():
        n = min(PER_AREA_TARGET, len(rows))
        sampled.extend(rng.sample(rows, n))
    print(f"\nSampled: {len(sampled)} OOS rows (target ~{PER_AREA_TARGET * len(OOS_AREAS)})")
    print(f"Per-area in sample:")
    sample_counts = Counter(r["area"] for r in sampled)
    for a, c in sorted(sample_counts.items(), key=lambda x: -x[1]):
        print(f"  {a:35} {c}")

    # Emit in eval-yaml schema compatible with rag_leis/run_concurso_eval.py
    yaml_rows = []
    for r in sampled:
        yaml_rows.append({
            "source_id": f"celsowm/legalbench.br/{r['id']}",
            "category": "oos_a",
            "expected_oos_subtype": "a",
            "question_type": "parafrase",  # MCQ-derived but presented as open question
            "query": r["enunciado"],
            "notes": f"OOS sample from {r['area']} (legalbench.br MCQ, "
                     f"answer_key={r['answer_key']}). Pipeline should refuse "
                     f"because corpus doesn't index this area.",
        })

    # Header comment for the eval file
    header = (
        "# legalbench.br OOS expansion — Phase 7.5.3 (2026-05-17).\n"
        "#\n"
        "# Source: celsowm/legalbench.br, multiple_choice_qa task, CC BY-SA 4.0.\n"
        "# Filter: legal_area in {Tributário, Trabalhista, Ambiental, Previdenciário,\n"
        "#   Processual Penal, Processual Civil, Internacional, Eleitoral, Empresarial}.\n"
        f"# Sample: stratified by area, ~{PER_AREA_TARGET} per area, seed={SEED}.\n"
        f"# Total: {len(yaml_rows)} OOS rows.\n"
        "#\n"
        "# Each row's `query` is the `Enunciado:` line ONLY — the discipline\n"
        "# prefix (\"Disciplina: Direito Tributário\") was stripped because it\n"
        "# would trivially leak the domain to the model and let refusal pass\n"
        "# on token match alone. We want refusal to fire on the SEMANTIC\n"
        "# OOS-ness (no LGPD/MCI/CDC norm exists to support this answer).\n"
        "#\n"
        "# Expected production behavior: pipeline refuses with subtype 'a'\n"
        "# (other domain entirely). Current baseline (concurso pilot 2026-05-17):\n"
        "# OOS-A refusal_rate = 43%. Target post-expansion + SYSTEM_PROMPT\n"
        "# iteration: ≥80%.\n"
        "#\n"
        "# Reproduce: uv run python -m scripts.extract_legalbench_oos\n"
        "\n"
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        header + yaml.dump(yaml_rows, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"\nWrote {len(yaml_rows)} rows → {OUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
