"""Phase 2.6 — answer-quality eval over eval/answer_queries.yaml.

For each row in the answer-eval set:

  in-scope rows
    1. run RAGPipeline.answer()
    2. citation precision/recall/F1 vs `gold_urns`
    3. faithfulness (0-5) via opus-4-7 LLM judge against `expected_paragraph`
    4. record rejected_citation_count (hallucination signal)
    5. refusal classifier: in-scope rows should NOT refuse

  OOS rows
    1. run RAGPipeline.answer()
    2. refused_correctly = pipeline.refused
       (we do NOT call the judge on OOS — there's no expected_paragraph
       to compare to in any meaningful sense)

Aggregates: macro means over in-scope rows; refusal accuracy = (correctly
refused OOS + correctly answered in-scope) / total.

Cost: 12 sonnet calls (pipeline) + 12 opus calls (judge) + 3 sonnet calls
(OOS pipeline) ≈ ~$0.30-1.00 per run depending on tokens. Cheap enough
to iterate, expensive enough to not run on every commit.

Usage:
    uv run python -m rag_leis.run_answer_eval                          # default config
    uv run python -m rag_leis.run_answer_eval --top-k 20               # try higher recall
    uv run python -m rag_leis.run_answer_eval --output eval/runs/<name>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
INDEX_DIR = PROJECT_ROOT / "data" / "index"
DEFAULT_EVAL_PATH = PROJECT_ROOT / "eval" / "answer_queries.yaml"


# ----------------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------------


@dataclass
class AnswerQuery:
    query: str
    type: str
    oos: bool
    gold_urns: frozenset[str]
    # URNs that aren't "must-cite" but a senior lawyer would consider
    # naturally co-cited (e.g., a definição's siblings: caput's parágrafos
    # of exceptions). Used to compute lenient citation precision — see
    # score_citations(). Defaults to empty (strict == lenient).
    alternative_acceptable_urns: frozenset[str]
    expected_paragraph: str
    # Phase 5.1: OOS subtype taxonomy (a-e). Empty when oos=False.
    #   a = other domain entirely
    #   b = adjacent without coverage
    #   c = projeto de lei não promulgado
    #   d = matéria estadual / municipal
    #   e = doutrina sem positivação
    oos_subtype: str = ""


@dataclass
class EvalRow:
    """Per-query eval record. Some fields only populated for in-scope or OOS."""
    query: AnswerQuery
    answer: RAGAnswer
    # in-scope:
    cit_precision: float | None = None              # strict: |cited ∩ gold| / |cited|
    cit_precision_lenient: float | None = None      # |cited ∩ (gold | alt)| / |cited|
    cit_recall: float | None = None                 # |cited ∩ gold| / |gold| — gold-only
    cit_f1: float | None = None                     # uses strict P
    faithfulness: int | None = None                 # 0-5
    faithfulness_reasoning: str | None = None
    # Phase 7.6.1 — explanation-quality dimensions (orthogonal to faithfulness).
    # None on OOS rows (no expected_paragraph, judge doesn't run); None on
    # refused in-scope (same rationale as faithfulness=0 there).
    coherence_score: int | None = None               # 0-5
    quality_score: int | None = None                 # 0-5
    compactness_score: int | None = None             # 0-5
    explanation_reasoning: str | None = None
    # both (refusal sanity):
    refused_correctly: bool = False


# ----------------------------------------------------------------------------
# Judge: structured-output LLM scoring of faithfulness
# ----------------------------------------------------------------------------

FAITHFULNESS_TOOL: dict[str, Any] = {
    "name": "avaliar_fidelidade",
    "description": (
        "Atribua nota 0-5 à fidelidade da resposta gerada em relação à esperada."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 5,
                "description": (
                    "5 = todos fatos essenciais cobertos, sem alucinação. "
                    "4 = cobre fatos essenciais; pode omitir detalhe menor. "
                    "3 = cobertura parcial; sem alucinação significativa. "
                    "2 = parcial com alucinação leve. "
                    "1 = cobertura ruim ou alucinação significativa. "
                    "0 = incorreta ou totalmente alucinada."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "1-3 frases justificando a nota.",
            },
        },
        "required": ["score", "reasoning"],
    },
}

JUDGE_SYSTEM = """\
Você é um avaliador rigoroso de fidelidade entre uma resposta esperada \
(referência jurídica curada por humano) e uma resposta gerada por um sistema RAG.

Critérios:
- IGNORE diferenças de estilo, ordem dos fatos, ou paráfrases semanticamente equivalentes.
- PENALIZE fatos adicionados na resposta gerada APENAS se forem factualmente incorretos \
ou se CONTRADISSEREM a resposta esperada. Fatos adicionais corretos (e relacionados) \
não devem reduzir a nota.
- Listas parciais (enumerações cobrindo subset dos itens esperados) recebem nota 3-4 \
quando a resposta gerada SE DECLARA incompleta ou usa "entre outros / entre eles"; \
recebem 2-3 quando se apresenta como exaustiva indevidamente.
- Refusas indevidas em queries respondíveis (ex: "Não há informação suficiente" quando \
a esperada tem conteúdo factual) recebem nota 0-1.

