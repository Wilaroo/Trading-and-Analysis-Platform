"""
test_stamp_strategy_metrics_v292.py — guards the v292 Part 1 DATA-HONESTY stamp.

_stamp_strategy_metrics fills strategy_win_rate / EV(R) / profit_factor from
_strategy_stats, mirroring the intraday grace logic and lazy-registering unseen
setups, so daily/positional-path alerts stop persisting a misleading 0%. It must
NEVER fabricate a real rate for a thin/unseen setup (uses the floor baseline) and
must canonicalize the base setup like the scanner does.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.enhanced_scanner import (  # noqa: E402
    EnhancedBackgroundScanner, StrategyStats, LiveAlert, AlertPriority,
)

stamp = EnhancedBackgroundScanner._stamp_strategy_metrics


def _self(stats):
    return SimpleNamespace(
        _strategy_stats=stats,
        _win_rate_grace_min_trades=20,
        _auto_execute_min_win_rate=0.55,
    )


def _alert(setup):
    return SimpleNamespace(setup_type=setup, strategy_win_rate=0.0,
                           strategy_profit_factor=0.0, strategy_ev_r=0.0)


class TestStampStrategyMetrics:
    def test_real_rate_when_enough_outcomes(self):
        st = StrategyStats(setup_type="vwap_fade", alerts_triggered=120,
                           win_rate=0.17, expected_value_r=-3.98, profit_factor=0.3)
        s = _self({"vwap_fade": st})
        a = _alert("vwap_fade_long")
        stamp(s, a)
        assert a.strategy_win_rate == 0.17          # real, honest — NOT grace
        assert a.strategy_ev_r == -3.98
        assert a.strategy_profit_factor == 0.3

    def test_grace_floor_when_thin(self):
        st = StrategyStats(setup_type="daily_squeeze", alerts_triggered=8,
                           win_rate=0.12, expected_value_r=-0.94)
        s = _self({"daily_squeeze": st})
        a = _alert("daily_squeeze")
        stamp(s, a)
        assert a.strategy_win_rate == 0.55          # floor baseline (8 < 20)
        assert a.strategy_ev_r == -0.94             # EV still stamped honestly

    def test_unregistered_is_lazy_registered_to_grace(self):
        stats = {}
        s = _self(stats)
        a = _alert("breakdown_confirmed")
        stamp(s, a)
        assert "breakdown_confirmed" in stats        # lazy-registered
        assert a.strategy_win_rate == 0.55           # grace, not a false 0.0
        assert stats["breakdown_confirmed"].alerts_triggered == 0

    def test_base_canonicalization(self):
        st = StrategyStats(setup_type="abc", alerts_triggered=50, win_rate=0.62)
        s = _self({"abc": st})
        a = _alert("abc_short")
        stamp(s, a)
        assert a.strategy_win_rate == 0.62

    def test_never_raises_on_garbage(self):
        s = _self({})
        a = SimpleNamespace(setup_type=None, strategy_win_rate=0.0,
                            strategy_profit_factor=0.0, strategy_ev_r=0.0)
        stamp(s, a)  # must not raise
        assert a.strategy_win_rate == 0.0            # empty base -> untouched

    def test_integration_real_livealert_persists(self):
        """End-to-end: a real LiveAlert gets honest fields that to_dict() persists."""
        st = StrategyStats(setup_type="accumulation_entry", alerts_triggered=39,
                           win_rate=0.13, expected_value_r=-0.44)
        s = _self({"accumulation_entry": st})
        a = LiveAlert(id="t1", symbol="NVDA", setup_type="accumulation_entry",
                      strategy_name="accumulation_entry", direction="long",
                      priority=AlertPriority.MEDIUM, current_price=100.0,
                      trigger_price=100.0, stop_loss=98.0, target=104.0,
                      risk_reward=2.0, trigger_probability=0.5, win_probability=0.5,
                      minutes_to_trigger=0, headline="x", reasoning=[],
                      time_window="INTRADAY", market_regime="neutral")
        assert a.strategy_win_rate == 0.0            # default before stamp
        stamp(s, a)
        d = a.to_dict()
        assert d["strategy_win_rate"] == 0.13        # honest, persisted
        assert d["strategy_ev_r"] == -0.44
