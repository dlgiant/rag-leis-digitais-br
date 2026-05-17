"""Cost estimation for LLM + embedding API calls (Phase 7.5.2).

Per-provider pricing table + `estimate()` function. Used by:
  - rag_leis.rag.RAGPipeline.answer() — accumulates cost into RAGAnswer.cost_estimate_usd
  - rag_leis.run_answer_eval — aggregates Aggregate.cost_total_usd + cost_mean_usd

Pricing is **hardcoded** and reflects publicly-listed rates as of
2026-05-17. NO live pricing fetch — providers don't publish stable
machine-readable APIs for pricing. Cost is therefore an ESTIMATE; the
authoritative number is on each provider's billing dashboard. Update this
table when a provider changes prices (search for "TODO update pricing
YYYY-MM" comments below to find stale entries).

Why we still bother estimating despite imprecision:
  - Iteration discipline — knowing approximate cost per eval run prevents
    runaway spend during iteration cycles (see memory feedback-paid-api-caution)
  - Per-query observability — `cost_estimate_usd` on RAGAnswer surfaces
    expensive paths (prose-check retry doubles LLM cost on the affected query)
  - Aggregate reporting — `Aggregate.cost_total_usd` printed per eval run
    so the operator sees what each iteration cost
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ----------------------------------------------------------------------------
# Pricing table — USD per 1M tokens. Updated 2026-05-17.
#
# Anthropic public rates: https://www.anthropic.com/pricing
# Maritaca rates: https://www.maritaca.ai/pricing (Sabiá series; approximate)
# Voyage rates: https://docs.voyageai.com/docs/pricing
#
# IMPORTANT: when a provider releases new model versions, ADD a new entry
# rather than editing. Older runs in eval/runs/*.json reference the prices
# in effect at the time of the run; we want comparability.
# ----------------------------------------------------------------------------

PRICING_USD_PER_1M_TOKENS: Final[dict[str, dict[str, dict[str, float]]]] = {
    "anthropic": {
        "claude-sonnet-4-5":  {"input": 3.0,  "output": 15.0},
        "claude-opus-4-7":    {"input": 15.0, "output": 75.0},
        "claude-haiku-4-5":   {"input": 1.0,  "output": 5.0},
    },
    "maritaca": {
        # Sabiá pricing approximate as of 2026-05; check provider dashboard
        # for authoritative rates. TODO: update pricing 2026-Q3.
        "sabia-3":            {"input": 0.50, "output": 2.0},
        "sabia-3.1":          {"input": 0.50, "output": 2.0},
        "sabia-4":            {"input": 0.80, "output": 3.0},
    },
    "voyage": {
        # Embedding model; output cost is 0 (returns vectors, not tokens).
        "voyage-3-large":     {"input": 0.18, "output": 0.0},
        "voyage-3":           {"input": 0.06, "output": 0.0},
    },
}


@dataclass(frozen=True)
class CostBreakdown:
    """Per-call cost record, sized so the JSON log per-row stays compact."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

    def as_dict(self) -> dict[str, object]:
        """JSON-friendly serialization — used in eval run logs."""
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


def estimate(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost in USD for one provider call.

    Returns 0.0 (not None, not raise) when provider/model is unknown — we
    don't want unknown-pricing situations to crash the pipeline. Operator
    sees the missing entry through the Aggregate.cost_total_usd being lower
    than expected, and adds the entry to PRICING_USD_PER_1M_TOKENS.
    """
    prices = PRICING_USD_PER_1M_TOKENS.get(provider, {}).get(model)
    if prices is None:
        return 0.0
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


def breakdown(provider: str, model: str, input_tokens: int, output_tokens: int) -> CostBreakdown:
    """Factory: build a CostBreakdown record. Inverse of as_dict() lookup
    in tests and run logs."""
    return CostBreakdown(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=estimate(provider, model, input_tokens, output_tokens),
    )
