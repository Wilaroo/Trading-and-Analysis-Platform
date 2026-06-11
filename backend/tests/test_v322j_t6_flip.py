"""
test_v322j_t6_flip.py — contracts for the T6 flip tooling + quarantine-aware
boot diagnostic.

  1. `summarize_shadow` (t6_flip.py): aggregates shadow suppression records
     correctly (counts, tracked outcomes, ignores NONE/missing).
  2. The boot consistency diagnostic separates QUARANTINED (intentional)
     from genuinely MISSING models.
  3. decide_suppression sanity (the function the flip arms): SKIP/REDUCE/
     NONE thresholds and thin-sample behaviour.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

T6_PATH = ROOT.parent / "scripts" / "t6_flip.py"


def _load_t6():
    spec = importlib.util.spec_from_file_location("t6_flip", T6_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_summarize_shadow_aggregation():
    t6 = _load_t6()
    rows = [
        {"regime_suppression": {"action": "SKIP", "matched_key": "vwap_fade|short|BULL>60"},
         "outcome_tracked": True, "trade_outcome": "loss"},
        {"regime_suppression": {"action": "SKIP", "matched_key": "vwap_fade|short|BULL>60"},
         "outcome_tracked": True, "trade_outcome": "win"},
        {"regime_suppression": {"action": "SKIP", "matched_key": "vwap_fade|short|BULL>60"},
         "outcome_tracked": False, "trade_outcome": None},
        {"regime_suppression": {"action": "REDUCE", "canonical_setup": "scalp", "band": "BEAR<=45"},
         "outcome_tracked": True, "trade_outcome": "loss"},
        {"regime_suppression": {"action": "NONE"}, "outcome_tracked": True, "trade_outcome": "win"},
        {"regime_suppression": None, "outcome_tracked": True},
    ]
    agg = t6.summarize_shadow(rows)
    skip = agg[("vwap_fade|short|BULL>60", "SKIP")]
    assert skip == {"n": 3, "tracked": 2, "wins": 1, "losses": 1}, skip
    red = agg[("scalp|BEAR<=45", "REDUCE")]
    assert red == {"n": 1, "tracked": 1, "wins": 0, "losses": 1}, red
    assert len(agg) == 2, "NONE/missing records must be ignored"


def test_boot_diagnostic_separates_quarantined():
    src = (ROOT / "services" / "ai_modules" / "timeseries_service.py").read_text()
    assert "QUARANTINED (intentional, PBO sweep)" in src, (
        "boot diagnostic no longer labels quarantined models separately")
    assert "genuinely_missing" in src
    assert "all gaps are intentional quarantines" in src


def test_decide_suppression_thresholds():
    from services.ai_modules.regime_expectancy_calibrator import decide_suppression
    cells = {
        "vwap_fade|short|BULL>60": {"weighted_mean_r": -0.80, "eff_n": 40},
        "scalp|long|BULL>60": {"weighted_mean_r": -0.20, "eff_n": 40},
        "orb|long|BULL>60": {"weighted_mean_r": +0.30, "eff_n": 40},
        "thin|long|BULL>60": {"weighted_mean_r": -0.90, "eff_n": 3},
    }
    assert decide_suppression(cells, "vwap_fade", "short", "BULL>60")["action"] == "SKIP"
    assert decide_suppression(cells, "scalp", "long", "BULL>60")["action"] == "REDUCE"
    assert decide_suppression(cells, "orb", "long", "BULL>60")["action"] == "NONE"
    assert decide_suppression(cells, "thin", "long", "BULL>60")["action"] == "NONE"
    assert decide_suppression(cells, "vwap_fade", "short", None)["action"] == "NONE"
