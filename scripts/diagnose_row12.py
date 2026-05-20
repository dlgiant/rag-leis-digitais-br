"""Find the eval-run cache entry for row 12 and compare to a fresh call."""
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path("/home/ricardo/rag-leis-digitais-br")
load_dotenv(PROJECT_ROOT / ".env", override=False)

from rag_leis.citation_relevance import (
    CITATION_RELEVANCE_TOOL,
    RELEVANCE_JUDGE_SYSTEM,
    _format_citations_for_judge,
)
from rag_leis.llm import DEFAULT_JUDGE_MODEL
from rag_leis.llm_cache import cache_key
from rag_leis.run_answer_eval import CHUNKS_DIR, INDEX_DIR, load_pipeline

print("Loading pipeline...")
pipe = load_pipeline(
    chunks_dir=CHUNKS_DIR, index_dir=INDEX_DIR,
    embedder_name="voyage-3-large",
    text_mode="title+label+nav+caput+text",
    llm_provider="maritaca", llm_model=None,
    top_k=10, oos_threshold=0.4, llm_cache_dir=Path("data/cache/llm"),
)

query = "o que o decreto regulamentador do Marco Civil diz sobre guarda de logs e segurança dos dados retidos?"
citations = [
    "urn:lex:br:federal:decreto:2016-05-11;8771~art13;par2;inc1",
    "urn:lex:br:federal:decreto:2016-05-11;8771~art13;par2;inc2",
]

user_msg = (
    f"<pergunta>\n{query.strip()}\n</pergunta>\n\n"
    f"<citacoes>\n{_format_citations_for_judge(citations, pipe.chunks_by_urn)}\n</citacoes>"
)

# Compute the key my diagnostic uses
k_mine = cache_key(
    provider="anthropic", model=DEFAULT_JUDGE_MODEL,
    system=RELEVANCE_JUDGE_SYSTEM, user=user_msg,
    tool_schema=CITATION_RELEVANCE_TOOL,
    max_tokens=4096, kind="structured",
)
print(f"\nMy key prefix: {k_mine[:16]}")
print(f"DEFAULT_JUDGE_MODEL = {DEFAULT_JUDGE_MODEL}")

# Search cache for entries that match the URN list anywhere in user content
cache_dir = Path("data/cache/llm")
hits = []
for f in sorted(cache_dir.glob("*.json")):
    try:
        entry = json.loads(f.read_text())
    except Exception:
        continue
    key_inputs = entry.get("key_inputs", {})
    user_in = key_inputs.get("user", "")
    if "decreto:2016-05-11;8771~art13" in user_in and "guarda de logs" in user_in:
        hits.append((f.name, entry))

print(f"\nFound {len(hits)} cache entries mentioning row 12's URNs + query phrase")
for fname, entry in hits:
    print(f"\n--- {fname} ---")
    print(f"  provider/model: {entry.get('provider')}/{entry.get('model')}")
    print(f"  tool_name: {entry.get('key_inputs',{}).get('tool_name')}")
    print(f"  max_tokens: {entry.get('key_inputs',{}).get('max_tokens')}")
    resp = entry.get("response", {})
    if "evaluations" in resp:
        for e in resp.get("evaluations", []):
            print(f"  - {e.get('urn')[-30:]}  relevant={e.get('relevant')}  reason={e.get('reason','')[:120]}")
    user_in = entry.get("key_inputs",{}).get("user","")
    print(f"  user prompt prefix: {user_in[:200]!r}")
    print(f"  matches my key: {fname.replace('.json','') == k_mine}")
