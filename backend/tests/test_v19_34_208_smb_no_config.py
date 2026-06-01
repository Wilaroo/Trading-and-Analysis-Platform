"""v19.34.208 — populate_smb_fields applies the SMB score even when the setup
has no registry config (directional variants like vwap_fade_long /
vwap_continuation), which previously left smb_score_total flat at 25.
"""
from services.enhanced_scanner import LiveAlert, AlertPriority
from services.smb_integration import get_setup_config, SMBVariableScore


def _make_alert(setup_type):
    return LiveAlert(
        id="t1", symbol="VIAV", setup_type=setup_type, strategy_name="x",
        direction="long", priority=AlertPriority.MEDIUM,
        current_price=10.0, trigger_price=10.0, stop_loss=9.5, target=11.0,
        risk_reward=2.0, trigger_probability=0.5, win_probability=0.5,
        minutes_to_trigger=0, headline="h", reasoning=[], time_window="rth",
        market_regime="range_bound",
    )


def _smb38():
    # total = 8+7+8+7+8 = 38
    return SMBVariableScore(big_picture=8, intraday_fundamental=7,
                            technical_level=8, tape_reading=7, intuition=8)


def test_vwap_fade_has_no_config():
    # Guards the premise: these directional variants resolve to no config.
    assert get_setup_config("vwap_fade_long") is None
    assert get_setup_config("vwap_continuation") is None
    assert get_setup_config("gap_fade") is not None


def test_smb_applies_without_config():
    a = _make_alert("vwap_fade_long")
    assert a.smb_score_total == 25  # dataclass default
    a.populate_smb_fields({"smb_score": _smb38()})
    assert a.smb_score_total == 38
    assert a.smb_big_picture == 8
    assert a.smb_tape == 7


def test_smb_applies_with_config():
    a = _make_alert("gap_fade")
    a.populate_smb_fields({"smb_score": _smb38()})
    assert a.smb_score_total == 38


def test_no_context_keeps_default():
    a = _make_alert("vwap_fade_short")
    a.populate_smb_fields(None)
    assert a.smb_score_total == 25


def test_earnings_applies_without_config():
    a = _make_alert("vwap_continuation")
    a.populate_smb_fields({"smb_score": _smb38(), "earnings_score": 7})
    assert a.smb_score_total == 38
    assert a.earnings_score == 7
