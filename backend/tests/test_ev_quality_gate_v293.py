"""
test_ev_quality_gate_v293.py — guards the v293 Part 2 EV-AWARE auto-exec gate
(operator-approved: EV_R > +0.10R replaces the win-rate floor; win-rate dropped).

Locks the gate decision (_passes_ev_quality_gate) and its honest reason decoder
(_auto_exec_fail_reasons_ev) against the four populations: unregistered, cold-start
grace, proven-positive (passes), proven-negative (blocked).
"""
import os
import sys
from dataclasses import dataclass
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.enhanced_scanner import EnhancedBackgroundScanner  # noqa: E402

gate = EnhancedBackgroundScanner._passes_ev_quality_gate
reasons = EnhancedBackgroundScanner._auto_exec_fail_reasons_ev


@dataclass
class _Stats:
    alerts_triggered: int = 0
    expected_value_r: float = 0.0


def _self(stats):
    return SimpleNamespace(
        _strategy_stats=stats,
        _win_rate_grace_min_trades=20,
        _auto_execute_min_ev_r=0.10,
    )


def _alert(setup):
    return SimpleNamespace(setup_type=setup)


class TestEvQualityGate:
    def test_unregistered_blocked(self):
        assert gate(_self({}), _alert("ghost")) is False

    def test_cold_start_grace_passes(self):
        s = _self({"orb": _Stats(alerts_triggered=5, expected_value_r=-9.0)})
        assert gate(s, _alert("orb")) is True            # <20 outcomes -> grace, EV ignored

    def test_proven_positive_passes(self):
        # vwap_continuation: 49 outcomes, EV +0.17 > +0.10
        s = _self({"vwap_continuation": _Stats(alerts_triggered=49, expected_value_r=0.17)})
        assert gate(s, _alert("vwap_continuation")) is True

    def test_proven_negative_blocked(self):
        # vwap_fade: 116 outcomes, EV -3.98
        s = _self({"vwap_fade": _Stats(alerts_triggered=116, expected_value_r=-3.98)})
        assert gate(s, _alert("vwap_fade_long")) is False

    def test_proven_just_below_threshold_blocked(self):
        # gap_fade: 34 outcomes, EV +0.088 < +0.10 -> blocked (operator accepted)
        s = _self({"gap_fade": _Stats(alerts_triggered=34, expected_value_r=0.088)})
        assert gate(s, _alert("gap_fade")) is False

    def test_threshold_is_strict_greater_than(self):
        s = _self({"x": _Stats(alerts_triggered=30, expected_value_r=0.10)})
        assert gate(s, _alert("x")) is False             # 0.10 is NOT > 0.10

    def test_base_canonicalization(self):
        s = _self({"vwap_fade": _Stats(alerts_triggered=116, expected_value_r=-3.98)})
        assert gate(s, _alert("vwap_fade_short")) is False


class TestEvFailReasons:
    def test_all_pass_no_reasons(self):
        assert reasons("HIGH", True, 0.5, 0.10, 30, 20) == []

    def test_priority_low(self):
        assert "priority=LOW<high" in reasons("LOW", True, 0.5, 0.10, 30, 20)

    def test_tape_unconfirmed(self):
        assert "tape_unconfirmed" in reasons("HIGH", False, 0.5, 0.10, 30, 20)

    def test_proven_negative_ev_reason(self):
        out = reasons("HIGH", True, -3.98, 0.10, 116, 20)
        assert out == ["EV -3.98R<=+0.10R"]

    def test_cold_start_no_ev_reason(self):
        assert reasons("HIGH", True, -9.0, 0.10, 5, 20) == []   # <grace -> EV not judged

    def test_unregistered_reason(self):
        out = reasons("HIGH", True, 0.0, 0.10, 0, 20, registered=False)
        assert out == ["no_strategy_stats"]
