"""Filter ECA parser output → only digital-rights + digital-crime arts.

Phase 18.1 — ECA (Lei 8.069/1990) full parse produces ~1154 chunks
(323 artigos). Indexing the full ECA adds heavy noise to a
digital-law corpus — only a narrow set of articles touches the
project's domain:

  art. 17     — direito ao respeito (inviolabilidade da imagem,
                identidade, autonomia, valores, ideias, crenças)
  art. 18     — dever de proteção à dignidade contra tratamento
                vexatório / constrangedor
  art. 78     — proibição de exposição/publicação que possa
                identificar criança/adolescente em ato infracional
                (espelha CF art. 5 V/X aplicado a menores)
  art. 240    — produzir/dirigir/fotografar cena de sexo explícito
                ou pornográfica com criança/adolescente (crime; pena
                4-8 anos + multa)
  art. 241    — vender/expor/oferecer/trocar/disponibilizar imagem
                pornográfica de criança/adolescente — base do
                processamento digital de pedofilia
  art. 241-A  — oferecer/trocar/disponibilizar/distribuir por
                qualquer meio inclusive sistema informático
  art. 241-B  — adquirir/possuir/armazenar
  art. 241-C  — simular participação (montagem) de criança em
                cena pornográfica
  art. 241-D  — aliciar/assediar/instigar/constranger por qualquer
                meio (sexting / grooming digital)
  art. 241-E  — definição legal de "cena de sexo explícito ou
                pornográfica" — load-bearing para classificação
                forense de conteúdo

These 9 artigos (+ their parágrafos e incisos) are the ECA-side
universe that legal-research queries about digital crimes against
minors hit. The remaining 314 artigos are out of project scope
(adoção, conselho tutelar, fundo dos direitos, etc.).

Uso:
  uv run python scripts/filter_eca_digital_arts.py

Pré-requisito: data/raw/tier-2/br_federal_lei_1990-07-13_8069.html
existe (rode `fetch_tier --tier 2` antes).

Saída: SOBRESCREVE data/chunks/tier-2/br_federal_lei_1990-07-13_8069.jsonl
com a versão filtrada (~40 chunks vs 1154 originais).

Re-aplicar sempre que `parse_all_tier --tier 2` for executado.
Mesmo padrão do filter_cc_personalidade.py.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

from rag_leis.fetch_tier import urn_to_filename
from rag_leis.parser import parse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ECA_URN = "urn:lex:br:federal:lei:1990-07-13;8069"

# Match the chunk-partition format produced by the parser:
#   art17, art18, art78, art240, art241, art241-a, art241-b,
#   art241-c, art241-d, art241-e
# Followed by either end-of-partition OR a `;` introducing a
# child (paragrafo, inciso, alinea).
# The (?:;|$) terminator avoids matching "art1700" or "art78x".
KEEP_PATTERN = re.compile(
    r"^art(?:17|18|78|240|241(?:-[a-e])?)(?:;|$)",
)


def main() -> int:
    base = urn_to_filename(ECA_URN)
    html_path = PROJECT_ROOT / "data" / "raw" / "tier-2" / f"{base}.html"
    out_path = PROJECT_ROOT / "data" / "chunks" / "tier-2" / f"{base}.jsonl"

    if not html_path.exists():
        print(
            f"ERRO: {html_path} não existe. "
            f"Rode `uv run python -m rag_leis.fetch_tier --tier 2` antes.",
            file=sys.stderr,
        )
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)

    html = html_path.read_text(encoding="utf-8")
    all_chunks = parse(ECA_URN, html)
    filtered = [c for c in all_chunks if KEEP_PATTERN.match(c.partition)]

    if not filtered:
        print(
            "ERRO: filter produced 0 chunks. KEEP_PATTERN may be wrong "
            "for this ECA version. Sample partitions:",
            file=sys.stderr,
        )
        for c in all_chunks[:10]:
            print(f"  {c.partition}", file=sys.stderr)
        return 1

    with out_path.open("w", encoding="utf-8") as f:
        for c in filtered:
            payload = asdict(c)
            payload["urn"] = c.urn
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    # Breakdown by top-level article for sanity-check
    by_top: dict[str, int] = {}
    for c in filtered:
        top = c.partition.split(";", 1)[0]
        by_top[top] = by_top.get(top, 0) + 1
    print(
        f"ECA parser produced {len(all_chunks)} chunks; "
        f"kept {len(filtered)} matching digital-arts pattern."
    )
    for top in sorted(by_top.keys()):
        print(f"  {top:>10}  {by_top[top]} chunks")
    print(f"Overwrote {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
