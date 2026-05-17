"""Concurso/OAB eval runner — parallel to run_answer_eval but adapted to
the OAB MCQ schema (`eval/oab_concurso_pilot.yaml`).

Three buckets of rows, three different scoring rules:

  inscope  — pipeline should answer non-refused. Cited URNs must "cover"
             gold_urns (any-overlap, not strict-equal). The Brazilian OAB
             question has ONE correct alternative legally supported by
             specific articles; we measure whether the pipeline found
             AT LEAST one of those articles in its citations.

             metrics: inscope_answer_rate (not-refused), inscope_coverage_rate
             (cited ∩ gold non-empty), inscope_coverage_jaccard (avg).

  oos_a    — clearly other-domain (TAXES, LABOUR-PROCEDURE, INTERNATIONAL).
             Pipeline must refuse (refused=True).
             metrics: oos_a_refusal_rate.

  oos_b    — adjacent-without-coverage. Topic touches our corpus' adjacency
             (internet/dados) but operative norm not indexed (ECA, Código
             Ética OAB). Pipeline must refuse — but this is the harder case
             where the model might over-answer.
             metrics: oos_b_refusal_rate.

Uso:
    uv run python -m rag_leis.run_concurso_eval
    uv run python -m rag_leis.run_concurso_eval --output eval/runs/concurso-baseline.json

Pre-req: cached Voyage index + secrets (MARITACA_API_KEY for the production
generator; VOYAGE_API_KEY for index loading).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from rag_leis.llm import DEFAULT_JUDGE_MODEL, LLM, get_llm
from rag_leis.rag import (
    DEFAULT_EMBEDDER,
    DEFAULT_OOS_THRESHOLD,
    DEFAULT_TEXT_MODE,
    DEFAULT_TOP_K,
    RAGAnswer,
    load_pipeline,
)


# Phase 7.5.5 — discursive judge (OAB 2ª-fase rubric scoring).
DISCURSIVE_TOOL: dict[str, Any] = {
    "name": "avaliar_dissertativa_oab",
    "description": (
        "Pontue a resposta da banca contra o gabarito da OAB. Score é normalizado "
        "0.0-1.0 (fraction of max_score). Aplica os critérios FGV."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "score_pct": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "Fração do max_score atribuída à resposta. "
                    "1.0 = cobre todos os pontos do gabarito com fundamentação correta; "
                    "0.75 = cobre maioria com fundamentação OK, pode faltar 1 ponto; "
                    "0.5 = cobre parte central com erro ou omissão relevante; "
                    "0.25 = cobertura mínima ou fundamentação errada com tópico certo; "
                    "0.0 = não respondeu OU completamente errado OU recusou indevidamente."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "1-4 frases justificando: o que acertou, o que faltou, qual o veredicto na escala.",
            },
        },
        "required": ["score_pct", "reasoning"],
    },
}

DISCURSIVE_JUDGE_SYSTEM = """\
Você é um avaliador rigoroso da segunda fase do Exame de Ordem da OAB \
(banca FGV). Sua tarefa: pontuar a resposta de um candidato contra o \
gabarito oficial.

Critérios:
- A resposta precisa identificar a tese jurídica correta, citar os \
dispositivos legais corretos (artigos, leis, súmulas conforme o gabarito), \
e fundamentar com lógica jurídica.
- PENALIZE: omissão de dispositivo central, conclusão jurídica errada, \
recusa indevida quando a questão é respondível, alucinação de dispositivo \
inexistente, peça com endereçamento errado.
- ACEITE: paráfrase de fundamentação se substância é igual; cobertura \
parcial com transparência ("sem prejuízo de outros fundamentos") recebe \
nota intermediária.
- Em peças prático-profissionais (recursos, petições): exija \
endereçamento + autoridade + razões + pedido. Falha em qualquer = score baixo.
- Refusa indevida (responder "não há informação suficiente" quando o \
gabarito tem conteúdo factual respondível) = score_pct ≤ 0.1.

