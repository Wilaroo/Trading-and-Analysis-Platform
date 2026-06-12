"""v332 — regime demotion policy + EOD naked-guard style fix.

1. New services/regime_demotion_service.py: confirmed adverse regime flips
   (persisting REGIME_DEMOTION_CONFIRM_MIN, default 20min) demote conflicting
   intraday/swing positions — stop→BE if ≥0.25R, else software-stop ratchet
   halfway to entry. NO IB order surgery (orphan-safe by construction).
   Also un-freezes bot._current_regime (sizing multiplier was stuck at
   RISK_ON since _update_market_regime was never called).
2. position_manager._eod_naked_flatten_guard now resolves close_at_eod from
   the trade-style POLICY (should_close_at_eod) like the main EOD pass,
   instead of the broken default-True per-trade attribute that got swing
   holds force-flattened at 15:56.
"""
import asyncio
import py_compile
from pathlib import Path
from types import SimpleNamespace


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "regime_demotion_service.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
PM = (ROOT / "backend" / "services" / "position_manager.py").read_text()
TBS = (ROOT / "backend" / "services" / "trading_bot_service.py").read_text()


def _svc():
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from services.regime_demotion_service import RegimeDemotionService
    return RegimeDemotionService()


def _trade(direction, style="intraday", entry=100.0, stop=98.0, px=100.0,
           mode="original"):
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from services.trading_bot_service import TradeDirection
    d = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
    return SimpleNamespace(
        symbol="TEST", direction=d, trade_style=style,
        fill_price=entry, entry_price=entry, stop_price=stop,
        current_price=px,
        trailing_stop_config={"mode": mode, "current_stop": stop},
    )


class _StopMgrStub:
    def __init__(self):
        self.be_calls = []
        self.adjustments = []

    def _move_stop_to_breakeven(self, t):
        self.be_calls.append(t.symbol)
        t.trailing_stop_config["mode"] = "breakeven"

    def _record_stop_adjustment(self, t, old, new, reason):
        self.adjustments.append((old, new, reason))


def _bot(trades, regime="RISK_OFF"):
    return SimpleNamespace(
        _open_trades={str(i): t for i, t in enumerate(trades)},
        _stop_manager=_StopMgrStub(),
        _db=None,
        _current_regime="RISK_ON",
        _regime_position_multipliers={"RISK_ON": 1.0, "RISK_OFF": 0.5},
        _market_regime_engine=None,
    )


# ── unit: _demote_one outcomes ───────────────────────────────────────────

def test_profitable_long_goes_breakeven():
    svc = _svc()
    t = _trade("long", entry=100.0, stop=98.0, px=101.0)   # +0.5R
    bot = _bot([t])
    out = svc._demote_one(bot, t, demote_long=True, demote_short=False, to="RISK_OFF")
    assert out == "be"
    assert bot._stop_manager.be_calls == ["TEST"]
    assert t.trailing_stop_config["regime_demoted"]["action"] == "be"


def test_losing_long_gets_tightened_halfway():
    svc = _svc()
    t = _trade("long", entry=100.0, stop=98.0, px=99.8)    # losing
    bot = _bot([t])
    out = svc._demote_one(bot, t, demote_long=True, demote_short=False, to="RISK_OFF")
    assert out == "tightened"
    assert t.trailing_stop_config["current_stop"] == 99.0   # (100+98)/2
    assert bot._stop_manager.adjustments[0][2] == "regime_demotion_risk_off"


def test_no_instant_trigger_guard():
    svc = _svc()
    t = _trade("long", entry=100.0, stop=98.0, px=98.9)    # px below halfway
    bot = _bot([t])
    out = svc._demote_one(bot, t, demote_long=True, demote_short=False, to="RISK_OFF")
    assert out == "too_close"
    assert t.trailing_stop_config["current_stop"] == 98.0   # unchanged


def test_scalp_and_long_horizon_exempt():
    svc = _svc()
    for style in ("scalp", "multi_day", "position", "investment"):
        t = _trade("long", style=style, px=99.0)
        out = svc._demote_one(_bot([t]), t, True, False, "RISK_OFF")
        assert out == "style_exempt", style


def test_short_not_demoted_on_risk_off():
    svc = _svc()
    t = _trade("short", entry=100.0, stop=102.0, px=99.0)
    out = svc._demote_one(_bot([t]), t, demote_long=True, demote_short=False, to="RISK_OFF")
    assert out == "direction_ok"


def test_already_protective_skipped():
    svc = _svc()
    t = _trade("long", px=101.0, mode="trailing")
    out = svc._demote_one(_bot([t]), t, True, False, "RISK_OFF")
    assert out == "already_protective"


def test_never_fires_twice():
    svc = _svc()
    t = _trade("long", entry=100.0, stop=98.0, px=101.0)
    bot = _bot([t])
    assert svc._demote_one(bot, t, True, False, "RISK_OFF") == "be"
    assert svc._demote_one(bot, t, True, False, "RISK_OFF") == "already_demoted"


# ── integration: confirmation window via tick() ──────────────────────────

def test_whipsaw_revert_cancels_pending():
    svc = _svc()
    svc._last_regime = "RISK_ON"
    svc._pending = {"from": "RISK_ON", "to": "RISK_OFF", "at_ts": 0}

    class _Engine:
        async def get_current_regime(self):
            return {"state": "RISK_ON"}   # reverted

    bot = _bot([])
    bot._market_regime_engine = _Engine()
    svc._last_tick = 0
    asyncio.run(svc.tick(bot))
    assert svc._pending is None           # cancelled, no demotion


def test_sizing_regime_kept_live():
    svc = _svc()

    class _Engine:
        async def get_current_regime(self):
            return {"state": "RISK_OFF"}

    bot = _bot([])
    bot._market_regime_engine = _Engine()
    svc._last_tick = 0
    asyncio.run(svc.tick(bot))
    assert bot._current_regime == "RISK_OFF"   # was frozen at RISK_ON


# ── source assertions ────────────────────────────────────────────────────

def test_naked_guard_uses_policy_resolution():
    i = PM.index("def _eod_naked_flatten_guard")
    block = PM[i:i + 9000]
    assert "should_close_at_eod" in block, \
        "naked guard must resolve close_at_eod from policy (v19.34.245 parity)"


def test_manage_loop_hooks_demotion_tick():
    assert "get_regime_demotion_service" in TBS
    assert "regime demotion tick" in TBS


def test_files_compile():
    for rel in ("regime_demotion_service.py", "position_manager.py",
                "trading_bot_service.py"):
        py_compile.compile(str(ROOT / "backend" / "services" / rel), doraise=True)
