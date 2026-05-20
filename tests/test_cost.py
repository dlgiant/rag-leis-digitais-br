"""Tests for rag_leis.cost — pricing table integrity + estimate correctness.

Pure logic. No network. Pins pricing values so accidental edits break the
test (then operator updates intentionally).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from rag_leis.cost import (
    PRICING_USD_PER_1M_TOKENS,
    CostBreakdown,
    breakdown,
    estimate,
)

# ----------------------------------------------------------------------------
# estimate — arithmetic correctness
# ----------------------------------------------------------------------------


def test_estimate_anthropic_sonnet_typical_request():
    """1000 input + 500 output tokens on sonnet-4-5 at $3/$15 per 1M.
    Cost = 1000*3/1M + 500*15/1M = 0.003 + 0.0075 = 0.0105."""
    cost = estimate("anthropic", "claude-sonnet-4-5", 1000, 500)
    assert cost == pytest.approx(0.0105, rel=1e-9)


def test_estimate_anthropic_opus_higher_than_sonnet():
    """Same tokens: opus must cost more than sonnet."""
    in_t, out_t = 2000, 800
    sonnet = estimate("anthropic", "claude-sonnet-4-5", in_t, out_t)
    opus = estimate("anthropic", "claude-opus-4-7", in_t, out_t)
    assert opus > sonnet


def test_estimate_maritaca_sabia_cheaper_than_sonnet():
    """Sabiá is the production generator partly BECAUSE it's cheaper.
    This test will catch if pricing accidentally inverts."""
    in_t, out_t = 1000, 1000
    sabia = estimate("maritaca", "sabia-3.1", in_t, out_t)
    sonnet = estimate("anthropic", "claude-sonnet-4-5", in_t, out_t)
    assert sabia < sonnet


def test_estimate_voyage_output_cost_is_zero():
    """Voyage embed: output is vectors, not tokens — output cost = 0.
    Total cost should match input_tokens × input_rate only."""
    cost = estimate("voyage", "voyage-3-large", 10000, 999999)
    # 10000 × 0.18 / 1M = 0.0018; the output_tokens are ignored.
    assert cost == pytest.approx(0.0018, rel=1e-9)


def test_estimate_zero_tokens_zero_cost():
    """Edge case: 0/0 tokens → 0 cost (no division-by-zero)."""
    assert estimate("anthropic", "claude-sonnet-4-5", 0, 0) == 0.0


# ----------------------------------------------------------------------------
# estimate — unknown provider/model defensive behavior
# ----------------------------------------------------------------------------


def test_estimate_unknown_provider_returns_zero():
    """Unknown provider → 0.0 (NOT raise). Pipeline must not crash if
    operator forgets to add a new model to the pricing table."""
    assert estimate("openai", "gpt-5", 1000, 500) == 0.0


def test_estimate_unknown_model_within_known_provider_returns_zero():
    """Same: unknown model → 0.0."""
    assert estimate("anthropic", "claude-future-9-7", 1000, 500) == 0.0


# ----------------------------------------------------------------------------
# breakdown factory — builds CostBreakdown dataclass
# ----------------------------------------------------------------------------


def test_breakdown_includes_cost_and_round_trip():
    b = breakdown("anthropic", "claude-sonnet-4-5", 1000, 500)
    assert isinstance(b, CostBreakdown)
    assert b.provider == "anthropic"
    assert b.model == "claude-sonnet-4-5"
    assert b.input_tokens == 1000
    assert b.output_tokens == 500
    assert b.cost_usd == pytest.approx(0.0105, rel=1e-9)


def test_breakdown_as_dict_serializable_and_rounded():
    """as_dict rounds cost to 6 decimals — keeps JSON logs clean.
    fractional cents below 0.000001 USD aren't meaningful."""
    b = breakdown("voyage", "voyage-3-large", 100, 0)
    d = b.as_dict()
    assert d["provider"] == "voyage"
    assert d["model"] == "voyage-3-large"
    assert d["input_tokens"] == 100
    assert d["output_tokens"] == 0
    # 100 × 0.18 / 1M = 0.000018
    assert d["cost_usd"] == 0.000018


def test_cost_breakdown_is_frozen():
    """Dataclass is frozen — accidental mutation should fail."""
    b = breakdown("anthropic", "claude-sonnet-4-5", 1000, 500)
    with pytest.raises(FrozenInstanceError):
        b.cost_usd = 999.0  # type: ignore[misc]


# ----------------------------------------------------------------------------
# Pricing table integrity — pin entries so accidental deletions break test
# ----------------------------------------------------------------------------


def test_pricing_table_includes_known_production_models():
    """The production stack today: voyage-3-large + sabia-3.1 + opus-4-7
    (judge) + sonnet-4-5 (fallback / cross-validation). All 4 must be priced."""
    assert "voyage-3-large" in PRICING_USD_PER_1M_TOKENS["voyage"]
    assert "sabia-3.1" in PRICING_USD_PER_1M_TOKENS["maritaca"]
    assert "claude-opus-4-7" in PRICING_USD_PER_1M_TOKENS["anthropic"]
    assert "claude-sonnet-4-5" in PRICING_USD_PER_1M_TOKENS["anthropic"]


def test_pricing_input_rate_never_zero_for_llm_models():
    """Embedding models can have output=0 cost. LLM models should never
    have input=0 — that would silently zero out the LLM cost contribution."""
    for provider in ("anthropic", "maritaca"):
        for model, prices in PRICING_USD_PER_1M_TOKENS[provider].items():
            assert prices["input"] > 0, f"{provider}/{model} has input=0"
            assert prices["output"] > 0, f"{provider}/{model} has output=0"
