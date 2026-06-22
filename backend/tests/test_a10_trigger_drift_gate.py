"""
test_a10_trigger_drift_gate.py — regression guard for the A10 trigger
re-validation (drift) gate inserted into
EnhancedBackgroundScanner._auto_execute_alert.

Drives the REAL method with a bare scanner instance (constructed via __new__
to skip heavy __init__ deps), a stubbed live-quote source, and a fake trading
bot that records whether the trade reached submit_trade_from_scanner.

Run on DGX:
    source .venv/bin/activate
    .venv/bin/python -m pytest backend/tests/test_a10_trigger_drift_gate.py -q
"""
import os
import asyncio
from types import SimpleNamespace

import pytest

from services.enhanced_scanner import EnhancedBackgroundScanner


class _FakeBot:
    def __init__(self):
        self.submitted = []

    async def submit_trade_from_scanner(self, req):
        self.submitted.append(req)


def _make_scanner(live_price):
    s = EnhancedBackgroundScanner.__new__(EnhancedBackgroundScanner)
    s._trading_bot = _FakeBot()
    s._auto_execute_enabled = True
    s._scan_count = 999          # past any A8 warm-up
    s._strategy_stats = {}

    async def _fake_quote(symbol):
        return {"price": live_price} if live_price else None

    s._get_quote_with_ib_priority = _fake_quote
    return s


def _make_alert(trigger):
    return SimpleNamespace(
        auto_execute_eligible=True,
        symbol="TEST",
        setup_type="stage_2_breakout",
        direction="long",
        trigger_price=trigger,
        current_price=trigger,
        stop_loss=(trigger * 0.97 if trigger else 0.0),
        target=(trigger * 1.06 if trigger else 0.0),
        id="alert-test-1",
        headline="TEST stage_2_breakout",
        priority=None,
        tqs_grade="B", tqs_score=60.0, tape_score=1.0, tape_confirmation=True,
        risk_reward=2.0, atr=1.0, atr_percent=2.0, trade_style="multi_day",
        smb_grade="B",
    )


def _run(policy, trigger, live, max_drift=None):
    os.environ["AUTO_EXEC_REQUIRE_FEED"] = "0"   # bypass A8 feed guard import
    os.environ["AUTO_EXEC_WARMUP_SCANS"] = "0"   # bypass A8 warm-up hold
    os.environ["AUTO_EXEC_TRIGGER_DRIFT_POLICY"] = policy
    if max_drift is not None:
        os.environ["AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT"] = str(max_drift)
    else:
        os.environ.pop("AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT", None)
    scanner = _make_scanner(live)
    asyncio.run(scanner._auto_execute_alert(_make_alert(trigger)))
    return scanner._trading_bot.submitted


def test_block_extended_8pct_is_skipped():
    assert _run("block", 50.0, 54.0) == []          # 8% drift > 2% → blocked


def test_block_near_trigger_1pct_executes():
    out = _run("block", 50.0, 50.5)                  # 1% drift < 2% → proceeds
    assert len(out) == 1 and out[0]["symbol"] == "TEST"


def test_observe_logs_but_executes():
    assert len(_run("observe", 50.0, 54.0)) == 1     # observe never blocks


def test_off_disables_gate():
    assert len(_run("off", 50.0, 54.0)) == 1         # off never blocks


def test_no_trigger_fails_open():
    assert len(_run("block", 0.0, 54.0)) == 1        # no trigger → fail-open


def test_no_live_quote_fails_open():
    assert len(_run("block", 50.0, 0.0)) == 1        # no live quote → fail-open


def test_custom_threshold_5pct_blocks_8pct():
    assert _run("block", 50.0, 54.0, max_drift=5.0) == []   # 8% > custom 5%


def test_custom_threshold_10pct_allows_8pct():
    assert len(_run("block", 50.0, 54.0, max_drift=10.0)) == 1  # 8% < 10%
