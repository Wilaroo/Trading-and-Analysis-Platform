"""v19.34.165 — 5 momentum playbook setups must be enabled + configured.

v19.34.164 (trade_drops persistence) surfaced that the scanner emits 446
alerts/hour for these 5 setup types, but the bot was silently killing
them at the `setup_disabled` gate because they were missing from
`_enabled_setups` and `STRATEGY_CONFIG`. This suite locks in the fix:

  - Every new setup is listed in TradingBotService._enabled_setups (so
    `_get_trade_alerts` lets them through).
  - Every new setup has a STRATEGY_CONFIG entry with the required schema
    keys (timeframe / trail_pct / scale_out_pcts / close_at_eod) so the
    evaluator doesn't silently fall through to DEFAULT_STRATEGY_CONFIG.
  - Each parameter is within sane ranges for its trading style.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# Canonical list — keep in sync with both
# `trading_bot_service._enabled_setups` and `STRATEGY_CONFIG` keys.
V165_SETUPS = [
    "rs_leader_break",
    "power_trend_stack",
    "pocket_pivot",
    "stage_2_breakout",
    "three_week_tight",
]


@pytest.fixture(scope="module")
def strategy_config():
    from services.trading_bot_service import STRATEGY_CONFIG
    return STRATEGY_CONFIG


@pytest.fixture(scope="module")
def trade_timeframe():
    from services.trading_bot_service import TradeTimeframe
    return TradeTimeframe


@pytest.fixture(scope="module")
def bot_instance():
    """Construct a bare TradingBotService to read the hardcoded
    `_enabled_setups` list assembled in __init__."""
    from services.trading_bot_service import TradingBotService
    # __new__ avoids the expensive __init__ side effects (IB/Alpaca/etc.)
    # while still letting us call the unbound __init__ to populate the
    # list. But __init__ touches too many externals. Instead we just
    # reflect the list from the source by instantiating via __new__ and
    # manually replaying the list construction is too fragile — so we
    # call the real __init__ but expect it to fail late; we only need
    # _enabled_setups which is set very early.
    bot = TradingBotService.__new__(TradingBotService)
    # Replay the slice of __init__ that builds _enabled_setups, by
    # extracting the list literal from the source. Simplest: parse the
    # source file once.
    import re
    import ast
    src = (BACKEND_ROOT / "services" / "trading_bot_service.py").read_text()
    # Find the assignment `self._enabled_setups = [ ... ]`
    m = re.search(
        r"self\._enabled_setups\s*=\s*(\[[^\]]*\])", src, re.DOTALL,
    )
    assert m, "Couldn't locate self._enabled_setups assignment in source"
    list_src = m.group(1)
    bot._enabled_setups = ast.literal_eval(list_src)
    return bot


# ── Enabled-setups membership ────────────────────────────────────────
@pytest.mark.parametrize("setup", V165_SETUPS)
def test_setup_present_in_enabled_setups(setup, bot_instance):
    assert setup in bot_instance._enabled_setups, (
        f"`{setup}` missing from TradingBotService._enabled_setups "
        f"(would be silently dropped at setup_disabled gate). "
        f"Add it to the list in __init__ around lines 970-985."
    )


# ── STRATEGY_CONFIG schema ───────────────────────────────────────────
@pytest.mark.parametrize("setup", V165_SETUPS)
def test_setup_has_strategy_config(setup, strategy_config):
    assert setup in strategy_config, (
        f"`{setup}` missing from STRATEGY_CONFIG — would fall through "
        f"to DEFAULT_STRATEGY_CONFIG (intraday/2%/close_at_eod=True), "
        f"which is wrong for these multi-day momentum plays."
    )
    cfg = strategy_config[setup]
    for required_key in ("timeframe", "trail_pct", "scale_out_pcts",
                         "close_at_eod"):
        assert required_key in cfg, (
            f"`{setup}` STRATEGY_CONFIG missing key `{required_key}`"
        )


# ── Parameter sanity ranges ──────────────────────────────────────────
@pytest.mark.parametrize("setup", V165_SETUPS)
def test_setup_trail_pct_in_range(setup, strategy_config):
    trail = strategy_config[setup]["trail_pct"]
    assert 0.005 <= trail <= 0.10, (
        f"`{setup}` trail_pct={trail} outside sane range [0.005, 0.10]"
    )


@pytest.mark.parametrize("setup", V165_SETUPS)
def test_setup_scale_out_sums_to_1(setup, strategy_config):
    pcts = strategy_config[setup]["scale_out_pcts"]
    s = sum(pcts)
    assert abs(s - 1.0) < 1e-6, (
        f"`{setup}` scale_out_pcts={pcts} sums to {s}, must sum to 1.0"
    )


@pytest.mark.parametrize("setup", V165_SETUPS)
def test_multiday_setups_dont_close_at_eod(setup, strategy_config):
    """All 5 v165 setups are SWING or POSITION timeframe — they MUST
    NOT auto-close at EOD or we'd be cutting winners on day 1."""
    cfg = strategy_config[setup]
    assert cfg["close_at_eod"] is False, (
        f"`{setup}` close_at_eod must be False (multi-day playbook). "
        f"Setting it True would auto-flatten the position at 3:55pm ET "
        f"on the entry day, destroying the entire edge."
    )


@pytest.mark.parametrize("setup", V165_SETUPS)
def test_timeframe_is_swing_or_position(setup, strategy_config, trade_timeframe):
    """v165 setups are multi-day momentum plays — must be SWING or POSITION."""
    tf = strategy_config[setup]["timeframe"]
    assert tf in (trade_timeframe.SWING, trade_timeframe.POSITION), (
        f"`{setup}` timeframe={tf} — must be SWING or POSITION "
        f"(these are multi-day playbook trades, not intraday scalps)."
    )
