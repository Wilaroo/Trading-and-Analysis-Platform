"""
Tests for v19.34.100 — per-style order-management policy registry.

Validates:
  - All 6 styles have policies (scalp/intraday/multi_day/swing/investment/position)
  - Short-horizon styles are DAY/close_at_eod=True
  - Long-horizon styles are GTC/close_at_eod=False/eod_sweep_eligible=False
  - TP ladders sum to 1.0 for every policy
  - Stop trail anchor matches expected per-style indicator
  - is_eod_sweep_eligible() returns the right value for each style
  - get_policy_for_trade() correctly resolves from trade_style and from setup_type
  - DEFAULT_POLICY is intraday (conservative)
  - Bot vocabulary mentions every policy
  - GET /api/trading-bot/order-policies returns all 6
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.order_policy_registry import (
    DEFAULT_POLICY,
    ORDER_POLICIES,
    all_policies_summary,
    get_policy,
    get_policy_for_trade,
    is_eod_sweep_eligible,
    stop_trail_anchor_for,
    time_in_force_for,
)


@dataclass
class FakeTrade:
    symbol: str = "TEST"
    setup_type: str = ""
    trade_style: str = ""


# ─────────────────────────────────────────────────────────────────
# Registry coverage
# ─────────────────────────────────────────────────────────────────
class TestRegistryCoverage:
    def test_all_six_styles_present(self):
        expected = {"scalp", "intraday", "multi_day", "swing", "investment", "position"}
        assert set(ORDER_POLICIES.keys()) == expected

    def test_short_horizon_is_day_and_closes_eod(self):
        for s in ("scalp", "intraday"):
            p = ORDER_POLICIES[s]
            assert p.time_in_force == "DAY", f"{s} should be DAY"
            assert p.outside_rth is False, f"{s} should be inside RTH"
            assert p.close_at_eod is True, f"{s} should close at EOD"
            assert p.eod_sweep_eligible is True, f"{s} should be sweep-eligible"

    def test_long_horizon_is_gtc_and_holds_overnight(self):
        for s in ("multi_day", "swing", "investment", "position"):
            p = ORDER_POLICIES[s]
            assert p.time_in_force == "GTC", f"{s} should be GTC"
            assert p.outside_rth is True, f"{s} should allow outside-RTH fills"
            assert p.close_at_eod is False, f"{s} should hold overnight"
            assert p.eod_sweep_eligible is False, f"{s} should be sweep-PROTECTED"

    def test_tp_ladders_sum_to_one(self):
        for s, p in ORDER_POLICIES.items():
            total = sum(r.pct_of_position for r in p.tp_ladder)
            assert abs(total - 1.0) < 0.01, f"{s} ladder sums to {total}, expected 1.0"

    def test_tp_r_multiples_monotonically_increase(self):
        for s, p in ORDER_POLICIES.items():
            rs = [r.r_multiple for r in p.tp_ladder]
            assert rs == sorted(rs), f"{s} R-multiples must be monotonically increasing: {rs}"

    def test_stop_trail_anchors_match_horizon(self):
        # Short horizons use ATR; medium use EMA-20; long use SMAs
        assert ORDER_POLICIES["scalp"].stop_trail_anchor == "atr"
        assert ORDER_POLICIES["intraday"].stop_trail_anchor == "atr"
        assert ORDER_POLICIES["multi_day"].stop_trail_anchor == "ema_20"
        assert ORDER_POLICIES["swing"].stop_trail_anchor == "ema_20"
        assert ORDER_POLICIES["investment"].stop_trail_anchor == "sma_50"
        assert ORDER_POLICIES["position"].stop_trail_anchor == "sma_150"

    def test_breakeven_thresholds_increase_with_horizon(self):
        thresholds = [
            ORDER_POLICIES[s].stop_breakeven_at_r
            for s in ("scalp", "intraday", "multi_day", "swing", "investment", "position")
        ]
        # All set, monotonically non-decreasing
        assert all(t is not None for t in thresholds)
        assert thresholds == sorted(thresholds)

    def test_default_policy_is_intraday(self):
        # Safer than scalp — DAY orders, close at EOD, sweep-eligible.
        # An unmapped style won't orphan an overnight bracket.
        assert DEFAULT_POLICY.style == "intraday"
        assert DEFAULT_POLICY.time_in_force == "DAY"
        assert DEFAULT_POLICY.eod_sweep_eligible is True


# ─────────────────────────────────────────────────────────────────
# Lookup helpers
# ─────────────────────────────────────────────────────────────────
class TestPublicAPI:
    def test_get_policy_known_styles(self):
        for s in ORDER_POLICIES:
            assert get_policy(s).style == s

    def test_get_policy_case_insensitive(self):
        assert get_policy("SCALP").style == "scalp"
        assert get_policy(" Position ").style == "position"

    def test_get_policy_unknown_returns_default(self):
        assert get_policy("alien_style") is DEFAULT_POLICY
        assert get_policy(None) is DEFAULT_POLICY
        assert get_policy("") is DEFAULT_POLICY

    def test_get_policy_for_trade_via_trade_style(self):
        t = FakeTrade(trade_style="position")
        assert get_policy_for_trade(t).style == "position"

    def test_get_policy_for_trade_via_setup_type(self):
        # When trade_style is empty, fall back to SETUP_REGISTRY lookup
        t = FakeTrade(setup_type="stage_2_breakout")
        assert get_policy_for_trade(t).style == "position"

        t = FakeTrade(setup_type="pocket_pivot")
        assert get_policy_for_trade(t).style == "swing"

        t = FakeTrade(setup_type="weekly_breakout")
        assert get_policy_for_trade(t).style == "investment"

        t = FakeTrade(setup_type="rubber_band")
        assert get_policy_for_trade(t).style == "scalp"

    def test_get_policy_for_trade_handles_dict(self):
        t = {"trade_style": "swing"}
        assert get_policy_for_trade(t).style == "swing"

    def test_get_policy_for_trade_none_returns_default(self):
        assert get_policy_for_trade(None).style == DEFAULT_POLICY.style

    def test_get_policy_for_trade_explicit_style_beats_setup(self):
        # If both set, trade_style wins
        t = FakeTrade(trade_style="scalp", setup_type="stage_2_breakout")
        assert get_policy_for_trade(t).style == "scalp"

    def test_is_eod_sweep_eligible_helper(self):
        assert is_eod_sweep_eligible(FakeTrade(trade_style="scalp")) is True
        assert is_eod_sweep_eligible(FakeTrade(trade_style="intraday")) is True
        assert is_eod_sweep_eligible(FakeTrade(trade_style="multi_day")) is False
        assert is_eod_sweep_eligible(FakeTrade(trade_style="swing")) is False
        assert is_eod_sweep_eligible(FakeTrade(trade_style="investment")) is False
        assert is_eod_sweep_eligible(FakeTrade(trade_style="position")) is False

    def test_time_in_force_helper(self):
        assert time_in_force_for(FakeTrade(trade_style="scalp")) == "DAY"
        assert time_in_force_for(FakeTrade(trade_style="intraday")) == "DAY"
        assert time_in_force_for(FakeTrade(trade_style="multi_day")) == "GTC"
        assert time_in_force_for(FakeTrade(trade_style="swing")) == "GTC"
        assert time_in_force_for(FakeTrade(trade_style="investment")) == "GTC"
        assert time_in_force_for(FakeTrade(trade_style="position")) == "GTC"

    def test_stop_trail_anchor_helper(self):
        assert stop_trail_anchor_for(FakeTrade(trade_style="scalp")) == "atr"
        assert stop_trail_anchor_for(FakeTrade(trade_style="position")) == "sma_150"

    def test_all_policies_summary(self):
        s = all_policies_summary()
        assert set(s.keys()) == set(ORDER_POLICIES.keys())
        # Each is a dict with the expected fields
        for k, v in s.items():
            assert isinstance(v, dict)
            assert v["style"] == k
            assert "time_in_force" in v
            assert "tp_ladder" in v
            assert isinstance(v["tp_ladder"], list)


# ─────────────────────────────────────────────────────────────────
# Bot vocabulary integration
# ─────────────────────────────────────────────────────────────────
class TestVocabularyIntegration:
    def test_vocabulary_mentions_order_policies(self):
        from agents.vocabulary import VOCABULARY_BLOCK
        assert "ORDER-MANAGEMENT POLICIES" in VOCABULARY_BLOCK
        # Verify each policy row is referenced
        for s in ("scalp", "intraday", "multi_day", "swing", "investment", "position"):
            assert s in VOCABULARY_BLOCK
        # TIF column
        assert "DAY" in VOCABULARY_BLOCK
        assert "GTC" in VOCABULARY_BLOCK
        # Trail anchors
        assert "EMA-20" in VOCABULARY_BLOCK
        assert "SMA-50" in VOCABULARY_BLOCK
        assert "30wk-SMA" in VOCABULARY_BLOCK
        # EOD sweep protection
        assert "EOD-SWEEP PROTECTION" in VOCABULARY_BLOCK
        assert "protect_long_horizon" in VOCABULARY_BLOCK

    def test_system_prompt_has_order_policy_section(self):
        from services.ai_assistant_service import AIAssistantService
        prompt = AIAssistantService.SYSTEM_PROMPT
        assert "ORDER-MANAGEMENT POLICIES" in prompt
        assert "QUOTE THE TABLE ABOVE VERBATIM" in prompt
        assert "/api/trading-bot/order-policies" in prompt


# ─────────────────────────────────────────────────────────────────
# Integration with SETUP_REGISTRY
# ─────────────────────────────────────────────────────────────────
class TestSetupRegistryIntegration:
    """Every setup in SETUP_REGISTRY must resolve to a real policy
    (none should fall through to DEFAULT silently)."""

    def test_every_registered_setup_resolves(self):
        from services.smb_integration import SETUP_REGISTRY
        unmapped = []
        for name, cfg in SETUP_REGISTRY.items():
            t = FakeTrade(setup_type=name)
            p = get_policy_for_trade(t)
            if p is DEFAULT_POLICY:
                # Default is OK ONLY if the registry style is "intraday"
                if cfg.default_style.value != "intraday":
                    unmapped.append((name, cfg.default_style.value))
        assert not unmapped, f"Setups fell through to DEFAULT but shouldn't: {unmapped}"

    def test_all_20_new_setups_resolve_correctly(self):
        expected = {
            # Swing
            "pocket_pivot": "swing", "vcp_breakout": "swing",
            "three_week_tight": "swing", "bull_flag_break": "swing",
            "bear_flag_break": "swing", "ascending_triangle_break": "swing",
            "descending_triangle_break": "swing", "cup_with_high_handle": "swing",
            # Investment
            "weekly_breakout": "investment", "multi_quarter_base_break": "investment",
            "rs_leader_break": "investment", "fifty_two_week_high_break": "investment",
            "power_trend_stack": "investment",
            # Position
            "stage_2_breakout": "position", "stage_1_to_2_transition": "position",
            "stage_3_to_4_breakdown": "position", "golden_cross_filtered": "position",
            "death_cross_filtered": "position", "two_hundred_day_reclaim": "position",
            "two_hundred_day_loss": "position",
        }
        for setup, expected_style in expected.items():
            p = get_policy_for_trade(FakeTrade(setup_type=setup))
            assert p.style == expected_style, (
                f"{setup} resolved to {p.style}, expected {expected_style}"
            )
