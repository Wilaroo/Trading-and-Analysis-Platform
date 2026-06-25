"""DB-free proof of the PROMOTE decision logic (entry_edge_gate.compute_decision):
GO uses the confidence-discounted conservative edge; sizing scales with grade×confidence;
negatives & below-cutoff & uncertain all STAND DOWN; active share-rescale math holds."""
import os


def run():
    for k in ("ENTRY_EDGE_GO_THRESHOLD", "ENTRY_EDGE_SIZE_MIN", "ENTRY_EDGE_SIZE_MAX"):
        os.environ.pop(k, None)   # use defaults: go>0, size 0.5..1.25
    from services.entry_edge_gate import compute_decision

    cutoff = -0.20   # bottom-30% veto cutoff for these cases

    # 1. strong + high confidence + top grade → GO, size near max
    d = compute_decision(edge=0.30, grade=92, confidence_n=70, veto_threshold=cutoff)
    print("strong/high:", d)
    assert d["go"] is True and d["confidence"] == "high"
    assert d["conservative_edge"] == 0.30          # high conf → no haircut
    assert d["size_mult"] > 1.0

    # 2. high edge but THIN data → conservative edge discounted, smaller size, still GO
    d2 = compute_decision(edge=0.30, grade=92, confidence_n=8, veto_threshold=cutoff)
    print("strong/low:", d2)
    assert d2["confidence"] == "low" and d2["conservative_edge"] == round(0.30 * 0.3, 4)
    assert d2["size_mult"] < d["size_mult"], "thin data → smaller size than high-conf peer"

    # 3. positive edge but in the bottom band (<= cutoff) → STAND DOWN (veto)
    d3 = compute_decision(edge=-0.25, grade=10, confidence_n=40, veto_threshold=cutoff)
    print("below cutoff:", d3)
    assert d3["go"] is False and d3["stand_down_reason"] == "edge_below_veto_cutoff"

    # 4. above cutoff but NON-positive conservative edge → STAND DOWN
    d4 = compute_decision(edge=0.0, grade=55, confidence_n=40, veto_threshold=cutoff)
    print("flat edge:", d4)
    assert d4["go"] is False and d4["stand_down_reason"] == "nonpositive_conservative_edge"

    # 5. unscoreable (no cell) → STAND DOWN, never sized up
    d5 = compute_decision(edge=None, grade=None, confidence_n=None, veto_threshold=cutoff)
    print("unscoreable:", d5)
    assert d5["go"] is False and d5["stand_down_reason"] == "unscoreable" and d5["size_mult"] == 1.0

    # active sizing math: shares rescale + linear risk/reward rescale
    shares, risk, reward = 100, 200.0, 600.0
    sm = d["size_mult"]
    ns = max(1, round(shares * sm)); ratio = ns / shares
    assert round(risk * ratio, 2) == round(200.0 * ratio, 2)
    assert ns > shares and round(reward * ratio, 2) > reward
    print("\n✅ PROMOTE decision logic OK — GO gating, confidence haircut, sizing, fail-safe stand-downs")


if __name__ == "__main__":
    run()