Use a ferramenta `avaliar_fidelidade` pra emitir score (0-5) e reasoning conciso.
"""


def judge_faithfulness(
    judge: LLM, expected: str, generated: str
) -> tuple[int, str]:
    user_msg = (
        f"<expected>\n{expected.strip()}\n</expected>\n\n"
        f"<generated>\n{generated.strip()}\n</generated>"
    )
    result = judge.complete_structured(JUDGE_SYSTEM, user_msg, FAITHFULNESS_TOOL)
    score = int(result["score"])
    reasoning = str(result["reasoning"])
    # Defensive clamp — schema declares 0..5 but Anthropic doesn't always
    # enforce min/max in tool input, depending on the model.
    score = max(0, min(5, score))
    return score, reasoning


# ----------------------------------------------------------------------------
# Judge: explanation quality (Phase 7.6.1)
#
# Faithfulness measures "does the answer match expected_paragraph." Explanation
# quality is orthogonal: even a factually faithful answer can be incoherent,
# bloated, or evasive. Three axes per Springer 2025 Graph-RAG paper:
#
#   coherence       — does the answer hang together as legal reasoning?
#   general_quality — overall reader-perceived usefulness
#   compactness     — as short as possible while staying complete
#
# Each 0-5. Closes audit doc Gap #4 (RAGAS Answer Relevance). Same judge
# instance as faithfulness; called immediately after with the same
# question + generated text. Cost folded into RAGAnswer immediately
# because judge.last_call_usage is overwritten per call.
# ----------------------------------------------------------------------------

EXPLANATION_QUALITY_TOOL: dict[str, Any] = {
    "name": "avaliar_qualidade_explicacao",
    "description": (
        "Pontue três dimensões ortogonais da qualidade da explicação jurídica: "
        "coerência, qualidade geral, e compacidade. Cada uma 0-5."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "coherence": {
                "type": "integer",
                "minimum": 0,
                "maximum": 5,
                "description": (
                    "Lógica jurídica da resposta. "
                    "5 = encadeia premissas → dispositivos → conclusão sem saltos. "
                    "3 = lógica clara mas com 1-2 transições abruptas. "
                    "1 = afirmações desconectadas; sem fio condutor. "
                    "0 = contradições internas ou non-sequiturs."
                ),
            },
            "general_quality": {
                "type": "integer",
                "minimum": 0,
                "maximum": 5,
                "description": (
                    "Utilidade prática para um leitor jurídico. "
                    "5 = responde a pergunta + agrega contexto pertinente. "
                    "3 = responde, mas sem contextualização. "
                    "1 = resposta vaga ou tangencial à pergunta. "
                    "0 = não responde à pergunta feita."
                ),
            },
            "compactness": {
                "type": "integer",
                "minimum": 0,
                "maximum": 5,
                "description": (
                    "Densidade informacional sem repetição/preenchimento. "
                    "5 = cada frase agrega; sem redundância. "
                    "3 = uma ou duas frases poderiam sair sem perda. "
                    "1 = ~30% do texto é preenchimento / repetição. "
                    "0 = muro de texto cuja densidade real é baixa."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "1-3 frases justificando as três notas.",
            },
        },
        "required": ["coherence", "general_quality", "compactness", "reasoning"],
    },
}

EXPLANATION_JUDGE_SYSTEM = """\
Você avalia a qualidade da EXPLICAÇÃO produzida por um sistema RAG jurídico, \
em três dimensões ortogonais à fidelidade factual.

Foco:
- **Coerência**: a resposta tem fio condutor de raciocínio jurídico? \
Premissas → dispositivos citados → conclusão fluem?
- **Qualidade geral**: a resposta efetivamente RESPONDE à pergunta feita? \
Resposta tangencial ou "fala sobre o tema sem responder" pontua baixo \
mesmo quando factualmente correta.
- **Compacidade**: a resposta é tão curta quanto pode ser sem perder o \
essencial? Preenchimento, repetição, e disclaimers genéricos puxam a nota \
pra baixo.

NÃO avalie precisão factual aqui — isso é função do juiz de faithfulness. \
Uma resposta factualmente errada mas bem estruturada pode receber notas \
altas nas três dimensões; uma resposta certa mas confusa pode receber \
notas baixas em coerência.

