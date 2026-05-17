"""Extract discursive subset from maritaca-ai/oab-bench for Phase 7.5.5.

Source: maritaca-ai/oab-bench v2 (Apache-2.0, OAB editions 39-44, 2023-2024).
210 rows = 105 question + 105 guideline rows, paired by question_id.

Curation: 5 questions selected manually (Ricardo, 2026-05-17) covering:
  - 39_direito_civil_questao_3 — explicit LGPD art.8 §5 (consent revocation)
  - 39_direito_constitucional_questao_1 — Lei Complementar / atividade econômica
  - 40_direito_constitucional_questao_2 — ICMS interestadual / pacto federativo
  - 39_direito_penal_questao_1 — peça processual penal
  - 39_direito_civil_questao_1 — comodato (CC arts. fora de nossa janela 11-21;
    INTENCIONALMENTE incluída para sondar refusal behavior em sub-corpus gap)

Output schema (eval/oab_bench_discursive_pilot.yaml):

  - source_id: str — `maritaca-ai/oab-bench/<question_id>`
  - category: "discursive"
  - legal_area: str
  - query: str — `statement` field from oab-bench (peça/dissertativa prompt)
  - rubric: str — `guidelines.choices[0].turns[0]` (model answer / scoring guide)
  - max_score: float — sum of `values` (each sub-question scored separately
    in OAB official rubric; we collapse to single per-question max)
  - notes: str

Runner (rag_leis/run_concurso_eval.py discursive scoring) sends
(query, pipeline_answer, rubric) to opus-4-7 judge; judge returns
score_pct (0.0-1.0). Aggregate: discursive_mean_pct.

Uso:
    uv run python -m scripts.extract_oab_bench_discursive
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from datasets import load_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = PROJECT_ROOT / "eval" / "oab_bench_discursive_pilot.yaml"

# Manually selected 5 questions. Order: digital-law explicit + 2
# constitutional (CF full coverage) + penal (CP full coverage) + 1
# civil-out-of-window (sub-corpus gap probe).
SELECTED_QIDS: tuple[str, ...] = (
    "39_direito_civil_questao_3",            # LGPD art.8 §5 — consent revocation
    "39_direito_constitucional_questao_1",   # Lei Complementar (CF in scope)
    "40_direito_constitucional_questao_2",   # ICMS / pacto federativo
    "39_direito_penal_questao_1",            # Peça penal (CP in scope)
    "39_direito_civil_questao_1",            # Comodato (CC out of arts.11-21)
)

NOTES_BY_QID: dict[str, str] = {
    "39_direito_civil_questao_3":
        "LGPD art.8 §5 + art.15 III — consent revocation + dados elimination. "
        "Direct hit on LGPD in our corpus.",
    "39_direito_constitucional_questao_1":
        "Lei Complementar restringindo atividade econômica não constitucionalmente "
        "prevista. CF/88 art. 170 IV/V (livre iniciativa) — in-corpus.",
    "40_direito_constitucional_questao_2":
        "Pacto federativo + ICMS interestadual. CF/88 arts. sobre competência "
        "tributária — likely in-corpus partially; full answer needs CTN (OUT).",
    "39_direito_penal_questao_1":
        "Peça penal — defesa em ação por crime eleitoral / coação. CP partially "
        "in-corpus; eleitoral OUT.",
    "39_direito_civil_questao_1":
        "Comodato (contrato de empréstimo gratuito). CC arts. 579-585 — OUT of "
        "our 11-21 indexed range. Sub-corpus gap probe.",
}


def main() -> int:
    print("Loading maritaca-ai/oab-bench (questions + guidelines) ...")
    questions = load_dataset("maritaca-ai/oab-bench", "questions")["train"]
    guidelines = load_dataset("maritaca-ai/oab-bench", "guidelines")["train"]
    g_by_qid = {g["question_id"]: g for g in guidelines}
    q_by_qid = {q["question_id"]: q for q in questions}

    rows_out: list[dict] = []
    for qid in SELECTED_QIDS:
        q = q_by_qid.get(qid)
        g = g_by_qid.get(qid)
        if q is None or g is None:
            print(f"  SKIP: {qid} missing from dataset")
            continue
        # Sum values for max_score (some questions have multiple sub-parts;
        # the rubric is a single block, so we collapse to single score).
        max_score = sum(q.get("values") or [1.0])
        rubric_text = g["choices"][0]["turns"][0] if g["choices"] else ""
        rows_out.append({
            "source_id": f"maritaca-ai/oab-bench/{qid}",
            "category": "discursive",
            "legal_area": q.get("category", "").replace("39_", "").replace("40_", ""),
            "max_score": round(max_score, 3),
            "query": q["statement"],
            "rubric": rubric_text,
            "notes": NOTES_BY_QID.get(qid, ""),
        })

    header = (
        "# OAB-bench discursive pilot — Phase 7.5.5 (2026-05-17).\n"
        "#\n"
        "# Source: maritaca-ai/oab-bench v2, Apache-2.0, OAB 2ª fase\n"
        "#         (peças jurídicas + dissertativas) editions 39-44.\n"
        "# Sample: 5 questions manually curated for digital-law adjacency\n"
        "#         + sub-corpus gap probing (see scripts/extract_oab_bench_discursive.py).\n"
        "# Format: discursive — pipeline drafts legal text; LLM judge scores\n"
        "#         pipeline answer against rubric (model answer). New runner\n"
        "#         category in rag_leis/run_concurso_eval.py.\n"
        "# Scoring: judge emits score_pct (0.0-1.0); aggregate is mean across rows.\n"
        "# Cost: ~$1-2 per pilot run (Sabiá generation + opus judge × 5 rows).\n"
        "#\n"
        "# Reproduce: uv run python -m scripts.extract_oab_bench_discursive\n"
        "\n"
    )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        header + yaml.dump(rows_out, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"Wrote {len(rows_out)} discursive rows → {OUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
