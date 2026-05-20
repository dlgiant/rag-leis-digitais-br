"""Phase 7.8.2 — cached-data sweep for three gate-predicate variants.

Reads the Phase 7.8.1 in-scope eval JSON (which now serializes
rejected_irrelevant_citations) and projects what would have happened
under three different gate predicates:

  Option A: fire if (n_irrel / n_cits) >= T          [pure threshold]
  Option B: fire if n_cits >= K AND (n_irrel/n_cits) >= T   [+ guard]
  Option C: fire if (n_irrel/n_cits) >= T[classified_type]  [adaptive]

All projections are deterministic — the LLM was already called; we're
just re-evaluating the predicate. No new API spend.

The baseline (current Phase 7.8 gate) is T=1.00 in Option A.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path("/home/ricardo/rag-leis-digitais-br")
EVAL = json.load(open(ROOT / "eval/runs/phase-7.8.1-inscope-opus-relevance.json"))
ROWS = EVAL["rows"]


def pct_irrelevant(row) -> float:
    n_cits = len(row.get("citations", []))
    n_irrel = len(row.get("rejected_irrelevant_citations", []))
    return (n_irrel / n_cits) if n_cits > 0 else 0.0


def gate_fired_in_run(row) -> bool:
    """Was the relevance gate the actual reason this row was refused in 7.8.1?"""
    return row.get("refused", False) and row.get("refusal_reason") == "irrelevant-citations-implicit-refusal"


def evaluate_variant(predicate) -> dict:
    """Apply `predicate(row) -> bool` and report projected metrics."""
    inscope_total = sum(1 for r in ROWS if not r["oos"])
    oos_total = sum(1 for r in ROWS if r["oos"])
    inscope_now_refused = 0
    oos_already_refused = 0
    oos_newly_caught = 0
    new_inscope_fr_rows = []
    new_oos_catches = []
    for r in ROWS:
        was_refused = r.get("refused", False)
        # Would the gate fire under this predicate?
        new_gate = predicate(r) if len(r.get("citations", [])) > 0 else False
        # Effective refusal: was_refused OR new_gate (if gate didn't already fire)
        # When the gate already fired in the original run, that refusal stays
        # under any predicate that's at least as lenient — but if a strictly-
        # stricter predicate would now NOT fire, the refusal would un-fire.
        # We're only loosening the predicate here (T from 1.00 down to e.g. 0.80),
        # so the original gate-fires are a subset of the new gate-fires.
        # Hence effective_refused = was_refused_for_other_reason OR new_gate
        was_refused_for_other_reason = was_refused and not gate_fired_in_run(r)
        effective_refused = was_refused_for_other_reason or new_gate
        if r["oos"]:
            if effective_refused:
                oos_already_refused += 1
                if new_gate and not was_refused:
                    oos_newly_caught += 1
                    new_oos_catches.append(r)
        else:
            if effective_refused and not was_refused:
                inscope_now_refused += 1
                new_inscope_fr_rows.append(r)
    # Final aggregates
    total_inscope_refused = inscope_now_refused + sum(1 for r in ROWS if not r["oos"] and r.get("refused"))
    total_oos_refused = oos_already_refused
    return {
        "inscope_false_refusal_rate": total_inscope_refused / inscope_total if inscope_total else 0,
        "oos_refusal_recall": total_oos_refused / oos_total if oos_total else 0,
        "new_inscope_false_refusals": inscope_now_refused,
        "new_oos_catches": oos_newly_caught,
        "new_inscope_fr_rows": [(ROWS.index(r) + 1, r["query"][:60]) for r in new_inscope_fr_rows],
        "new_oos_catch_rows": [(ROWS.index(r) + 1, r["query"][:60]) for r in new_oos_catches],
    }


# ============================================================================
# BASELINE: current gate (≥100%)
# ============================================================================

print("=" * 78)
print("BASELINE — Phase 7.8 strict gate (n_irrel/n_cits >= 1.00)")
print("=" * 78)
baseline = evaluate_variant(lambda r: pct_irrelevant(r) >= 1.00)
print(f"  in-scope false_refusal_rate: {baseline['inscope_false_refusal_rate']:.3f}")
print(f"  OOS refusal recall:          {baseline['oos_refusal_recall']:.3f}")

# ============================================================================
# OPTION A — pure threshold
# ============================================================================

print("\n" + "=" * 78)
print("OPTION A — pure threshold (no n_cits guard, no per-type adaptation)")
print("=" * 78)
print(f"  {'T':6} {'in-scope FR':12} {'OOS recall':11} {'+FR':4} {'+catches':9}")
for T in [0.50, 0.60, 0.67, 0.75, 0.80, 0.90, 1.00]:
    r = evaluate_variant(lambda row, T=T: pct_irrelevant(row) >= T)
    print(f"  {T:.2f}   {r['inscope_false_refusal_rate']:.3f}        {r['oos_refusal_recall']:.3f}       {r['new_inscope_false_refusals']:4} {r['new_oos_catches']:9}")

# ============================================================================
# OPTION B — threshold + n_cits guard
# ============================================================================

print("\n" + "=" * 78)
print("OPTION B — threshold ≥0.80 + n_cits >= K guard")
print("=" * 78)
print(f"  {'K':4} {'in-scope FR':12} {'OOS recall':11} {'+FR':4} {'+catches':9}")
for K in [1, 2, 3, 4, 5]:
    pred = lambda row, K=K: len(row.get("citations", [])) >= K and pct_irrelevant(row) >= 0.80
    r = evaluate_variant(pred)
    print(f"  {K:3}   {r['inscope_false_refusal_rate']:.3f}        {r['oos_refusal_recall']:.3f}       {r['new_inscope_false_refusals']:4} {r['new_oos_catches']:9}")

# ============================================================================
# OPTION C — adaptive by classified_type
# ============================================================================

print("\n" + "=" * 78)
print("OPTION C — adaptive threshold by classified_type")
print("=" * 78)

# Variant C1: strict (1.00) for high-confidence types, 0.80 for parafrase
C1_THRESHOLDS = {
    "definicao":       1.00,
    "citacao-literal": 1.00,
    "enumeracao":      1.00,
    "parafrase":       0.80,
    None:              0.80,  # unclassified
}
# Variant C2: same but tighter on parafrase (0.75)
C2_THRESHOLDS = {**C1_THRESHOLDS, "parafrase": 0.75}
# Variant C3: even more relaxed on parafrase + relaxed enumeracao
C3_THRESHOLDS = {
    "definicao":       1.00,
    "citacao-literal": 1.00,
    "enumeracao":      0.80,
    "parafrase":       0.80,
    None:              0.80,
}

def adaptive_pred(thresholds):
    def pred(row):
        T = thresholds.get(row.get("classified_type"), 0.80)
        return pct_irrelevant(row) >= T
    return pred

for name, thresholds in [
    ("C1 (definicao/cit-literal/enum=1.00, parafrase=0.80)", C1_THRESHOLDS),
    ("C2 (same as C1 but parafrase=0.75)",                    C2_THRESHOLDS),
    ("C3 (definicao/cit-literal=1.00, enum/parafrase=0.80)",  C3_THRESHOLDS),
]:
    r = evaluate_variant(adaptive_pred(thresholds))
    print(f"\n  Variant {name}")
    print(f"    in-scope false_refusal_rate: {r['inscope_false_refusal_rate']:.3f}  (+{r['new_inscope_false_refusals']} new)")
    print(f"    OOS refusal recall:          {r['oos_refusal_recall']:.3f}  (+{r['new_oos_catches']} catches)")
    if r["new_inscope_fr_rows"]:
        print(f"    new in-scope refusals:")
        for idx, q in r["new_inscope_fr_rows"]:
            print(f"      row {idx}: {q}")
    if r["new_oos_catch_rows"]:
        print(f"    new OOS catches:")
        for idx, q in r["new_oos_catch_rows"]:
            print(f"      row {idx}: {q}")

# ============================================================================
# Side-by-side recommendation table
# ============================================================================

print("\n" + "=" * 78)
print("RECOMMENDATION TABLE")
print("=" * 78)
print(f"  {'Variant':50} {'FR':6} {'OOS recall':11} {'Δ FR':6} {'Δ catches':9}")
variants = [
    ("Baseline (≥100%)",                                           lambda r: pct_irrelevant(r) >= 1.00),
    ("A: pure ≥0.80",                                              lambda r: pct_irrelevant(r) >= 0.80),
    ("B: ≥0.80 AND n_cits>=4",                                     lambda r: len(r.get("citations",[]))>=4 and pct_irrelevant(r)>=0.80),
    ("C1: 1.00/1.00/1.00/0.80 (def/lit/enum/paraf)",               adaptive_pred(C1_THRESHOLDS)),
    ("C2: 1.00/1.00/1.00/0.75",                                    adaptive_pred(C2_THRESHOLDS)),
    ("C3: 1.00/1.00/0.80/0.80",                                    adaptive_pred(C3_THRESHOLDS)),
]
for name, pred in variants:
    r = evaluate_variant(pred)
    fr_delta = r['inscope_false_refusal_rate'] - baseline['inscope_false_refusal_rate']
    catch_delta = r['oos_refusal_recall'] - baseline['oos_refusal_recall']
    print(f"  {name:50} {r['inscope_false_refusal_rate']:.3f}  {r['oos_refusal_recall']:.3f}       {fr_delta:+.3f} {catch_delta:+.3f}")
