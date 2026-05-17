"""Extract candidate OAB questions for the digital-law concurso eval pilot.

Pulls from `eduagarcia/oab_exams` (2210 MCQ, 2010-2018 OAB editions), filters
by digital-law keyword patterns, and emits two YAML candidate files:

  - eval/oab_pilot_inscope_candidates.yaml — questions matching digital law
    keywords (MCI, Carolina Dieckmann, habeas data, direito de imagem,
    internet/dados-pessoais). Operator manually curates gold_urns from the
    correct alternative.

  - eval/oab_pilot_oos_candidates.yaml — random sample from TAXES,
    LABOUR-PROCEDURE, INTERNATIONAL (clearly outside our corpus). Used as
    OOS subtype "a" (other domain entirely) — expected refusal.

Run:
    uv run python -m scripts.extract_oab_pilot

Pre-req: `uv sync --extra concurso` (installs HuggingFace `datasets`).

Auto-extracted article references (best-effort regex on the correct
alternative text) are surfaced as `gold_urns_candidate` for operator review.
Operator copies confirmed URNs to `gold_urns` and removes the candidate field.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from pathlib import Path

import yaml
from datasets import load_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "eval"

# In-scope keyword patterns — match question + choices text against any of these
# to flag as digital-law candidate. Order doesn't matter; multiple matches OK.
INSCOPE_PATTERNS: dict[str, re.Pattern[str]] = {
    "marco_civil": re.compile(r"(?i)marco\s+civil|\blei\s+12\.965|\b12965\b"),
    "carolina_dieckmann": re.compile(
        r"(?i)carolina\s+dieckmann|\blei\s+12\.737|\b12737\b|invas[ãa]o.{0,30}dispositivo"
    ),
    "lei_software": re.compile(
        r"(?i)lei\s+do\s+software|\blei\s+9\.609|\b9609\b|programa\s+de\s+computador"
    ),
    "habeas_data": re.compile(r"(?i)habeas\s+data|\blei\s+9\.507|\b9507\b"),
    "lai": re.compile(
        r"(?i)\blei\s+de\s+acesso|\blei\s+12\.527|\b12527\b|acesso\s+(?:a|à)\s+informa[çc][ãa]o"
    ),
    "imagem_personalidade": re.compile(
        r"(?i)direito\s+(?:de|à)\s+imagem|direitos\s+da\s+personalidade"
    ),
    "crime_internet": re.compile(
        r"(?i)crime.{0,40}(?:cibern|inform[áa]tic|virtual|internet|dispositivo|computador)"
        r"|estelionato.{0,30}eletr[ôo]nico|furto.{0,30}eletr[ôo]nico"
    ),
    "internet_geral": re.compile(
        r"(?i)\binternet\b|provedor.{0,30}(?:conex|aplica)|servi[çc]o.{0,30}aplica[çc][ãa]o"
        r"|neutralidade\s+de\s+rede"
    ),
    "dados_pessoais": re.compile(
        r"(?i)dados\s+pessoais|prote[çc][ãa]o\s+de\s+dados|tratamento\s+de\s+dados"
    ),
}

# OOS sampling — these question_types are completely outside our federal-digital
# corpus. Used as in-corpus-relative OOS subtype "a" (other domain entirely).
OOS_TYPES = ("TAXES", "LABOUR-PROCEDURE", "INTERNATIONAL")
OOS_SAMPLE_SIZE = 15

# Article-reference extractor — looks for "art. N", "art. N-X", with optional
# inciso/parágrafo and law identifier. Maps to our URN scheme best-effort.
_ART_REF_RE = re.compile(
    r"art(?:igo|\.)?\s*(\d+[-A-Z]?)"          # art. N or art. N-A
    r"(?:\s*[º°])?"                            # optional ordinal
    r"(?:\s*[,§§]\s*(\d+[º°]?))?"             # optional § N
    r"(?:\s*,?\s*([IVXLCDM]+))?"              # optional inciso (roman)
    r"[^.;,)]*?"                                # noise tolerance
    r"(?:lei\s+(?:n[º°]?\.?\s*)?(\d{1,5}(?:[./]\d{2,4})?))?",
    re.IGNORECASE,
)

# Known law identifiers → corpus URNs (for auto-extracting `gold_urns_candidate`)
LAW_TO_URN_BASE = {
    "12965": "urn:lex:br:federal:lei:2014-04-23;12965",       # MCI
    "12.965": "urn:lex:br:federal:lei:2014-04-23;12965",
    "12737": "urn:lex:br:federal:lei:2012-11-30;12737",       # Carolina Dieckmann
    "12.737": "urn:lex:br:federal:lei:2012-11-30;12737",
    "9609": "urn:lex:br:federal:lei:1998-02-19;9609",          # Lei do Software
    "9.609": "urn:lex:br:federal:lei:1998-02-19;9609",
    "9610": "urn:lex:br:federal:lei:1998-02-19;9610",          # LDA
    "9.610": "urn:lex:br:federal:lei:1998-02-19;9610",
    "9507": "urn:lex:br:federal:lei:1997-11-12;9507",          # Habeas data procedimento
    "9.507": "urn:lex:br:federal:lei:1997-11-12;9507",
    "12527": "urn:lex:br:federal:lei:2011-11-18;12527",        # LAI
    "12.527": "urn:lex:br:federal:lei:2011-11-18;12527",
    "8078": "urn:lex:br:federal:lei:1990-09-11;8078",          # CDC
    "8.078": "urn:lex:br:federal:lei:1990-09-11;8078",
    "13709": "urn:lex:br:federal:lei:2018-08-14;13709",        # LGPD (unlikely in pre-2018 OAB)
    "13.709": "urn:lex:br:federal:lei:2018-08-14;13709",
    # CP / CC by reference (no number; relied on contextual mention)
    "2848": "urn:lex:br:federal:decreto.lei:1940-12-07;2848",  # CP
    "10406": "urn:lex:br:federal:lei:2002-01-10;10406",        # CC (filtered to arts.11-21)
    "10.406": "urn:lex:br:federal:lei:2002-01-10;10406",
    # CF: special-case detected by "CRFB" / "Constituição"
}

_ROMAN_TO_INT = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_to_int(roman: str) -> int:
    total, prev = 0, 0
    for ch in roman.upper()[::-1]:
        v = _ROMAN_TO_INT.get(ch, 0)
        total += -v if v < prev else v
        prev = v
    return total


def extract_gold_urn_candidates(text: str) -> list[str]:
    """Best-effort URN extraction from text mentioning articles + laws.

    Returns a deduplicated list. Quality is intentionally noisy — operator
    reviews before committing to eval gold.
    """
    out: set[str] = set()
    for m in _ART_REF_RE.finditer(text):
        art_num, par_num, inciso_roman, law_num = m.groups()
        if not art_num:
            continue
        # Resolve law base — direct match by number, else CRFB/Constituição check
        law_base = None
        if law_num:
            normalized = law_num.replace(".", "")
            law_base = LAW_TO_URN_BASE.get(normalized) or LAW_TO_URN_BASE.get(law_num)
        if law_base is None:
            # Heuristic: "CRFB", "Constituição", "art. 5º, X" → CF
            window = text[max(0, m.start() - 40) : m.end() + 40]
            if re.search(r"(?i)CRFB|Constitui[çc][ãa]o\s+Federal|CF/88", window):
                law_base = "urn:lex:br:federal:constituicao:1988-10-05;1988"
            elif re.search(r"(?i)c[óo]digo\s+penal|\bCP\b", window):
                law_base = "urn:lex:br:federal:decreto.lei:1940-12-07;2848"
            elif re.search(r"(?i)c[óo]digo\s+civil|\bCC\b", window):
                law_base = "urn:lex:br:federal:lei:2002-01-10;10406"
            elif re.search(r"(?i)c[óo]digo\s+de\s+defesa|\bCDC\b", window):
                law_base = "urn:lex:br:federal:lei:1990-09-11;8078"

        if law_base is None:
            continue

        # Build partition
        art_norm = art_num.lower().replace("º", "").replace("°", "")
        partition = f"art{art_norm}"
        if par_num:
            par_norm = par_num.replace("º", "").replace("°", "")
            partition += f";par{par_norm}"
        if inciso_roman:
            try:
                inc_int = _roman_to_int(inciso_roman)
                partition += f";inc{inc_int}"
            except (KeyError, IndexError):
                pass
        out.add(f"{law_base}~{partition}")
    return sorted(out)


def main() -> None:
    print("Loading eduagarcia/oab_exams from HuggingFace ...")
    ds = load_dataset("eduagarcia/oab_exams")["train"]
    print(f"Total questions: {len(ds)}")

    inscope: list[dict] = []
    oos_pool: dict[str, list[dict]] = {t: [] for t in OOS_TYPES}

    for row in ds:
        if row["nullified"]:
            continue
        qtext = row["question"] or ""
        choices_text = " ".join(row["choices"]["text"])
        combined = qtext + " " + choices_text
        matched_patterns = [
            name for name, pat in INSCOPE_PATTERNS.items() if pat.search(combined)
        ]
        if matched_patterns:
            # Correct alternative text — for gold extraction focus
            key = row["answerKey"]
            key_idx = "ABCDE".index(key) if key and key in "ABCDE" else 0
            correct_text = (
                row["choices"]["text"][key_idx]
                if key_idx < len(row["choices"]["text"])
                else ""
            )
            gold_candidates = extract_gold_urn_candidates(qtext + " " + correct_text)
            inscope.append({
                "source_id": row["id"],
                "source_dataset": "eduagarcia/oab_exams",
                "exam_year": row["exam_year"],
                "exam_id": row["exam_id"],
                "question_type": row["question_type"],
                "matched_patterns": matched_patterns,
                "query": qtext.strip(),
                "choices": row["choices"]["text"],
                "answer_key": key,
                "correct_alternative_text": correct_text.strip(),
                "gold_urns_candidate": gold_candidates,
                "gold_urns": [],  # operator fills after review
                "expected_paragraph": "",  # operator fills
                "notes": "",
            })
        elif row["question_type"] in OOS_TYPES:
            oos_pool[row["question_type"]].append(row)

    print(f"In-scope candidates: {len(inscope)}")
    print(f"Pattern hits breakdown:")
    pc = Counter()
    for h in inscope:
        for p in h["matched_patterns"]:
            pc[p] += 1
    for p, c in sorted(pc.items(), key=lambda x: -x[1]):
        print(f"  {p:25} {c}")

    # OOS sampling — take ~5 from each of the 3 types
    rng = random.Random(42)
    oos_sample: list[dict] = []
    per_type = OOS_SAMPLE_SIZE // len(OOS_TYPES)
    for t in OOS_TYPES:
        if not oos_pool[t]:
            continue
        sampled = rng.sample(oos_pool[t], min(per_type, len(oos_pool[t])))
        for row in sampled:
            oos_sample.append({
                "source_id": row["id"],
                "source_dataset": "eduagarcia/oab_exams",
                "exam_year": row["exam_year"],
                "exam_id": row["exam_id"],
                "question_type": row["question_type"],
                "query": (row["question"] or "").strip(),
                "choices": row["choices"]["text"],
                "answer_key": row["answerKey"],
                "expected_oos_subtype": "a",  # other domain entirely
                "notes": f"OOS sample from {row['question_type']}",
            })
    print(f"\nOOS candidates sampled: {len(oos_sample)}")

    # Write outputs
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inscope_path = OUT_DIR / "oab_pilot_inscope_candidates.yaml"
    oos_path = OUT_DIR / "oab_pilot_oos_candidates.yaml"
    inscope_path.write_text(
        yaml.dump(inscope, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    oos_path.write_text(
        yaml.dump(oos_sample, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"\nWrote {len(inscope)} in-scope → {inscope_path.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {len(oos_sample)} OOS    → {oos_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
