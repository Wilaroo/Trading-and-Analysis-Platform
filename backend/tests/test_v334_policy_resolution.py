"""v334 — get_policy_for_trade resolves generic/unknown styles via the
canonical trade_style_classifier (setup-derived horizon wins).

Probe evidence (diag_eod_pusher, 2026-06-12): 63 `trade_2_hold` positions
flattened by eod_auto_close_v162 at 15:45 in 14 days — the generic SMB
fallback style short-circuited to DEFAULT_POLICY (intraday,
close_at_eod=True), flattening real holds like daily_breakout (multi_day),
stage_2_breakout (position), rs_leader_break (investment),
trend_continuation (multi_day).
"""
from pathlib import Path
from types import SimpleNamespace
import sys


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "order_policy_registry.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

from services.order_policy_registry import (  # noqa: E402
    get_policy_for_trade, should_close_at_eod)


def _t(style, setup=None):
    return SimpleNamespace(trade_style=style, setup_type=setup,
                           setup_variant=None, timeframe=None)


# ── generic trade_2_hold resolves by setup horizon ───────────────────────

def test_trade_2_hold_daily_breakout_holds():
    assert should_close_at_eod(_t("trade_2_hold", "daily_breakout")) is False
    assert get_policy_for_trade(_t("trade_2_hold", "daily_breakout")).style == "multi_day"


def test_trade_2_hold_stage_2_breakout_holds():
    assert should_close_at_eod(_t("trade_2_hold", "stage_2_breakout")) is False
    assert get_policy_for_trade(_t("trade_2_hold", "stage_2_breakout")).style == "position"


def test_trade_2_hold_rs_leader_break_holds():
    assert should_close_at_eod(_t("trade_2_hold", "rs_leader_break")) is False
    assert get_policy_for_trade(_t("trade_2_hold", "rs_leader_break")).style == "investment"


def test_trade_2_hold_trend_continuation_short_holds():
    assert should_close_at_eod(_t("trade_2_hold", "trend_continuation_short")) is False


# ── intraday-horizon setups still close at EOD ───────────────────────────

def test_trade_2_hold_squeeze_still_closes():
    assert should_close_at_eod(_t("trade_2_hold", "squeeze")) is True


def test_trade_2_hold_orb_still_closes():
    assert should_close_at_eod(_t("trade_2_hold", "orb")) is True


def test_trade_2_hold_no_setup_defaults_intraday_close():
    assert should_close_at_eod(_t("trade_2_hold", None)) is True


# ── canonical styles unaffected (regression) ─────────────────────────────

def test_explicit_styles_unchanged():
    assert should_close_at_eod(_t("scalp")) is True
    assert should_close_at_eod(_t("intraday")) is True
    assert should_close_at_eod(_t("swing")) is False
    assert should_close_at_eod(_t("multi_day")) is False
    assert should_close_at_eod(_t("position")) is False
    assert should_close_at_eod(_t("investment")) is False


def test_explicit_intraday_beats_hold_setup():
    # explicit canonical style short-circuits — setup must NOT override it
    assert should_close_at_eod(_t("intraday", "daily_breakout")) is True


def test_none_trade_defaults():
    assert should_close_at_eod(None) is True
