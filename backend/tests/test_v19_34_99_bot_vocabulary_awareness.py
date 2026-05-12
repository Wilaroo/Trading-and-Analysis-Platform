"""
Tests for v19.34.99 — AI assistant awareness of new v19.34.95+ vocabulary.

Validates:
  - SYSTEM_PROMPT contains the 5-horizon taxonomy section
  - SYSTEM_PROMPT mentions every new setup name (20 detectors)
  - SYSTEM_PROMPT documents both exposure caps (30% / 55%)
  - strategy_keywords list catches questions about new setups
  - exposure_keywords trigger the live-cap context injection
"""
from __future__ import annotations

import re

import pytest

from services.ai_assistant_service import AIAssistantService


SYSTEM_PROMPT = AIAssistantService.SYSTEM_PROMPT


# ─────────────────────────────────────────────────────────────────
# SYSTEM_PROMPT coverage
# ─────────────────────────────────────────────────────────────────
class TestSystemPromptVocabulary:
    def test_five_horizons_section_present(self):
        assert "5-HORIZON TRADE-STYLE TAXONOMY" in SYSTEM_PROMPT

    def test_all_five_styles_documented(self):
        for style_label in ["SCALP", "INTRADAY", "SWING", "INVESTMENT", "POSITION"]:
            assert style_label in SYSTEM_PROMPT, f"Style {style_label} missing"

    def test_horizon_durations_documented(self):
        # At least one duration phrase per style
        for phrase in [
            "minutes – 1 hour",
            "1 – 6 hours",
            "1 – 3 weeks",
            "3 weeks – 3 months",
            "3+ months",
        ]:
            assert phrase in SYSTEM_PROMPT, f"Duration '{phrase}' missing"

    def test_legacy_aliases_explained(self):
        for alias in ["A+", "TRADE_2_HOLD", "MOVE_2_MOVE", "multi_day"]:
            assert alias in SYSTEM_PROMPT, f"Legacy alias '{alias}' not documented"

    def test_all_20_new_setups_named(self):
        new_setups = [
            # Swing
            "pocket_pivot", "vcp_breakout", "three_week_tight",
            "bull_flag_break", "bear_flag_break",
            "ascending_triangle_break", "descending_triangle_break",
            "cup_with_high_handle",
            # Investment
            "weekly_breakout", "multi_quarter_base_break", "rs_leader_break",
            "fifty_two_week_high_break", "power_trend_stack",
            # Position
            "stage_2_breakout", "stage_1_to_2_transition", "stage_3_to_4_breakdown",
            "golden_cross_filtered", "death_cross_filtered",
            "two_hundred_day_reclaim", "two_hundred_day_loss",
        ]
        missing = [s for s in new_setups if s not in SYSTEM_PROMPT]
        assert not missing, f"Setups missing from SYSTEM_PROMPT: {missing}"

    def test_six_prior_daily_detectors_referenced(self):
        # These were broken before v19.34.98 and now emit alerts.
        # The bot should know they exist.
        for setup in ["daily_squeeze", "trend_continuation", "daily_breakout",
                      "base_breakout", "accumulation_entry", "breakdown_confirmed"]:
            assert setup in SYSTEM_PROMPT, f"Setup {setup} missing"

    def test_thirty_percent_position_cap_documented(self):
        assert "30%" in SYSTEM_PROMPT
        assert "POSITION-only cap" in SYSTEM_PROMPT

    def test_fifty_five_percent_long_horizon_cap_documented(self):
        assert "55%" in SYSTEM_PROMPT
        assert "LONG-HORIZON" in SYSTEM_PROMPT

    def test_cap_block_response_format_explained(self):
        # The bot needs to know what `exposure_cap_warnings` means
        assert "exposure_cap_warnings" in SYSTEM_PROMPT
        assert "Portfolio exposure cap exhausted" in SYSTEM_PROMPT

    def test_portfolio_exposure_endpoint_referenced(self):
        # So the bot can suggest the endpoint when asked
        assert "/api/risk/position-sizing/portfolio-exposure" in SYSTEM_PROMPT

    def test_tradestylechip_colors_documented(self):
        for tone in ["fuchsia", "sky", "emerald", "amber", "rose"]:
            assert tone in SYSTEM_PROMPT

    def test_minervini_oneill_weinstein_namechecks(self):
        # Operator may reference the source authors — bot should know
        for name in ["Minervini", "O'Neil", "Weinstein", "Darvas", "Mansfield"]:
            assert name in SYSTEM_PROMPT, f"Author {name} missing"


