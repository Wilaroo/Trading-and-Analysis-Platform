"""
test_stat_hygiene_v284.py — guards the strategy_stats rebuild logic.

Covers:
  - legacy reconciliation/phantom artifact rows are detected even with NO
    `genuine` field (the v284 leak that over-gated the Smart Filter).
  - 0-PnL scratch closes are classified as neither win nor loss (the old
    bot_trades rebuild's "0 PnL counted as a loss" bug must NOT recur).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pnl_compute import (  # noqa: E402
    _is_reconciliation_artifact,
    _classify_outcome,
    _base_setup,
)


class TestArtifactGuard:
    def test_reconciled_orphan_is_artifact(self):
        assert _is_reconciliation_artifact("reconciled_orphan", "reconciled_orphan") is True

    def test_reconciled_excess_slice_is_artifact(self):
        assert _is_reconciliation_artifact("reconciled_excess_slice", "naked_sweep_reissue") is True

    def test_phantom_close_is_artifact(self):
        assert _is_reconciliation_artifact("vwap_fade", "wrong_direction_phantom_swept_v19_29") is True

    def test_sweep_reason_is_artifact(self):
        assert _is_reconciliation_artifact("breakout_long", "phantom_sibling_purge") is True

    def test_genuine_strategy_close_is_not_artifact(self):
        assert _is_reconciliation_artifact("breakout_long", "target_hit") is False
        assert _is_reconciliation_artifact("squeeze", "stop_loss") is False

    def test_none_inputs_safe(self):
        assert _is_reconciliation_artifact(None, None) is False


class TestScratchClassification:
    def test_zero_pnl_scratch_is_neither_win_nor_loss(self):
        # outcome="scratch", r=0, pnl=0 → None (excluded, NOT a loss).
        assert _classify_outcome("scratch", 0.0, 0.0) is None

    def test_zero_everything_is_none(self):
        assert _classify_outcome(None, None, 0.0) is None

    def test_positive_pnl_is_win(self):
        assert _classify_outcome("won", 1.5, 120.0) == "win"

    def test_negative_pnl_is_loss(self):
        assert _classify_outcome("lost", -1.0, -80.0) == "loss"

    def test_r_only_classifies(self):
        assert _classify_outcome("", 0.8, 0) == "win"
        assert _classify_outcome("", -0.5, 0) == "loss"


class TestBaseSetup:
    def test_strips_direction_suffix(self):
        assert _base_setup("trend_continuation_short") == "trend_continuation"
        assert _base_setup("breakout_long") == "breakout"

    def test_no_suffix_unchanged(self):
        assert _base_setup("squeeze") == "squeeze"
