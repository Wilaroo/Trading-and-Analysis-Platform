"""Tests for backend/scripts/analyze_gate_log.py.

Covers:
- layer classification for every layer prefix emitted by confidence_gate.py
- delta extraction (positive, negative, trailing clauses, neutral lines)
- aggregate correctness (fire rate, mean/median/stdev, decision counts)
- outcome-conditional edge math on outcome_tracked=True docs
- friction heuristic catches the smoke-test case

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_analyze_gate_log.py -v
"""
import sys
from pathlib import Path

# Ensure backend/ is importable for `scripts.*` in both pytest and direct runs
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.analyze_gate_log import (  # noqa: E402
    classify_layer,
    extract_delta,
    layer_deltas_for_doc,
    aggregate,
    verdict_per_layer,
)


# ── classify_layer ──────────────────────────────────────────────────────

def test_classify_layer_matches_all_active_prefixes():
    cases = {
        "Regime BULLISH (score 70) — strongly aligned with long (+20)": "layer_1_regime",
        "Regime NEUTRAL (score 50) — no directional confirmation": "layer_1_regime",
        "Model consensus STRONG (80% of 5 models, avg acc 60%) (+15)": "layer_3_consensus",
        "No trained models for this setup — using regime + quality score only": "layer_3_consensus",
        "Live xgb_setup_scalp_1min CONFIRMS LONG (up, 72% conf, weight 0.8) (+12)": "layer_4_live_pred",
        "Cross-model: consensus + live prediction ALIGNED (+5)": "layer_5_cross_model",
        "Quality score HIGH (82) (+10)": "layer_6_quality",
        "Learning Loop: SCALP winning at 62% (28 trades, EV 0.5R) — boosting confidence +9": "layer_7_learning",
        "CNN visual analysis: HIGH win probability (70%) — pattern 'flag' (85% conf) (+12)": "layer_8_cnn",
        "TFT multi-timeframe CONFIRMS LONG (75% conf, top TF: 1h) (+10)": "layer_9_tft",
        "TFT signal IGNORED — model accuracy 48.0% below 52% threshold": "layer_9_tft",
        "VAE detects BULL TRENDING regime (80% conf) — aligned (+6)": "layer_10_vae",
        "VAE signal IGNORED — regime diversity 0.20 below 0.3 threshold": "layer_10_vae",
        "CNN-LSTM temporal: HIGH win prob (68%), pattern evolving favorably (+10)": "layer_11_cnn_lstm",
        "Ensemble meta-labeler ensemble_scalp: P(win)=72% high — bet-size boost (+10)": "layer_12_ensemble",
        "FinBERT sentiment: bullish (score=+0.55, 5 articles, conf=80%) aligned STRONG (+10)": "layer_13_finbert",
    }
    for line, expected in cases.items():
        assert classify_layer(line) == expected, f"line='{line}' → {classify_layer(line)}"


def test_classify_layer_ignores_decision_lines():
    assert classify_layer("Borderline confidence (30, need 38 for GO) — reducing to 60% size") is None
    assert classify_layer("Insufficient confirmation (12, need 25) — skipping trade") is None
    assert classify_layer("") is None
    assert classify_layer("random unrelated text") is None


# ── extract_delta ───────────────────────────────────────────────────────

def test_extract_delta_positive_and_negative():
    assert extract_delta("Regime BULLISH (+20)") == 20
    assert extract_delta("Regime BEARISH — against long (-10, size -30%)") == -10
    assert extract_delta("Quality score HIGH (82) (+10)") == 10
    assert extract_delta("Live xgb DISAGREES (65% conf) (-5, size -15%)") == -5


def test_extract_delta_neutral_lines_return_none():
    assert extract_delta("Regime NEUTRAL (score 55) — no directional confirmation") is None
    assert extract_delta("Model consensus MIXED (45% of 5 models) — no score adjustment") is None
    assert extract_delta("") is None


# ── layer_deltas_for_doc ────────────────────────────────────────────────

def test_layer_deltas_for_doc_aggregates_per_layer():
    doc = {
        "reasoning": [
            "Regime BULLISH (score 70) — strongly aligned with long (+20)",
            "Model consensus STRONG (80% of 5 models, avg acc 60%) (+15)",
            "Live xgb CONFIRMS LONG (72% conf, weight 0.8) (+12)",
            "Quality score HIGH (82) (+10)",
            "TFT signal IGNORED — model accuracy 48.0% below 52% threshold",  # fires, no delta
            "FinBERT sentiment: bearish (score=-0.60, 4 articles) OPPOSES trade (-5)",
        ]
    }
    d = layer_deltas_for_doc(doc)
    assert d["layer_1_regime"] == 20
    assert d["layer_3_consensus"] == 15
    assert d["layer_4_live_pred"] == 12
    assert d["layer_6_quality"] == 10
    assert d["layer_9_tft"] == 0          # fired neutrally (IGNORED)
    assert d["layer_13_finbert"] == -5
    # Layers that did not fire are absent
    assert "layer_8_cnn" not in d
    assert "layer_11_cnn_lstm" not in d


def test_layer_deltas_sums_multiple_lines_for_same_layer():
    # Defense-in-depth: if one layer somehow emits two reasoning lines we sum them
    doc = {
        "reasoning": [
            "Learning Loop: SCALP winning at 62% — boosting +9",
            "Learning Loop: edge_declining flag -5",
        ]
    }
    d = layer_deltas_for_doc(doc)
    # Neither of these has a trailing (+N) group — treated as neutral (0) fire
    assert d["layer_7_learning"] == 0


