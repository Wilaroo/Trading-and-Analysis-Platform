"""v19.34.207 — SMB 5-variable scoring wired into the live scanner.

Validates the canonical path the scanner now uses
(scoring_engine.evaluate_smb_checklist -> convert_checklist_to_smb_score)
produces a real per-alert spread instead of the old flat smb_score_total=25.
"""
from services.scoring_engine import get_scoring_engine
from services.smb_unified_scoring import convert_checklist_to_smb_score


def _score(data, regime="bullish"):
    checklist = get_scoring_engine(None).evaluate_smb_checklist(data, {"regime": regime})
    return convert_checklist_to_smb_score(checklist)


_STRONG = {
    "current_price": 100.0,
    "gap_percent": 5.0,            # catalyst
    "rvol": 3.0,                   # catalyst + volume
    "trend": "BULLISH",
    "ema_9": 98.0, "sma_20": 95.0, "sma_50": 90.0,  # price>ema9>sma20 -> trend+MA
    "support_1": 97.0, "resistance_1": 110.0,        # S/R + R:R 4.3:1 -> exit
    "avg_volume": 1_000_000,
    "change_percent": 5.0,         # relative strength
    "vwap": 95.0, "prev_close": 99.0,                # mtf confluence
    "matched_strategies": [{"name": "gap_and_go"}],  # proven success
}

_WEAK = {
    "current_price": 100.0,
    "gap_percent": 0.0,
    "rvol": 1.0,
    "trend": "NEUTRAL",
    "support_1": 0.0, "resistance_1": 0.0,
    "avg_volume": 100_000,
    "change_percent": 0.0,
    "matched_strategies": [],
}


def test_strong_setup_scores_high():
    smb = _score(_STRONG)
    assert smb is not None
    assert smb.total_score >= 40
    assert smb.grade in ("A", "A+")
    assert smb.total_score != 25  # not the old flat default


def test_weak_setup_is_baseline():
    # Every check fails -> all five variables sit at the 5/10 default = 25/50.
    smb = _score(_WEAK, regime="neutral")
    assert smb is not None
    assert smb.total_score == 25


def test_real_spread_between_setups():
    strong = _score(_STRONG)
    weak = _score(_WEAK, regime="neutral")
    assert strong.total_score > weak.total_score + 10


def test_partial_setup_lands_in_between():
    # Catalyst + volume + clear levels, but no trend/MA/RS alignment.
    partial = {
        "current_price": 50.0,
        "gap_percent": 4.0,           # catalyst
        "rvol": 2.6,                  # catalyst + volume
        "trend": "NEUTRAL",
        "support_1": 49.0, "resistance_1": 56.0,   # S/R + R:R 7:1 -> exit
        "avg_volume": 800_000,
        "matched_strategies": [{"name": "range_break"}],
    }
    smb = _score(partial, regime="neutral")
    assert 25 < smb.total_score < 46