Use a ferramenta `avaliar_dissertativa_oab` pra emitir score_pct e reasoning.
"""


def judge_discursive(
    judge: LLM, question: str, rubric: str, pipeline_answer: str, max_score: float
) -> tuple[float, str]:
    """Opus-4-7 judges pipeline_answer against rubric. Returns (score_pct, reasoning).

    max_score is informational (questions vary 0.65-1.25); score_pct is the
    normalized 0-1 fraction so we can mean across heterogeneous questions.

    Cost note: caller is responsible for reading `judge.last_call_usage`
    AFTER this returns and folding into the RAGAnswer cost fields. See
    `_fold_judge_cost_into_answer()` for the canonical pattern.
    """
    user_msg = (
        f"<questao>\n{question.strip()}\n</questao>\n\n"
        f"<gabarito_oab max_score={max_score}>\n{rubric.strip()}\n</gabarito_oab>\n\n"
        f"<resposta_candidato>\n{pipeline_answer.strip()}\n</resposta_candidato>"
    )
    result = judge.complete_structured(DISCURSIVE_JUDGE_SYSTEM, user_msg, DISCURSIVE_TOOL, max_tokens=1024)
    pct = float(result["score_pct"])
    # Defensive clamp
    pct = max(0.0, min(1.0, pct))
    return pct, str(result["reasoning"])


def _fold_judge_cost_into_answer(ans: RAGAnswer, judge: LLM) -> None:
    """Phase 7.5.7 fix — accumulate the judge's last_call_usage into the
    RAGAnswer cost/token/llm_calls fields, in-place.

    Why: Phase 7.5.2 cost instrumentation only tracked pipeline.llm
    (generation). Judge calls (opus on this codepath) were not measured,
    causing eval logs to undercount LLM-judge runs by ~20× (judge tokens
    × judge price typically dominates Sabiá generation cost). Folding into
    the existing RAGAnswer fields keeps the aggregation logic unchanged
    (sums across records still produce a correct total).

    No-op if judge has no last_call_usage (e.g. judge call failed before
    populating it, or judge implementation doesn't track usage).
    """
    from rag_leis.cost import estimate as _cost_estimate
    usage = getattr(judge, "last_call_usage", None)
    if not usage:
        return
    in_t = int(usage.get("input_tokens", 0))
    out_t = int(usage.get("output_tokens", 0))
    judge_cost = _cost_estimate(judge.provider, judge.name, in_t, out_t)
    ans.cost_estimate_usd = round(ans.cost_estimate_usd + judge_cost, 6)
    if not ans.tokens_used:
        ans.tokens_used = {"input_tokens": 0, "output_tokens": 0}
    ans.tokens_used["input_tokens"] = ans.tokens_used.get("input_tokens", 0) + in_t
    ans.tokens_used["output_tokens"] = ans.tokens_used.get("output_tokens", 0) + out_t
    ans.llm_calls = (ans.llm_calls or 0) + 1

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"
DEFAULT_EVAL_PATH = PROJECT_ROOT / "eval" / "oab_concurso_pilot.yaml"


@dataclass
class ConcursoRow:
    source_id: str
    category: str  # "inscope" | "oos_a" | "oos_b" | "rule_recall" | "discursive"
    query: str
    question_type: str | None = None
    expected_oos_subtype: str | None = None
    gold_urns: frozenset[str] = frozenset()
    correct_alternative_text: str = ""
    notes: str = ""
    # Phase 7.5.5 — discursive category fields. LLM judge scores pipeline
    # answer against `rubric` (gold reference / model answer from oab-bench),
    # output normalized as score_pct (0.0-1.0) of `max_score`.
    rubric: str = ""
    max_score: float = 1.0
    legal_area: str = ""


@dataclass
class ConcursoEvalRecord:
    row: ConcursoRow
    answer: RAGAnswer
    # Per-row computed signals (None when not applicable to category)
    refused_correctly: bool = False
    coverage: float | None = None  # |cited ∩ gold| / |gold| for inscope
    coverage_jaccard: float | None = None
    any_gold_cited: bool | None = None  # binary "at least one hit"
    # Phase 7.5.4 — rule_recall category: did pipeline cite the gold URN?
    # Stricter than `any_gold_cited` (which uses set intersection on the
    # whole gold set); for rule_recall the gold has ONE URN by construction
    # and the pipeline must cite that specific URN. None when not applicable.
    rule_recall_hit: bool | None = None
    # Phase 7.5.5 — discursive category: opus-4-7 judge score, normalized
    # 0.0-1.0 against the rubric's max_score.
    discursive_score_pct: float | None = None
    discursive_reasoning: str = ""


@dataclass
class ConcursoAggregate:
    n_total: int
    n_inscope: int
    n_oos_a: int
    n_oos_b: int
    # In-scope metrics
    inscope_answer_rate: float = 0.0       # not-refused / inscope
    inscope_any_gold_cited_rate: float = 0.0  # at-least-one-gold-URN / inscope
    inscope_coverage_mean: float = 0.0      # avg recall-style coverage
    inscope_coverage_jaccard_mean: float = 0.0
    # OOS metrics
    oos_a_refusal_rate: float = 0.0
    oos_b_refusal_rate: float = 0.0
    # Combined refusal accuracy (oos_a + oos_b should refuse; inscope should not)
    overall_refusal_accuracy: float = 0.0
    # Phase 7.5.4 — rule_recall: external-anchored citation precision.
    # Gold has 1 URN by construction; pipeline must cite that exact URN.
    n_rule_recall: int = 0
    rule_recall_hit_rate: float = 0.0
    rule_recall_answered_rate: float = 0.0  # not-refused / total (precondition for hit)
    # Phase 7.5.5 — discursive: opus judge mean score_pct across rows.
    n_discursive: int = 0
    discursive_mean_pct: float = 0.0
    discursive_answered_rate: float = 0.0  # precondition: pipeline drafted, not refused
    # Phase 7.5.2 — cost + token aggregates (RAGAnswer fields summed across rows).
    cost_total_usd: float = 0.0
    cost_mean_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_llm_calls: int = 0
    # Phase 7.5.7 — SRE Golden Signals (Google SRE Book, Beyer et al. ch.6).
    # Computed from RAGAnswer.latency_ms across rows. p50/p95/p99 are the
    # canonical SLO targets for production; mean is informational only
    # (latency distributions are typically heavy-tailed in RAG pipelines —
    # mean understates tail).
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    latency_mean_ms: float = 0.0
    # Error rate: per-row pipeline exceptions, surfaced via error_count.
    # error_rate = error_count / n_total. SLO target in Phase 8: <1%.
    error_count: int = 0
    error_rate: float = 0.0


def load_rows(path: Path) -> list[ConcursoRow]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[ConcursoRow] = []
    for item in data:
        out.append(ConcursoRow(
            source_id=item["source_id"],
            category=item["category"],
            query=item["query"],
            question_type=item.get("question_type"),
            expected_oos_subtype=item.get("expected_oos_subtype"),
            gold_urns=frozenset(item.get("gold_urns") or []),
            correct_alternative_text=item.get("correct_alternative_text", ""),
            notes=item.get("notes", ""),
            rubric=item.get("rubric", ""),
            max_score=float(item.get("max_score", 1.0)),
            legal_area=item.get("legal_area", ""),
        ))
    return out


def _score_inscope(row: ConcursoRow, ans: RAGAnswer) -> ConcursoEvalRecord:
    """In-scope row: should be answered (not refused) AND citations should
    cover gold."""
    cited = set(ans.citations)
    gold = set(row.gold_urns)
    if not gold:
        coverage = None
        jaccard = None
        any_hit = None
    else:
        hits = cited & gold
        coverage = len(hits) / len(gold) if gold else 0.0
        union = cited | gold
        jaccard = len(hits) / len(union) if union else 0.0
        any_hit = bool(hits)
    # In-scope: refused_correctly is True if NOT refused
    refused_correctly = not ans.refused
    return ConcursoEvalRecord(
        row=row,
        answer=ans,
        refused_correctly=refused_correctly,
        coverage=coverage,
        coverage_jaccard=jaccard,
        any_gold_cited=any_hit,
    )


def _score_oos(row: ConcursoRow, ans: RAGAnswer) -> ConcursoEvalRecord:
    """OOS row: should be refused."""
    return ConcursoEvalRecord(
        row=row,
        answer=ans,
        refused_correctly=ans.refused,
    )


def _score_discursive(
    row: ConcursoRow, ans: RAGAnswer, judge: LLM
) -> ConcursoEvalRecord:
    """Discursive (OAB 2ª-fase) scoring via opus judge against rubric.

    If pipeline refused, score=0 without calling judge (saves money on
    obvious zeros). Otherwise judge gives score_pct in [0, 1].
    """
    if ans.refused:
        return ConcursoEvalRecord(
            row=row,
            answer=ans,
            refused_correctly=False,  # in discursive, refusing is failing
            discursive_score_pct=0.0,
            discursive_reasoning="(pipeline refused; skipped judge)",
        )
    try:
        pct, reasoning = judge_discursive(
            judge, row.query, row.rubric, ans.answer, row.max_score
        )
        # Phase 7.5.7 — fold judge cost in even on success path (this is the
        # bug fix: prior to 7.5.7 the judge spend was never counted).
        _fold_judge_cost_into_answer(ans, judge)
    except Exception as e:
        # Judge failure is rare but possible (rate limit, schema parse).
        # Mark as None so aggregation skips it; reasoning surfaces the cause.
        # Still try to fold partial usage if the SDK populated it before raising.
        _fold_judge_cost_into_answer(ans, judge)
        return ConcursoEvalRecord(
            row=row,
            answer=ans,
            refused_correctly=True,
            discursive_score_pct=None,
            discursive_reasoning=f"JUDGE_ERROR: {type(e).__name__}: {e}",
        )
    return ConcursoEvalRecord(
        row=row,
        answer=ans,
        refused_correctly=True,  # discursive: answered = "correct disposition"
        discursive_score_pct=pct,
        discursive_reasoning=reasoning,
    )


def _score_rule_recall(row: ConcursoRow, ans: RAGAnswer) -> ConcursoEvalRecord:
    """Rule recall row (Phase 7.5.4): gold has 1 URN, pipeline must cite
    that specific URN. Pipeline answering at all is the precondition; rule
    recall hit then checks the specific URN."""
    cited = set(ans.citations)
    gold = set(row.gold_urns)
    # gold has exactly 1 URN by construction (see extract_legalbench_rule_recall)
    hit = bool(cited & gold)
    return ConcursoEvalRecord(
        row=row,
        answer=ans,
        # "refused_correctly" for rule_recall = NOT refused (we want answers)
        refused_correctly=not ans.refused,
        any_gold_cited=hit,
        rule_recall_hit=hit,
    )


def aggregate(records: list[ConcursoEvalRecord]) -> ConcursoAggregate:
    inscope = [r for r in records if r.row.category == "inscope"]
    oos_a = [r for r in records if r.row.category == "oos_a"]
    oos_b = [r for r in records if r.row.category == "oos_b"]
    rule_recall = [r for r in records if r.row.category == "rule_recall"]
    discursive = [r for r in records if r.row.category == "discursive"]

    def _safe_mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    # Phase 7.5.2 — sum cost + token usage across rows.
    cost_total = sum(getattr(r.answer, "cost_estimate_usd", 0.0) or 0.0 for r in records)
    in_tok = sum(
        (getattr(r.answer, "tokens_used", {}) or {}).get("input_tokens", 0) for r in records
    )
    out_tok = sum(
        (getattr(r.answer, "tokens_used", {}) or {}).get("output_tokens", 0) for r in records
    )
    llm_calls = sum(getattr(r.answer, "llm_calls", 0) or 0 for r in records)

    # Phase 7.5.7 — latency percentiles + error rate. Exclude error-marked
    # rows from the latency distribution (their latency reflects time-to-fail,
    # not user-perceived response time of a successful call).
    latencies = sorted(
        float(getattr(r.answer, "latency_ms", 0.0) or 0.0)
        for r in records
        if not (r.answer.refusal_reason or "").startswith("ERROR:")
    )
    error_n = sum(
        1 for r in records if (r.answer.refusal_reason or "").startswith("ERROR:")
    )

    def _pct(xs: list[float], p: float) -> float:
        if not xs:
            return 0.0
        # Nearest-rank percentile (per Beyer SRE Book; matches `numpy
        # percentile(method='lower')` for small N). For n=5, p95 picks
        # rank ceil(5*0.95)=5 (=max). Stable + zero-dep.
        import math
        rank = max(1, math.ceil(len(xs) * p))
        return xs[min(rank, len(xs)) - 1]
    latency_mean = sum(latencies) / len(latencies) if latencies else 0.0

    return ConcursoAggregate(
        n_total=len(records),
        n_inscope=len(inscope),
        n_oos_a=len(oos_a),
        n_oos_b=len(oos_b),
        inscope_answer_rate=_safe_mean([1.0 if not r.answer.refused else 0.0 for r in inscope]),
        inscope_any_gold_cited_rate=_safe_mean(
            [1.0 if r.any_gold_cited else 0.0 for r in inscope if r.any_gold_cited is not None]
        ),
        inscope_coverage_mean=_safe_mean(
            [r.coverage for r in inscope if r.coverage is not None]
        ),
        inscope_coverage_jaccard_mean=_safe_mean(
            [r.coverage_jaccard for r in inscope if r.coverage_jaccard is not None]
        ),
        oos_a_refusal_rate=_safe_mean([1.0 if r.refused_correctly else 0.0 for r in oos_a]),
        oos_b_refusal_rate=_safe_mean([1.0 if r.refused_correctly else 0.0 for r in oos_b]),
        overall_refusal_accuracy=_safe_mean(
            [1.0 if r.refused_correctly else 0.0 for r in records
             if r.row.category != "rule_recall"]  # rule_recall isn't a refusal task
        ),
        n_rule_recall=len(rule_recall),
        rule_recall_hit_rate=_safe_mean(
            [1.0 if r.rule_recall_hit else 0.0 for r in rule_recall]
        ),
        rule_recall_answered_rate=_safe_mean(
            [1.0 if not r.answer.refused else 0.0 for r in rule_recall]
        ),
        n_discursive=len(discursive),
        discursive_mean_pct=_safe_mean(
            [r.discursive_score_pct for r in discursive if r.discursive_score_pct is not None]
        ),
        discursive_answered_rate=_safe_mean(
            [1.0 if not r.answer.refused else 0.0 for r in discursive]
        ),
        cost_total_usd=round(cost_total, 6),
        cost_mean_usd=round(cost_total / len(records), 6) if records else 0.0,
        total_input_tokens=in_tok,
        total_output_tokens=out_tok,
        total_llm_calls=llm_calls,
        latency_p50_ms=round(_pct(latencies, 0.50), 1),
        latency_p95_ms=round(_pct(latencies, 0.95), 1),
        latency_p99_ms=round(_pct(latencies, 0.99), 1),
        latency_mean_ms=round(latency_mean, 1),
        error_count=error_n,
        error_rate=round(error_n / len(records), 4) if records else 0.0,
    )


def print_report(records: list[ConcursoEvalRecord], agg: ConcursoAggregate) -> None:
    print(f"\nConcurso pilot eval — {agg.n_total} rows ({agg.n_inscope} inscope, "
          f"{agg.n_oos_a} oos_a, {agg.n_oos_b} oos_b)")

    print(f"\n{'#':>2}  {'category':<10}  {'src_id':<35}  {'refused':>7}  "
          f"{'cov':>5}  {'gold-hit':>8}  query[:60]")
    for i, r in enumerate(records, 1):
        cat = r.row.category
        ref = "Y" if r.answer.refused else "N"
        cov_str = f"{r.coverage:.2f}" if r.coverage is not None else "  -  "
        hit_str = "Y" if r.any_gold_cited else ("N" if r.any_gold_cited is False else "-")
        ok = "✓" if r.refused_correctly else "✗"
        print(f"{i:>2}  [{ok}] {cat:<6}  {r.row.source_id[-30:]:<30}  {ref:>7}  "
              f"{cov_str:>5}  {hit_str:>8}  {r.row.query[:60]}")

    print(f"\n--- IN-SCOPE ---")
    print(f"  answer_rate (not-refused):          {agg.inscope_answer_rate:.3f}  "
          f"({agg.n_inscope} rows)")
    print(f"  any_gold_cited_rate:                {agg.inscope_any_gold_cited_rate:.3f}")
    print(f"  coverage_mean (|cited∩gold|/|gold|):{agg.inscope_coverage_mean:.3f}")
    print(f"  coverage_jaccard_mean:              {agg.inscope_coverage_jaccard_mean:.3f}")
    print(f"\n--- OOS ---")
    print(f"  oos_a refusal_rate (other domain):  {agg.oos_a_refusal_rate:.3f}  "
          f"({agg.n_oos_a} rows)")
    print(f"  oos_b refusal_rate (adjacent):      {agg.oos_b_refusal_rate:.3f}  "
          f"({agg.n_oos_b} rows)")
    if agg.n_discursive > 0:
        print(f"\n--- DISCURSIVE (Phase 7.5.5 — OAB 2ª-fase opus judge) ---")
        print(f"  n_discursive:                       {agg.n_discursive}")
        print(f"  discursive_answered_rate:           {agg.discursive_answered_rate:.3f}  "
              f"(precondition: not refused)")
        print(f"  discursive_mean_pct:                {agg.discursive_mean_pct:.3f}  "
              f"(judge 0.0-1.0 normalized)")

    if agg.n_rule_recall > 0:
        print(f"\n--- RULE RECALL (Phase 7.5.4 — external-anchored citation precision) ---")
        print(f"  n_rule_recall:                      {agg.n_rule_recall}")
        print(f"  rule_recall_answered_rate:          {agg.rule_recall_answered_rate:.3f}  "
              f"(precondition: not refused)")
        print(f"  rule_recall_hit_rate:               {agg.rule_recall_hit_rate:.3f}  "
              f"(gold URN in pipeline.citations)")

    print(f"\n--- OVERALL ---")
    print(f"  overall_refusal_accuracy:           {agg.overall_refusal_accuracy:.3f}")
    if agg.cost_total_usd > 0 or agg.total_llm_calls > 0:
        print(f"\n--- COST (Phase 7.5.2 instrumentation; judge cost folded since 7.5.7) ---")
        print(f"  cost_total_usd:                     ${agg.cost_total_usd:.4f}")
        print(f"  cost_mean_usd (per query):          ${agg.cost_mean_usd:.6f}")
        print(f"  total_llm_calls (incl. retries):    {agg.total_llm_calls}")
        print(f"  total_input/output tokens:          "
              f"{agg.total_input_tokens:,} / {agg.total_output_tokens:,}")

    print(f"\n--- SRE GOLDEN SIGNALS (Phase 7.5.7) ---")
    print(f"  latency p50/p95/p99/mean ms:        "
          f"{agg.latency_p50_ms:.1f} / {agg.latency_p95_ms:.1f} / "
          f"{agg.latency_p99_ms:.1f} / {agg.latency_mean_ms:.1f}")
    print(f"  error_count / error_rate:           "
          f"{agg.error_count} / {agg.error_rate:.4f}")


def serialize_record(r: ConcursoEvalRecord) -> dict[str, Any]:
    """JSON-serializable per-row record for the run log."""
    return {
        "row": {
            "source_id": r.row.source_id,
            "category": r.row.category,
            "query": r.row.query,
            "question_type": r.row.question_type,
            "expected_oos_subtype": r.row.expected_oos_subtype,
            "gold_urns": sorted(r.row.gold_urns),
            "notes": r.row.notes,
        },
        "answer": {
            "text": r.answer.answer,
            "citations": r.answer.citations,
            "refused": r.answer.refused,
            "refusal_reason": r.answer.refusal_reason,
            "rejected_citations": r.answer.rejected_citations,
            "unverified_claims": r.answer.unverified_claims,
            "hierarchy_warning": r.answer.hierarchy_warning,
            # Phase 7.5.2 — per-row cost/token accounting
            "cost_estimate_usd": getattr(r.answer, "cost_estimate_usd", 0.0),
            "tokens_used": getattr(r.answer, "tokens_used", {}),
            "llm_calls": getattr(r.answer, "llm_calls", 0),
            # Phase 7.5.7 — SRE: end-to-end pipeline latency
            "latency_ms": getattr(r.answer, "latency_ms", 0.0),
        },
        "scoring": {
            "refused_correctly": r.refused_correctly,
            "coverage": r.coverage,
            "coverage_jaccard": r.coverage_jaccard,
            "any_gold_cited": r.any_gold_cited,
            "rule_recall_hit": r.rule_recall_hit,
            "discursive_score_pct": r.discursive_score_pct,
            "discursive_reasoning": r.discursive_reasoning,
        },
    }


def main() -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--eval", default=str(DEFAULT_EVAL_PATH))
    p.add_argument("--output", default=None,
                   help="Write full per-row report to this JSON file.")
    p.add_argument("--llm-provider", default="maritaca",
                   help="LLM provider for the generator (default: maritaca, "
                        "matching production).")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    args = p.parse_args()

    eval_path = Path(args.eval)
    if not eval_path.is_absolute():
        eval_path = (PROJECT_ROOT / eval_path).resolve()
    rows = load_rows(eval_path)
    try:
        shown = eval_path.relative_to(PROJECT_ROOT)
    except ValueError:
        shown = eval_path
    print(f"Loaded {len(rows)} rows from {shown}")

    print(f"Building pipeline (Voyage + {args.llm_provider}, "
          f"text_mode={DEFAULT_TEXT_MODE}, top_k={args.top_k}) ...")
    pipe = load_pipeline(
        chunks_dir=CHUNKS_DIR,
        index_dir=INDEX_DIR,
        llm_provider=args.llm_provider,
        top_k=args.top_k,
    )

    records: list[ConcursoEvalRecord] = []
    for i, row in enumerate(rows, 1):
        print(f"  [{i:>2}/{len(rows)}] [{row.category}] {row.source_id} ...", end="", flush=True)
        # Phase 7.5.7 — pipeline error handling. Without this, one bad row
        # (rate limit mid-run, transient transport error) would crash the
        # whole eval and lose all completed work. We mark the row as errored,
        # surface it in the error_count aggregate, and proceed. The error
        # marker convention (refusal_reason starts with "ERROR:") is read
        # by the aggregate function to count errors + exclude from latency.
        try:
            ans = pipe.answer(row.query)
        except Exception as e:
            ans = RAGAnswer(
                answer="",
                citations=[],
                unverified_claims=[],
                rejected_citations=[],
                refused=True,
                refusal_reason=f"ERROR: {type(e).__name__}: {e}",
                raw_retrieval=[],
            )
        if row.category == "inscope":
            rec = _score_inscope(row, ans)
        elif row.category == "rule_recall":
            rec = _score_rule_recall(row, ans)
        elif row.category == "discursive":
            # Lazy-init judge — only build if a discursive row appears.
            if not hasattr(main, "_judge_cache"):
                main._judge_cache = get_llm("anthropic", DEFAULT_JUDGE_MODEL)  # type: ignore[attr-defined]
            rec = _score_discursive(row, ans, main._judge_cache)  # type: ignore[attr-defined]
        else:  # oos_a or oos_b
            rec = _score_oos(row, ans)
        records.append(rec)
        mark = "✓" if rec.refused_correctly else "✗"
        extra = ""
        if rec.rule_recall_hit is not None:
            extra = f" hit={rec.rule_recall_hit}"
        if rec.discursive_score_pct is not None:
            extra = f" score={rec.discursive_score_pct:.2f}"
        print(f" {mark} refused={ans.refused}{extra}")

    agg = aggregate(records)
    print_report(records, agg)

    if args.output:
        # Resolve to absolute so the run can be invoked from any cwd; only
        # use relative_to when the output is actually under PROJECT_ROOT
        # (typical case: eval/runs/*.json).
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = (PROJECT_ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "config": {
                        "embedder": DEFAULT_EMBEDDER,
                        "text_mode": DEFAULT_TEXT_MODE,
                        "llm_provider": args.llm_provider,
                        "top_k": args.top_k,
                        "oos_threshold": DEFAULT_OOS_THRESHOLD,
                    },
                    "aggregate": asdict(agg),
                    "records": [serialize_record(r) for r in records],
                },
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            shown = out_path.relative_to(PROJECT_ROOT)
        except ValueError:
            shown = out_path
        print(f"\nWrote report → {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