# ── aggregate ───────────────────────────────────────────────────────────

def _mk_doc(decision, deltas_by_layer, outcome_tracked=False, outcome=None):
    """Helper: build a minimal gate_log doc with given per-layer reasoning."""
    line_templates = {
        "layer_1_regime": "Regime BULLISH (score 70) — aligned ({:+d})",
        "layer_3_consensus": "Model consensus STRONG ({:+d})",
        "layer_4_live_pred": "Live xgb CONFIRMS ({:+d})",
        "layer_5_cross_model": "Cross-model ALIGNED ({:+d})",
        "layer_6_quality": "Quality score HIGH ({:+d})",
        "layer_7_learning": "Learning Loop: SCALP winning ({:+d})",
        "layer_8_cnn": "CNN visual analysis ({:+d})",
        "layer_9_tft": "TFT multi-timeframe ({:+d})",
        "layer_10_vae": "VAE detects regime ({:+d})",
        "layer_11_cnn_lstm": "CNN-LSTM temporal ({:+d})",
        "layer_12_ensemble": "Ensemble meta-labeler ensemble_x: P(win) ({:+d})",
        "layer_13_finbert": "FinBERT sentiment ({:+d})",
    }
    reasoning = []
    for key, delta in deltas_by_layer.items():
        reasoning.append(line_templates[key].format(delta))
    return {
        "decision": decision,
        "reasoning": reasoning,
        "outcome_tracked": outcome_tracked,
        "trade_outcome": outcome,
    }


def test_aggregate_decision_counts_and_fire_rate():
    docs = [
        _mk_doc("GO",     {"layer_1_regime": 20, "layer_6_quality": 10}),
        _mk_doc("GO",     {"layer_1_regime": 15}),
        _mk_doc("SKIP",   {"layer_6_quality": -5}),
        _mk_doc("REDUCE", {"layer_1_regime": 10, "layer_6_quality": 5}),
    ]
    r = aggregate(docs)
    assert r["total_evaluations"] == 4
    assert r["decision_counts"] == {"GO": 2, "REDUCE": 1, "SKIP": 1}

    regime = r["layers"]["layer_1_regime"]
    assert regime["count"] == 3
    assert regime["fire_rate"] == 0.75
    assert regime["positive_count"] == 3
    assert regime["negative_count"] == 0
    assert abs(regime["mean_delta"] - 15.0) < 1e-9

    quality = r["layers"]["layer_6_quality"]
    assert quality["count"] == 3
    assert quality["positive_count"] == 2
    assert quality["negative_count"] == 1


def test_aggregate_outcome_edge_math():
    # Baseline: 4/8 wins = 50%.
    # Layer 1 fires positive in 4 tracked trades: 3 wins, 1 loss → WR=75%, edge=+25%
    # Layer 6 fires negative in 3 tracked trades: 0 wins → WR=0%, edge=-50%
    docs = []
    # 4 positive-regime wins/losses
    docs.append(_mk_doc("GO", {"layer_1_regime": 20}, outcome_tracked=True, outcome="win"))
    docs.append(_mk_doc("GO", {"layer_1_regime": 20}, outcome_tracked=True, outcome="win"))
    docs.append(_mk_doc("GO", {"layer_1_regime": 20}, outcome_tracked=True, outcome="win"))
    docs.append(_mk_doc("GO", {"layer_1_regime": 15}, outcome_tracked=True, outcome="loss"))
    # 3 negative-quality losers
    docs.append(_mk_doc("REDUCE", {"layer_6_quality": -5}, outcome_tracked=True, outcome="loss"))
    docs.append(_mk_doc("REDUCE", {"layer_6_quality": -5}, outcome_tracked=True, outcome="loss"))
    docs.append(_mk_doc("REDUCE", {"layer_6_quality": -5}, outcome_tracked=True, outcome="loss"))
    # 1 neutral win to get baseline to 4/8
    docs.append(_mk_doc("GO", {"layer_4_live_pred": 5}, outcome_tracked=True, outcome="win"))

    r = aggregate(docs)
    assert r["outcome_tracked"] == 8
    assert r["baseline_win_rate"] == 0.5

    regime = r["layers"]["layer_1_regime"]
    assert regime["tracked_outcomes"] == 4
    assert regime["n_positive_tracked"] == 4
    assert regime["win_rate_when_positive"] == 0.75
    assert regime["edge_when_positive"] == 0.25

    quality = r["layers"]["layer_6_quality"]
    assert quality["n_negative_tracked"] == 3
    assert quality["win_rate_when_negative"] == 0.0
    assert quality["edge_when_negative"] == -0.5


def test_verdict_flags_friction_layer():
    # Build 120 docs so we clear the LOW DATA threshold, and a friction layer
    # whose positive fires lose consistently.
    docs = []
    # 60 wins baseline via layer_1_regime positive fires → WR=50% overall
    for i in range(60):
        docs.append(_mk_doc("GO", {"layer_1_regime": 20}, outcome_tracked=True, outcome="win"))
    for i in range(60):
        docs.append(_mk_doc("GO", {"layer_1_regime": 20, "layer_13_finbert": 10},
                            outcome_tracked=True, outcome="loss"))
    r = aggregate(docs)
    v = verdict_per_layer(r)
    # FinBERT positive fires only on losses → should flag as FRICTION
    assert "FRICTION" in v["layer_13_finbert"], v["layer_13_finbert"]
