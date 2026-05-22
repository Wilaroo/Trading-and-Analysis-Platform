"""
test_alert_outcomes_trade_grade_fallback_v19_34_89.py
─────────────────────────────────────────────────────────────────────────────
Regression guard for v19.34.89 — `alert_outcomes.trade_grade` was being
written as `None` because the writer in `pnl_compute._record_alert_outcome_bestEffort`
only consulted `trade.trade_grade`, while the canonical SMB grade set
by the setup grader actually lives on `trade.smb_grade`.

This left ~180 production `alert_outcomes` docs with `trade_grade=None`
and broke `backend/scripts/setup_retro.py`'s Grade A/B/C analytics.

After the fix, the writer must:
  1. Prefer `trade.trade_grade` when set (explicit override path).
  2. Fall back to `trade.smb_grade` when `trade_grade` is missing/None.
  3. Tolerate trades with neither attribute (returns None silently).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest


def _build_trade(**overrides) -> SimpleNamespace:
    base = dict(
        id="t-grade-89",
        symbol="ETHU",
        setup_type="vwap_reclaim",
        direction=SimpleNamespace(value="long"),
        fill_price=10.0,
        stop_price=9.5,
        tp_price=11.0,
        shares=100,
        closed_at="2026-02-01T00:00:00Z",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _captured_doc_from_upsert(mock_coll: MagicMock) -> dict:
    """Pull the $set doc that the writer would have upserted."""
    assert mock_coll.update_one.called, "writer never called update_one"
    args, kwargs = mock_coll.update_one.call_args
    update = args[1] if len(args) > 1 else kwargs.get("update")
    return update["$set"]


class TestTradeGradeFallback:
    def test_smb_grade_used_when_trade_grade_absent(self):
        """Production case: setup_grader stamps smb_grade='B' on the
        trade, trade_grade was never populated, alert_outcomes must
        record 'B' (not None)."""
        from services import pnl_compute
        trade = _build_trade(smb_grade="B")
        mock_coll = MagicMock()
        with patch.object(pnl_compute, "_get_outcomes_collection",
                          return_value=mock_coll):
            pnl_compute._record_alert_outcome_bestEffort(
                trade,
                reason="target_hit",
                pnl={"realized_pnl": 100.0, "net_pnl": 98.0, "shares": 100},
                exit_price=11.0,
                exit_source="explicit",
            )
        doc = _captured_doc_from_upsert(mock_coll)
        assert doc["trade_grade"] == "B"

    def test_trade_grade_preferred_over_smb_grade(self):
        """When BOTH are set, trade_grade wins (explicit override)."""
        from services import pnl_compute
        trade = _build_trade(trade_grade="A", smb_grade="C")
        mock_coll = MagicMock()
        with patch.object(pnl_compute, "_get_outcomes_collection",
                          return_value=mock_coll):
            pnl_compute._record_alert_outcome_bestEffort(
                trade,
                reason="target_hit",
                pnl={"realized_pnl": 50.0, "net_pnl": 50.0, "shares": 50},
                exit_price=11.0,
                exit_source="explicit",
            )
        doc = _captured_doc_from_upsert(mock_coll)
        assert doc["trade_grade"] == "A"

    def test_none_when_neither_attribute_set(self):
        """Trades created before grading was rolled out have neither
        attribute — writer must not crash and must write None."""
        from services import pnl_compute
        trade = _build_trade()  # no trade_grade, no smb_grade
        mock_coll = MagicMock()
        with patch.object(pnl_compute, "_get_outcomes_collection",
                          return_value=mock_coll):
            pnl_compute._record_alert_outcome_bestEffort(
                trade,
                reason="stop_loss",
                pnl={"realized_pnl": -25.0, "net_pnl": -27.0, "shares": 100},
                exit_price=9.5,
                exit_source="explicit",
            )
        doc = _captured_doc_from_upsert(mock_coll)
        assert doc["trade_grade"] is None

    def test_trade_grade_none_falls_through_to_smb_grade(self):
        """trade_grade explicitly set to None must NOT block fallback."""
        from services import pnl_compute
        trade = _build_trade(trade_grade=None, smb_grade="A")
        mock_coll = MagicMock()
        with patch.object(pnl_compute, "_get_outcomes_collection",
                          return_value=mock_coll):
            pnl_compute._record_alert_outcome_bestEffort(
                trade,
                reason="target_hit",
                pnl={"realized_pnl": 200.0, "net_pnl": 196.0, "shares": 200},
                exit_price=12.0,
                exit_source="explicit",
            )
        doc = _captured_doc_from_upsert(mock_coll)
        assert doc["trade_grade"] == "A"
