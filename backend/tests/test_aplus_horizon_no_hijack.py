"""Regression guard for the v320p + v320u A+ horizon-hijack fixes.

LOCKS IN: SMB "A+" is a QUALITY grade, NOT a horizon. An A+ score must NOT
convert an intraday/scalp-natured setup into a multi-day overnight carry.

Background: two A+ paths used to force trade_style=multi_day —
  • enhanced_scanner.LiveAlert populate (v320p guard)
  • smb_integration.get_default_trade_style L1061 (v320u)  ← this test's focus
This test fails if either regresses for config-bearing intraday/scalp setups,
and documents the multi-timeframe (trend_continuation) resolution invariant.

Run: cd backend && .venv/bin/python -m pytest tests/test_aplus_horizon_no_hijack.py -q
"""
import pytest

from services.smb_integration import SMBVariableScore, get_default_trade_style, get_setup_config
from services.trade_style_classifier import resolve_trade_style

CARRY = {"multi_day", "swing", "position", "investment"}
INTRADAY = {"scalp", "intraday"}


def _aplus():
    s = SMBVariableScore(big_picture=9, intraday_fundamental=9, technical_level=9,
                         tape_reading=9, intuition=9)
    assert s.is_a_plus and s.total_score >= 40
    return s


def _mid():
    # >=35 but NOT a_plus
    s = SMBVariableScore(big_picture=8, intraday_fundamental=7, technical_level=7,
                         tape_reading=7, intuition=7)
    assert not s.is_a_plus and s.total_score >= 35
    return s


@pytest.mark.parametrize("setup", ["gap_fade", "squeeze", "second_chance"])
def test_aplus_does_not_hijack_intraday_setups_to_carry(setup):
    """v320u: A+ on an intraday/scalp-natured config setup keeps its natural
    (intraday-group) horizon — must NOT return a carry style."""
    cfg = get_setup_config(setup)
    assert cfg is not None, f"{setup} should have a registry config"
    natural = cfg.default_style.value
    assert natural in INTRADAY, f"{setup} natural style should be intraday-group"

    style = get_default_trade_style(setup, {"smb_score": _aplus()}).value
    assert style not in CARRY, (
        f"A+ HIJACK REGRESSION: {setup} (natural={natural}) was promoted to "
        f"carry style '{style}' — v320u/v320p broken."
    )
    assert style in INTRADAY


def test_aplus_still_promotes_genuinely_carry_setups():
    """A+ promotion to multi_day is still allowed for carry-natured defaults
    (defensive: the guard keys on default_style, not a blanket block)."""
    # No registry config setups are carry-natured, so simulate via a stub.
    class _CarryCfg:
        class _S:
            value = "multi_day"
        default_style = _S()
    import services.smb_integration as smb
    orig = smb.get_setup_config
    try:
        smb.get_setup_config = lambda name: _CarryCfg()
        assert smb.get_default_trade_style("x", {"smb_score": _aplus()}).value == "multi_day"
    finally:
        smb.get_setup_config = orig


def test_mid_grade_scalp_upgrades_to_intraday_not_carry():
    """The >=35 (non-A+) branch may upgrade scalp->intraday, never to carry."""
    style = get_default_trade_style("gap_fade", {"smb_score": _mid()}).value
    assert style in INTRADAY


def test_trend_continuation_timeframe_resolution_invariant():
    """Multi-timeframe setup (no registry config): style is timeframe-driven;
    only the no-context case falls to the static multi_day fallback."""
    assert get_setup_config("trend_continuation") is None
    base = {"setup_type": "trend_continuation_short"}
    # explicit intraday timeframe -> intraday (the TSLA/META/NOK case)
    assert resolve_trade_style({**base, "timeframe": "intraday"}) == "intraday"
    # swing timeframe -> swing (the GLD/MSTR case)
    assert resolve_trade_style({**base, "timeframe": "swing"}) == "swing"
    # no context at all -> documented static fallback
    assert resolve_trade_style(base) == "multi_day"
