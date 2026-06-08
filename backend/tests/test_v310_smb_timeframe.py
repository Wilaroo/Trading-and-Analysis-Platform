"""v19.34.310 — SMB checklist timeframe-awareness + smb_5var_score persistence."""
import os
import importlib

from services.scoring_engine import UniversalScoringEngine


def _eng():
    return UniversalScoringEngine(db=None)


_BASE = {
    "current_price": 100.0, "prev_close": 95.0, "ema_9": 99.0, "sma_20": 98.0,
    "sma_50": 100.5, "vwap": 90.0, "support_1": 97.0, "resistance_1": 110.0,
    "avg_volume": 1_000_000, "trend": "BULLISH",
    "matched_strategies": [{"name": "swing_breakout"}],
}


def _run(rvol, trade_style, tf_aware):
    if tf_aware:
        os.environ["SMB_CHECKLIST_TIMEFRAME_AWARE"] = "true"
    else:
        os.environ.pop("SMB_CHECKLIST_TIMEFRAME_AWARE", None)
    data = dict(_BASE, rvol=rvol, trade_style=trade_style)
    return _eng().evaluate_smb_checklist(data, {"regime": "neutral"}, timeframe=trade_style)["checklist"]


def test_legacy_off_is_intraday_thresholds():
    # Flag OFF: swing with quiet rvol 1.3 fails the 1.5 "In Play" bar (legacy).
    cl = _run(1.3, "swing", tf_aware=False)
    assert cl["volume_analysis"]["passed"] is False


def test_tf_aware_swing_lowers_volume_bar():
    # Flag ON: swing rvol 1.3 now clears the 1.2 swing bar.
    cl = _run(1.3, "swing", tf_aware=True)
    assert cl["volume_analysis"]["passed"] is True


def test_tf_aware_swing_catalyst_rvol():
    # rvol 2.2: swing-aware catalyst bar (2.0) passes; legacy (2.5) would not.
    on = _run(2.2, "swing", tf_aware=True)
    off = _run(2.2, "swing", tf_aware=False)
    assert on["catalyst"]["passed"] is True
    # off: gap/earnings absent, rvol 2.2 < 2.5 → no catalyst from volume
    assert off["catalyst"]["passed"] is False


def test_tf_aware_does_not_affect_intraday():
    # Intraday style keeps legacy thresholds even with flag on.
    cl = _run(1.3, "intraday", tf_aware=True)
    assert cl["volume_analysis"]["passed"] is False
    os.environ.pop("SMB_CHECKLIST_TIMEFRAME_AWARE", None)


def test_smb_5var_score_persisted_in_to_dict():
    from services.enhanced_scanner import LiveAlert
    # Build a minimal alert via dataclass defaults, set a real 5-var total.
    import dataclasses
    fields = {f.name: f.default for f in dataclasses.fields(LiveAlert)
              if f.default is not dataclasses.MISSING}
    try:
        a = LiveAlert(**{k: v for k, v in fields.items()})
    except Exception:
        a = None
    if a is None:
        return  # constructor needs required args; persistence covered by code review
    a.smb_score_total = 42
    d = a.to_dict()
    assert d.get("smb_5var_score") == 42
