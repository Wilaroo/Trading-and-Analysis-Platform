"""
test_gate_funnel_v286.py — guards the symbol-trace alert→trade gate funnel.

The funnel joins a symbol's `trade_drops` rows so the trace answers WHICH gate
ate the alerts and BY HOW MUCH. Pure-function tests (no Mongo / no scanner).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.scanner import _drop_margin, _summarize_symbol_drops  # noqa: E402


class TestDropMargin:
    def test_tqs_too_low_margin(self):
        m = _drop_margin("tqs_too_low", {"tqs": 52, "min_tqs": 60})
        assert m == "TQS 52 < min 60 (missed by 8)"

    def test_rr_below_min_margin(self):
        m = _drop_margin("rr_below_min", {"rr_ratio": 1.19, "min_required": 1.5})
        assert m == "R:R 1.19 < min 1.50"

    def test_smart_filter_fractional_winrate(self):
        assert _drop_margin("smart_filter_skip", {"win_rate": 0.17}) == "win-rate 17%"

    def test_smart_filter_percent_winrate(self):
        assert _drop_margin("smart_filter_skip", {"win_rate": 17}) == "win-rate 17%"

    def test_open_cap_margin(self):
        assert _drop_margin("max_open_positions", {"current": 5, "max": 5}) == "5/5 cap"

    def test_cooldown_margin(self):
        assert _drop_margin("post_stop_cooldown", {"cooldown_seconds_left": 240}) == "240s cooldown left"

    def test_unknown_gate_returns_none(self):
        assert _drop_margin("account_guard", {"foo": 1}) is None

    def test_missing_context_returns_none(self):
        assert _drop_margin("tqs_too_low", {}) is None
        assert _drop_margin("tqs_too_low", None) is None

    def test_bad_values_dont_raise(self):
        assert _drop_margin("tqs_too_low", {"tqs": "x", "min_tqs": None}) is None


class TestSummarizeDrops:
    def test_empty(self):
        s = _summarize_symbol_drops([])
        assert s == {"total": 0, "first_killing_gate": None, "by_gate": {}}

    def test_aggregates_and_ranks(self):
        drops = [
            {"gate": "tqs_too_low", "setup_type": "squeeze", "reason": "low tqs",
             "context": {"tqs": 52, "min_tqs": 60}, "ts": "2026-06-05T17:00:00"},
            {"gate": "tqs_too_low", "setup_type": "vwap_fade", "reason": "low tqs 2",
             "context": {"tqs": 48, "min_tqs": 60}, "ts": "2026-06-05T18:00:00"},
            {"gate": "rr_below_min", "setup_type": "squeeze", "reason": "rr low",
             "context": {"rr_ratio": 1.1, "min_required": 1.5}, "ts": "2026-06-05T17:30:00"},
        ]
        s = _summarize_symbol_drops(drops)
        assert s["total"] == 3
        assert s["first_killing_gate"] == "tqs_too_low"  # 2 vs 1
        tqs = s["by_gate"]["tqs_too_low"]
        assert tqs["count"] == 2
        # margin taken from the LATEST (18:00) drop
        assert tqs["margin"] == "TQS 48 < min 60 (missed by 12)"
        assert tqs["last_reason"] == "low tqs 2"
        assert tqs["setups"] == ["squeeze", "vwap_fade"]

    def test_unknown_gate_label(self):
        s = _summarize_symbol_drops([{"gate": None, "ts": "2026-06-05T01:00:00"}])
        assert "unknown" in s["by_gate"]
        assert s["first_killing_gate"] == "unknown"