# ─────────────────────────────────────────────────────────────────
# Context-builder keyword coverage
# ─────────────────────────────────────────────────────────────────
class TestKeywordCoverage:
    """The context builder uses two keyword lists — strategy_keywords (line
    ~1607 of ai_assistant_service.py) and exposure_keywords (line ~1622).
    We can't easily call the private method here, so we read the source
    file to assert that the right keywords were added in v19.34.99.
    """
    @classmethod
    def setup_class(cls):
        from pathlib import Path
        src_path = Path(__file__).resolve().parent.parent / "services" / "ai_assistant_service.py"
        cls.src = src_path.read_text()

    def test_strategy_keywords_includes_new_setup_names(self):
        for kw in ["pocket pivot", "vcp", "stage 2", "weekly breakout",
                  "rs leader", "200dma", "golden cross", "minervini",
                  "weinstein", "bull flag", "bear flag"]:
            assert f"'{kw}'" in self.src or f'"{kw}"' in self.src, (
                f"strategy_keywords missing '{kw}'"
            )

    def test_strategy_keywords_includes_horizon_words(self):
        for kw in ["intraday", "swing", "investment", "horizon", "trade style"]:
            assert f"'{kw}'" in self.src or f'"{kw}"' in self.src, (
                f"strategy_keywords missing '{kw}'"
            )

    def test_exposure_keywords_present(self):
        for kw in ["cap", "exposure", "blocked", "downsized", "buying power",
                  "long-horizon", "30%", "55%"]:
            assert f'"{kw}"' in self.src, f"exposure_keywords missing '{kw}'"

    def test_live_snapshot_injection_path_present(self):
        # Sanity: the code that pulls live exposure snapshot is wired
        assert "LIVE PORTFOLIO EXPOSURE" in self.src
        assert "compute_exposure(open_trades_list" in self.src
        assert "Per-trade breakdown" in self.src


# ─────────────────────────────────────────────────────────────────
# Multi-agent orchestrator awareness
# ─────────────────────────────────────────────────────────────────
class TestAgentVocabularyInjection:
    def test_vocabulary_module_exists_and_has_block(self):
        from agents.vocabulary import VOCABULARY_BLOCK, inject_vocabulary
        assert "SENTCOM SHARED VOCABULARY" in VOCABULARY_BLOCK
        for style in ["scalp", "intraday", "multi_day", "swing", "investment", "position"]:
            assert style in VOCABULARY_BLOCK, f"Style {style} missing"
        for setup in ["pocket_pivot", "vcp_breakout", "stage_2_breakout",
                      "weekly_breakout", "two_hundred_day_reclaim"]:
            assert setup in VOCABULARY_BLOCK, f"Setup {setup} missing"
        # 30% / 55% caps documented
        assert "30%" in VOCABULARY_BLOCK
        assert "55%" in VOCABULARY_BLOCK
        # Inject is idempotent
        once = inject_vocabulary("base prompt.")
        twice = inject_vocabulary(once)
        assert once == twice

    def test_analyst_agent_prompt_has_vocabulary(self):
        try:
            from agents.analyst_agent import AnalystAgent
        except Exception as exc:
            pytest.skip(f"AnalystAgent not importable in isolation: {exc}")
        agent = AnalystAgent.__new__(AnalystAgent)
        prompt = agent.get_system_prompt()
        assert "SENTCOM SHARED VOCABULARY" in prompt

    def test_coach_agent_prompt_has_vocabulary(self):
        try:
            from agents.coach_agent import CoachAgent
        except Exception as exc:
            pytest.skip(f"CoachAgent not importable in isolation: {exc}")
        agent = CoachAgent.__new__(CoachAgent)
        prompt = agent.get_system_prompt()
        assert "SENTCOM SHARED VOCABULARY" in prompt