Use a ferramenta `avaliar_qualidade_explicacao` pra emitir as três notas \
+ reasoning conciso.
"""


def judge_explanation_quality(
    judge: LLM, question: str, generated: str
) -> tuple[int, int, int, str]:
    """Score the explanation on coherence / general_quality / compactness.

    Returns (coherence, general_quality, compactness, reasoning), each 0-5.
    Defensive clamp on every axis.
    """
    user_msg = (
        f"<pergunta>\n{question.strip()}\n</pergunta>\n\n"
        f"<resposta_gerada>\n{generated.strip()}\n</resposta_gerada>"
    )
    result = judge.complete_structured(
        EXPLANATION_JUDGE_SYSTEM, user_msg, EXPLANATION_QUALITY_TOOL
    )
    coherence = max(0, min(5, int(result["coherence"])))
    quality = max(0, min(5, int(result["general_quality"])))
    compactness = max(0, min(5, int(result["compactness"])))
    reasoning = str(result["reasoning"])
    return coherence, quality, compactness, reasoning


# ----------------------------------------------------------------------------
# Loaders & scorers
# ----------------------------------------------------------------------------


def load_answer_queries(path: Path) -> list[AnswerQuery]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[AnswerQuery] = []
    for item in raw:
        out.append(
            AnswerQuery(
                query=item["query"],
                type=item["type"],
                oos=bool(item.get("oos", False)),
                gold_urns=frozenset(item.get("gold_urns") or []),
                alternative_acceptable_urns=frozenset(
                    item.get("alternative_acceptable_urns") or []
                ),
                expected_paragraph=str(item.get("expected_paragraph", "")),
                oos_subtype=str(item.get("oos_subtype", "")),
            )
        )
    return out


def _safe_div(a: float, b: float) -> float:
    return a / b if b > 0 else 0.0


def score_citations(
    cited: list[str],
    gold: frozenset[str],
    alt: frozenset[str] = frozenset(),
) -> tuple[float, float, float, float]:
    """Citation metrics.

    Returns (precision_strict, precision_lenient, recall, f1_strict).

      precision_strict  = |cited ∩ gold|        / |cited|
      precision_lenient = |cited ∩ (gold | alt)| / |cited|
      recall            = |cited ∩ gold|        / |gold|     — gold-only by design;
        alt is an "OK to cite" set, not a "must cite" set, so it doesn't
        change the recall denominator
      f1_strict         = harmonic of strict precision and recall

    Empty-gold case (OOS sentinel): all metrics 0. Empty-cited case (model
    refused or cited nothing despite gold existing): precision metrics 0
    by convention; surfaces alongside the refusal flag so callers can
    distinguish "refused" from "answered with no cites".

    `alt` defaults to empty → strict == lenient. Add per-row alts in
    eval/answer_queries.yaml when the gold is intentionally narrow but
    sibling chunks (parágrafos, alíneas, related incisos) would be
    legitimately cited by a senior lawyer answering the same question.
    """
    if not gold:
        return 0.0, 0.0, 0.0, 0.0
    cited_set = set(cited)
    hits = len(cited_set & gold)
    hits_lenient = len(cited_set & (gold | alt))
    n_cited = len(cited_set)
    precision = _safe_div(hits, n_cited)
    precision_lenient = _safe_div(hits_lenient, n_cited)
    recall = _safe_div(hits, len(gold))
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return precision, precision_lenient, recall, f1


def score_in_scope(
    q: AnswerQuery, answer: RAGAnswer, judge: LLM
) -> EvalRow:
    prec, prec_lenient, rec, f1 = score_citations(
        answer.citations, q.gold_urns, q.alternative_acceptable_urns
    )
    if answer.refused:
        # Model refused on an answerable query → judge can't score the
        # (empty) generated answer fairly; assign 0 and mark.
        faithfulness, reasoning = 0, "Refusal on in-scope query."
        coherence = quality = compactness = None
        explanation_reasoning = "Refusal on in-scope query — explanation-quality not scored."
    else:
        from rag_leis.cost import estimate as _cost_estimate

        def _fold_judge_usage_in_place(ans: RAGAnswer, j: LLM) -> None:
            """Read j.last_call_usage and fold into ans cost/tokens/llm_calls.
            Must be called IMMEDIATELY after each judge call — last_call_usage
            is overwritten on the next call (Phase 7.5.7 bug fix infra)."""
            usage = getattr(j, "last_call_usage", None)
            if not usage:
                return
            in_t = int(usage.get("input_tokens", 0))
            out_t = int(usage.get("output_tokens", 0))
            judge_cost = _cost_estimate(j.provider, j.name, in_t, out_t)
            ans.cost_estimate_usd = round(ans.cost_estimate_usd + judge_cost, 6)
            if not ans.tokens_used:
                ans.tokens_used = {"input_tokens": 0, "output_tokens": 0}
            ans.tokens_used["input_tokens"] = ans.tokens_used.get("input_tokens", 0) + in_t
            ans.tokens_used["output_tokens"] = ans.tokens_used.get("output_tokens", 0) + out_t
            ans.llm_calls = (ans.llm_calls or 0) + 1

        # Faithfulness judge call (existing — Phase 4).
        faithfulness, reasoning = judge_faithfulness(
            judge, q.expected_paragraph, answer.answer
        )
        _fold_judge_usage_in_place(answer, judge)

        # Phase 7.6.1 — explanation-quality judge (NEW). Fold immediately
        # because `judge.last_call_usage` is overwritten on the next call.
        coherence, quality, compactness, explanation_reasoning = judge_explanation_quality(
            judge, q.query, answer.answer
        )
        _fold_judge_usage_in_place(answer, judge)
    return EvalRow(
        query=q,
        answer=answer,
        cit_precision=prec,
        cit_precision_lenient=prec_lenient,
        cit_recall=rec,
        cit_f1=f1,
        faithfulness=faithfulness,
        faithfulness_reasoning=reasoning,
        coherence_score=coherence,
        quality_score=quality,
        compactness_score=compactness,
        explanation_reasoning=explanation_reasoning,
        refused_correctly=(not answer.refused),  # in-scope: should NOT refuse
    )


def score_oos(q: AnswerQuery, answer: RAGAnswer) -> EvalRow:
    return EvalRow(
        query=q,
        answer=answer,
        refused_correctly=answer.refused,  # OOS: SHOULD refuse
    )


# ----------------------------------------------------------------------------
# Aggregation & reporting
# ----------------------------------------------------------------------------


@dataclass
class Aggregate:
    n_total: int
    n_inscope: int
    n_oos: int
    cit_precision_mean: float                  # strict
    cit_precision_lenient_mean: float
    cit_recall_mean: float
    cit_f1_mean: float
    faithfulness_mean: float
    # Phase 7.6.1 — explanation-quality means (orthogonal to faithfulness).
    # In-scope only; rows where the judge didn't score (refusals) skipped via
    # the `or 0` pattern (consistent with faithfulness_mean).
    coherence_mean: float
    quality_mean: float
    compactness_mean: float
    refusal_accuracy: float
    # Phase 7.5.1 — refusal split into the two confusion-matrix dimensions.
    # `refusal_accuracy` above (the macro avg of both) collapsed two distinct
    # production-quality dimensions into one number; the split surfaces them:
    #
    #   false_refusal_rate = |inscope ∩ refused| / |inscope|
    #     — fraction of in-scope queries where the pipeline incorrectly
    #     refused. User-facing quality bug; should approach 0.
    #
    #   oos_refusal_recall = |oos ∩ refused| / |oos|
    #     — fraction of OOS queries where the pipeline correctly refused.
    #     Safety success; should approach 1.
    #
    # Surfacing both lets us see the trade-off explicitly: a SYSTEM_PROMPT
    # iteration that increases OOS recall at the cost of false refusals is
    # different from one that fixes both. Concurso pilot (2026-05-17)
    # measured false_refusal_rate=0% in-scope but oos_refusal_recall=44%
    # — the macro `refusal_accuracy` of 62.5% hid that the OOS side was the
    # problem.
    false_refusal_rate: float = 0.0
    oos_refusal_recall: float = 0.0
    rejected_citation_rate: float = 0.0  # |rejected| / |cited+rejected|
    by_type: dict[str, dict[str, float]] = field(default_factory=dict)
    # Phase 5.1: per-OOS-subtype refusal accuracy. Surfaces where the
    # pipeline is fragile (typically subtype b — adjacent OOS).
    refusal_accuracy_by_oos_subtype: dict[str, float] = field(default_factory=dict)
    # Phase 7.5.2 — cost + token aggregates across the eval run. Computed
    # from each RAGAnswer.cost_estimate_usd and .tokens_used (which the
    # pipeline populates via llm.last_call_usage + rag_leis.cost.estimate).
    # Lets the operator see "this iteration cost $X" without digging into
    # provider dashboards. cost_mean_usd is per-row mean cost; useful as
    # SLA target ("p95 query under $0.05") in Phase 8.
    cost_total_usd: float = 0.0
    cost_mean_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_llm_calls: int = 0
    # Phase 7.5.7 — SRE Golden Signals (Beyer et al., Google SRE Book ch.6).
    # Same shape as ConcursoAggregate; mean is informational only because RAG
    # latency distributions are heavy-tailed (long LLM-retry rows skew the
    # tail). p95/p99 are the load-bearing SLO targets for Phase 8.
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    latency_mean_ms: float = 0.0
    error_count: int = 0
    error_rate: float = 0.0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(rows: list[EvalRow]) -> Aggregate:
    inscope = [r for r in rows if not r.query.oos]
    oos = [r for r in rows if r.query.oos]

    # rejected citation rate uses BOTH inscope and oos, since both have
    # RAGAnswer with citations; OOS will have 0/0 by definition.
    total_cited = sum(
        len(r.answer.citations) + len(r.answer.rejected_citations) for r in rows
    )
    total_rejected = sum(len(r.answer.rejected_citations) for r in rows)

    by_type: dict[str, dict[str, float]] = {}
    grouped: dict[str, list[EvalRow]] = defaultdict(list)
    for r in rows:
        grouped[r.query.type].append(r)
    for t, group in grouped.items():
        inscope_g = [r for r in group if not r.query.oos]
        by_type[t] = {
            "n": float(len(group)),
            "cit_precision": _mean([r.cit_precision or 0.0 for r in inscope_g]),
            "cit_precision_lenient": _mean(
                [r.cit_precision_lenient or 0.0 for r in inscope_g]
            ),
            "cit_recall": _mean([r.cit_recall or 0.0 for r in inscope_g]),
            "cit_f1": _mean([r.cit_f1 or 0.0 for r in inscope_g]),
            "faithfulness": _mean([float(r.faithfulness or 0) for r in inscope_g]),
            # Phase 7.6.1 — explanation-quality per-type breakdown
            "coherence": _mean([float(r.coherence_score or 0) for r in inscope_g]),
            "quality": _mean([float(r.quality_score or 0) for r in inscope_g]),
            "compactness": _mean([float(r.compactness_score or 0) for r in inscope_g]),
            "refusal_accuracy": _mean([1.0 if r.refused_correctly else 0.0 for r in group]),
        }

    # Phase 5.1: per-OOS-subtype refusal accuracy
    by_subtype: dict[str, list[EvalRow]] = defaultdict(list)
    for r in oos:
        sub = r.query.oos_subtype or "unspecified"
        by_subtype[sub].append(r)
    refusal_acc_by_subtype = {
        sub: _mean([1.0 if r.refused_correctly else 0.0 for r in group])
        for sub, group in by_subtype.items()
    }

    # Phase 7.5.1 — explicit confusion matrix dimensions:
    # in-scope refused (false refusal) vs OOS refused (recall).
    inscope_refused = sum(1 for r in inscope if r.answer.refused)
    oos_refused = sum(1 for r in oos if r.answer.refused)

    # Phase 7.5.2 — cost + token totals across all eval rows. (Judge cost
    # folded into RAGAnswer fields by score_in_scope() since Phase 7.5.7.)
    cost_total = sum(getattr(r.answer, "cost_estimate_usd", 0.0) or 0.0 for r in rows)
    in_tok = sum(
        (getattr(r.answer, "tokens_used", {}) or {}).get("input_tokens", 0) for r in rows
    )
    out_tok = sum(
        (getattr(r.answer, "tokens_used", {}) or {}).get("output_tokens", 0) for r in rows
    )
    llm_calls = sum(getattr(r.answer, "llm_calls", 0) or 0 for r in rows)

    # Phase 7.5.7 — SRE Golden Signals. Exclude error-marked rows from latency
    # distribution (time-to-fail isn't a meaningful user-perceived latency).
    latencies = sorted(
        float(getattr(r.answer, "latency_ms", 0.0) or 0.0)
        for r in rows
        if not (r.answer.refusal_reason or "").startswith("ERROR:")
    )
    error_n = sum(
        1 for r in rows if (r.answer.refusal_reason or "").startswith("ERROR:")
    )

    def _pct(xs: list[float], p: float) -> float:
        if not xs:
            return 0.0
        import math
        rank = max(1, math.ceil(len(xs) * p))
        return xs[min(rank, len(xs)) - 1]
    latency_mean_ms_v = sum(latencies) / len(latencies) if latencies else 0.0

    return Aggregate(
        n_total=len(rows),
        n_inscope=len(inscope),
        n_oos=len(oos),
        cit_precision_mean=_mean([r.cit_precision or 0.0 for r in inscope]),
        cit_precision_lenient_mean=_mean(
            [r.cit_precision_lenient or 0.0 for r in inscope]
        ),
        cit_recall_mean=_mean([r.cit_recall or 0.0 for r in inscope]),
        cit_f1_mean=_mean([r.cit_f1 or 0.0 for r in inscope]),
        faithfulness_mean=_mean([float(r.faithfulness or 0) for r in inscope]),
        # Phase 7.6.1 — explanation-quality means (in-scope; refused→None→0 via `or`)
        coherence_mean=_mean([float(r.coherence_score or 0) for r in inscope]),
        quality_mean=_mean([float(r.quality_score or 0) for r in inscope]),
        compactness_mean=_mean([float(r.compactness_score or 0) for r in inscope]),
        refusal_accuracy=_mean([1.0 if r.refused_correctly else 0.0 for r in rows]),
        false_refusal_rate=_safe_div(inscope_refused, len(inscope)),
        oos_refusal_recall=_safe_div(oos_refused, len(oos)),
        rejected_citation_rate=_safe_div(total_rejected, total_cited),
        by_type=by_type,
        refusal_accuracy_by_oos_subtype=refusal_acc_by_subtype,
        cost_total_usd=round(cost_total, 6),
        cost_mean_usd=round(cost_total / len(rows), 6) if rows else 0.0,
        total_input_tokens=in_tok,
        total_output_tokens=out_tok,
        total_llm_calls=llm_calls,
        latency_p50_ms=round(_pct(latencies, 0.50), 1),
        latency_p95_ms=round(_pct(latencies, 0.95), 1),
        latency_p99_ms=round(_pct(latencies, 0.99), 1),
        latency_mean_ms=round(latency_mean_ms_v, 1),
        error_count=error_n,
        error_rate=round(error_n / len(rows), 4) if rows else 0.0,
    )


def print_report(rows: list[EvalRow], agg: Aggregate, verbose: bool) -> None:
    print()
    print("Per-query results (P_s = strict precision, P_l = lenient precision):")
    print(
        f"  {'#':>2}  {'type':<15}  {'oos':<3}  "
        f"{'refused':<7}  {'P_s':<5}  {'P_l':<5}  {'R':<5}  "
        f"{'F1':<5}  {'faith':<5}  {'rej':<3}  query"
    )
    for i, r in enumerate(rows):
        ref = "Y" if r.answer.refused else "N"
        rej = len(r.answer.rejected_citations)
        if r.query.oos:
            p_str = pl_str = r_str = f_str = fa_str = "  -  "
        else:
            p_str = f"{r.cit_precision:.2f}" if r.cit_precision is not None else "  -  "
            pl_str = (
                f"{r.cit_precision_lenient:.2f}"
                if r.cit_precision_lenient is not None
                else "  -  "
            )
            r_str = f"{r.cit_recall:.2f}" if r.cit_recall is not None else "  -  "
            f_str = f"{r.cit_f1:.2f}" if r.cit_f1 is not None else "  -  "
            fa_str = f"{r.faithfulness}/5" if r.faithfulness is not None else "  -  "
        q_short = r.query.query[:60] + ("…" if len(r.query.query) > 60 else "")
        print(
            f"  {i+1:>2}  {r.query.type:<15}  "
            f"{'Y' if r.query.oos else 'N':<3}  "
            f"{ref:<7}  {p_str:<5}  {pl_str:<5}  {r_str:<5}  "
            f"{f_str:<5}  {fa_str:<5}  {rej:<3}  {q_short}"
        )

    extra_rate = agg.cit_precision_lenient_mean - agg.cit_precision_mean
    print()
    print(f"Aggregate over {agg.n_total} rows ({agg.n_inscope} in-scope, {agg.n_oos} OOS):")
    print(f"  Citation precision strict  (mean, in-scope)  : {agg.cit_precision_mean:.3f}")
    print(f"  Citation precision lenient (mean, in-scope)  : {agg.cit_precision_lenient_mean:.3f}")
    print(f"  Over-citation rate (lenient - strict)         : {extra_rate:+.3f}")
    print(f"  Citation recall            (mean, in-scope)  : {agg.cit_recall_mean:.3f}")
    print(f"  Citation F1 (strict)       (mean, in-scope)  : {agg.cit_f1_mean:.3f}")
    print(f"  Faithfulness               (mean, in-scope)  : {agg.faithfulness_mean:.2f} / 5")
    # Phase 7.6.1 — three orthogonal axes scored by a separate judge call.
    print(f"  Coherence                  (mean, in-scope)  : {agg.coherence_mean:.2f} / 5")
    print(f"  General quality            (mean, in-scope)  : {agg.quality_mean:.2f} / 5")
    print(f"  Compactness                (mean, in-scope)  : {agg.compactness_mean:.2f} / 5")
    print(f"  Refusal accuracy           (all rows, macro)  : {agg.refusal_accuracy:.3f}")
    # Phase 7.5.1 — split refusal into the two confusion-matrix dimensions.
    # In-scope side: should approach 0 (refusing real questions is a bug).
    # OOS side: should approach 1 (refusing OOS is the safety success).
    print(f"  False refusal rate         (in-scope refused) : {agg.false_refusal_rate:.3f}  "
          f"(target: 0; lower = better)")
    print(f"  OOS refusal recall         (OOS refused)      : {agg.oos_refusal_recall:.3f}  "
          f"(target: 1; higher = better)")
    print(f"  Rejected citation rate     (all rows)         : {agg.rejected_citation_rate:.3f}")
    # Phase 7.5.2 — cost reporting (includes folded judge cost since 7.5.7).
    if agg.cost_total_usd > 0 or agg.total_llm_calls > 0:
        print(f"  Cost total                 (USD, this run)    : ${agg.cost_total_usd:.4f}")
        print(f"  Cost per query             (USD, mean)        : ${agg.cost_mean_usd:.6f}")
        print(f"  LLM calls total            (incl. judge)      : {agg.total_llm_calls}")
        print(f"  Tokens total               (input / output)   : "
              f"{agg.total_input_tokens:,} / {agg.total_output_tokens:,}")
    # Phase 7.5.7 — SRE Golden Signals
    print(f"  Latency p50/p95/p99/mean ms                   : "
          f"{agg.latency_p50_ms:.1f} / {agg.latency_p95_ms:.1f} / "
          f"{agg.latency_p99_ms:.1f} / {agg.latency_mean_ms:.1f}")
    print(f"  Error count / error rate                       : "
          f"{agg.error_count} / {agg.error_rate:.4f}")

    if agg.refusal_accuracy_by_oos_subtype:
        print()
        print("OOS refusal accuracy by subtype (Phase 5.1):")
        subtype_labels = {
            "a": "(a) other domain entirely",
            "b": "(b) adjacent without coverage",
            "c": "(c) projeto de lei não promulgado",
            "d": "(d) matéria estadual/municipal",
            "e": "(e) doutrina sem positivação",
        }
        for sub, acc in sorted(agg.refusal_accuracy_by_oos_subtype.items()):
            label = subtype_labels.get(sub, sub)
            mark = "✅" if acc >= 1.0 else ("⚠️" if acc >= 0.5 else "❌")
            print(f"  {mark} {label:<40} {acc:.3f}")

    print()
    print("By type (in-scope metrics; refusal_accuracy includes OOS):")
    print(
        f"  {'type':<16}  {'n':>2}  {'P_s':<5}  {'P_l':<5}  {'R':<5}  "
        f"{'F1':<5}  {'faith':<5}  {'coh':<4}  {'qual':<4}  {'comp':<4}  {'ref_acc':<6}"
    )
    for t in sorted(agg.by_type):
        b = agg.by_type[t]
        print(
            f"  {t:<16}  {int(b['n']):>2}  "
            f"{b['cit_precision']:<5.2f}  {b['cit_precision_lenient']:<5.2f}  "
            f"{b['cit_recall']:<5.2f}  {b['cit_f1']:<5.2f}  "
            f"{b['faithfulness']:<5.2f}  "
            f"{b.get('coherence', 0.0):<4.2f}  "
            f"{b.get('quality', 0.0):<4.2f}  "
            f"{b.get('compactness', 0.0):<4.2f}  "
            f"{b['refusal_accuracy']:<6.3f}"
        )

    if verbose:
        print()
        print("Detail (per-query):")
        for i, r in enumerate(rows):
            print(f"\n[{i+1}] {r.query.query}")
            print(f"   type={r.query.type}  oos={r.query.oos}  refused={r.answer.refused}")
            if r.answer.refusal_reason:
                print(f"   refusal_reason: {r.answer.refusal_reason}")
            if not r.query.oos:
                print(
                    f"   citations  : {len(r.answer.citations)}/{len(r.query.gold_urns)} gold  "
                    f"(P={r.cit_precision:.2f} R={r.cit_recall:.2f} F1={r.cit_f1:.2f})"
                )
                missing = sorted(r.query.gold_urns - set(r.answer.citations))
                extra = sorted(set(r.answer.citations) - r.query.gold_urns)
                if missing:
                    print(f"   missing gold ({len(missing)}):")
                    for u in missing[:5]:
                        print(f"     - {u}")
                    if len(missing) > 5:
                        print(f"     … +{len(missing)-5} more")
                if extra:
                    print(f"   extra cited (not in gold, {len(extra)}):")
                    for u in extra[:5]:
                        print(f"     - {u}")
                if r.answer.rejected_citations:
                    print(f"   rejected   : {len(r.answer.rejected_citations)}")
                    for reason, urn in r.answer.rejected_citations[:3]:
                        print(f"     [{reason}] {urn}")
                if r.faithfulness is not None:
                    print(f"   faithfulness: {r.faithfulness}/5 — {r.faithfulness_reasoning}")
                if r.coherence_score is not None:
                    print(
                        f"   explanation: coh={r.coherence_score}/5 "
                        f"qual={r.quality_score}/5 comp={r.compactness_score}/5 — "
                        f"{r.explanation_reasoning}"
                    )
                if r.answer.unverified_claims:
                    print(f"   unverified_claims ({len(r.answer.unverified_claims)}):")
                    for c in r.answer.unverified_claims[:2]:
                        print(f"     ? {c[:120]}{'…' if len(c) > 120 else ''}")


# ----------------------------------------------------------------------------
# Output serialization (JSON for downstream analysis / write-up)
# ----------------------------------------------------------------------------


def serialize_row(r: EvalRow) -> dict[str, Any]:
    return {
        "query": r.query.query,
        "type": r.query.type,
        "oos": r.query.oos,
        "gold_urns": sorted(r.query.gold_urns),
        "alternative_acceptable_urns": sorted(r.query.alternative_acceptable_urns),
        "expected_paragraph": r.query.expected_paragraph,
        "answer": r.answer.answer,
        "citations": r.answer.citations,
        "rejected_citations": [
            {"reason": rsn, "urn": u} for rsn, u in r.answer.rejected_citations
        ],
        "unverified_claims": r.answer.unverified_claims,
        "refused": r.answer.refused,
        "refusal_reason": r.answer.refusal_reason,
        "raw_retrieval": [
            {"urn": u, "score": s} for u, s in r.answer.raw_retrieval
        ],
        "flagged_vigencia": [
            {
                "urn": fv.urn,
                "status": fv.status,
                "fundamento": fv.fundamento,
                "descricao_curta": fv.descricao_curta,
            }
            for fv in r.answer.flagged_vigencia
        ],
        "classified_type": r.answer.classified_type,
        "classified_top_k": r.answer.classified_top_k,
        "pii_types_redacted": r.answer.pii_types_redacted,
        "hierarchy_warning": r.answer.hierarchy_warning,
        "prose_citation_mismatches": [
            {
                "surface": m.surface,
                "expected_partition": m.expected_partition,
                "nearest_cited_urn": m.nearest_cited_urn,
            }
            for m in r.answer.prose_citation_mismatches
        ],
        "prose_check_retried": r.answer.prose_check_retried,
        "sources_consulted_at": r.answer.sources_consulted_at,
        # Phase 7.5.2 — cost/tokens (includes judge cost since 7.5.7)
        "cost_estimate_usd": getattr(r.answer, "cost_estimate_usd", 0.0),
        "tokens_used": getattr(r.answer, "tokens_used", {}),
        "llm_calls": getattr(r.answer, "llm_calls", 0),
        # Phase 7.5.7 — SRE: end-to-end pipeline latency in ms
        "latency_ms": getattr(r.answer, "latency_ms", 0.0),
        "cit_precision": r.cit_precision,
        "cit_precision_lenient": r.cit_precision_lenient,
        "cit_recall": r.cit_recall,
        "cit_f1": r.cit_f1,
        "faithfulness": r.faithfulness,
        "faithfulness_reasoning": r.faithfulness_reasoning,
        # Phase 7.6.1 — explanation-quality scores (None on OOS / refused)
        "coherence_score": r.coherence_score,
        "quality_score": r.quality_score,
        "compactness_score": r.compactness_score,
        "explanation_reasoning": r.explanation_reasoning,
        "refused_correctly": r.refused_correctly,
    }


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run the answer-eval set against the RAG pipeline."
    )
    p.add_argument("--eval", default=str(DEFAULT_EVAL_PATH), help="Path to answer_queries.yaml")
    p.add_argument("--embedder", default=DEFAULT_EMBEDDER)
    p.add_argument("--text-mode", default=DEFAULT_TEXT_MODE)
    p.add_argument(
        "--llm-provider",
        default="anthropic",
        choices=["anthropic", "maritaca"],
        help="Generator LLM provider (default: anthropic)",
    )
    p.add_argument("--llm-model", default=None, help="Generator model (default: provider's)")
    p.add_argument(
        "--judge-provider",
        default="anthropic",
        choices=["anthropic", "maritaca"],
        help="Judge LLM provider (default: anthropic — opus-4-7)",
    )
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument(
        "--oos-threshold",
        type=float,
        default=DEFAULT_OOS_THRESHOLD,
        help="top-1 cosine sim below which the pipeline refuses",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Optional path to dump per-row JSON for downstream analysis",
    )
    p.add_argument("--verbose", action="store_true", help="Print per-query detail")
    args = p.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)

    print(f"Loading pipeline (embedder={args.embedder}, text_mode={args.text_mode}, top_k={args.top_k})...")
    pipeline = load_pipeline(
        chunks_dir=CHUNKS_DIR,
        index_dir=INDEX_DIR,
        embedder_name=args.embedder,
        text_mode=args.text_mode,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        top_k=args.top_k,
        oos_threshold=args.oos_threshold,
    )
    judge = get_llm(provider=args.judge_provider, model=args.judge_model)
    print(f"Generator: {pipeline.llm.provider}/{pipeline.llm.name}")
    print(f"Judge    : {judge.provider}/{judge.name}")

    queries = load_answer_queries(Path(args.eval))
    print(f"Loaded {len(queries)} queries from {args.eval}")
    print()

    rows: list[EvalRow] = []
    for i, q in enumerate(queries):
        marker = "OOS" if q.oos else q.type
        print(f"  [{i+1}/{len(queries)}] ({marker}) {q.query[:70]}{'…' if len(q.query) > 70 else ''}")
        # Phase 7.5.7 — pipeline error handling: one bad row shouldn't lose
        # the whole eval. Mark with ERROR: prefix so aggregate counts it
        # toward error_count + excludes from latency distribution.
        try:
            ans = pipeline.answer(q.query)
        except Exception as e:
            from rag_leis.rag import RAGAnswer as _RAGAnswer
            ans = _RAGAnswer(
                answer="",
                citations=[],
                unverified_claims=[],
                rejected_citations=[],
                refused=True,
                refusal_reason=f"ERROR: {type(e).__name__}: {e}",
                raw_retrieval=[],
            )
        row = score_oos(q, ans) if q.oos else score_in_scope(q, ans, judge)
        rows.append(row)

    agg = aggregate(rows)
    print_report(rows, agg, verbose=args.verbose)

    if args.output:
        payload = {
            "config": {
                "embedder": args.embedder,
                "text_mode": args.text_mode,
                "llm_model": pipeline.llm.model,
                "judge_model": judge.model,
                "top_k": args.top_k,
                "oos_threshold": args.oos_threshold,
            },
            "aggregate": asdict(agg),
            "rows": [serialize_row(r) for r in rows],
        }
        Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\nWrote per-row JSON → {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
