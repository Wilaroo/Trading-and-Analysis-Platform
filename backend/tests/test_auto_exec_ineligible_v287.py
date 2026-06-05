"""
test_auto_exec_ineligible_v287.py — guards the auto-exec eligibility intake trace.

Alerts that surface but fail the scanner's auto-execute gate (priority<high /
tape unconfirmed / win-rate<floor) were silently skipped (0 trade_drops), so
symbol-trace showed "NO gate-drop logged". This tests the pure reason-decoder
that now feeds the recorded `auto_exec_ineligible` drop.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.enhanced_scanner import EnhancedBackgroundScanner  # noqa: E402

reasons = EnhancedBackgroundScanner._auto_exec_fail_reasons


class TestFailReasons:
    def test_all_pass_returns_empty(self):
        assert reasons("high", True, 0.60, 0.55) == []
        assert reasons("critical", True, 0.55, 0.55) == []

    def test_priority_too_low(self):
        r = reasons("medium", True, 0.60, 0.55)
        assert r == ["priority=medium<high"]

    def test_tape_unconfirmed(self):
        r = reasons("high", False, 0.60, 0.55)
        assert r == ["tape_unconfirmed"]

    def test_win_rate_below_floor(self):
        r = reasons("high", True, 0.50, 0.55)
        assert r == ["win-rate 50%<55%"]

    def test_multiple_failures_ordered(self):
        r = reasons("medium", False, 0.40, 0.55)
        assert r == ["priority=medium<high", "tape_unconfirmed", "win-rate 40%<55%"]

    def test_critical_priority_passes_priority_check(self):
        assert "priority" not in " ".join(reasons("critical", True, 0.60, 0.55))

    def test_bad_winrate_values_dont_raise(self):
        # None/garbage win_rate must not throw; treated as 0 → below any floor
        assert "win-rate" in " ".join(reasons("high", True, None, 0.55))
        assert reasons("high", True, "x", 0.55) == ["win-rate 0%<55%"]

    def test_priority_case_insensitive(self):
        assert reasons("HIGH", True, 0.60, 0.55) == []
