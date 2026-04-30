"""
test_critical_pipeline_hardening_v19_29.py — pin v19.29 fixes triggered
by operator's 2026-05-01 EOD screenshot showing:
  Bug 1: 300+ duplicate cancelled orders 2:17pm-3:55pm (order spam)
  Bug 2: New entries fired 3:55-3:59pm (LITE @ 3:59pm w/ no overnight bracket)
  Bug 3: 3:59pm flatten cancellations left positions overnight
  Bug 4: SOFI auto-reconciled SHORT while IB had it LONG (catastrophic)
  Bug 5: TMUS reconciled at 100sh while IB had 255sh (drift)

Five coordinated fixes:
  A. Order-level intent dedup (`services/order_intent_dedup.py`)
  B. Direction-safe reconcile (30s direction stability gate)
  C. Wrong-direction phantom sweep (extends v19.27 phantom sweeper)
  D. 3:45 soft / 3:55 hard EOD no-new-entries gate
  E. EOD flatten escalation alarm via Unified Stream

All tests pure-Python — no IB, no Mongo, no LLM.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ─── A. Order Intent Dedup ───────────────────────────────────────────────

def test_intent_dedup_blocks_duplicate_intent():
    """Same (symbol, side, qty±5%, price±0.5%) intent within TTL must
    be blocked. This is the fix for today's 300+ duplicate BP/SOFI/etc.
    cancellation cascade."""
    from services.order_intent_dedup import OrderIntentDedup
    d = OrderIntentDedup()
    d.mark_pending("BP", "buy", 672, 47.49, trade_id="T-1")
    # Exact match
    assert d.is_already_pending("BP", "buy", 672, 47.49) is not None
    # Within tolerance (qty +3%, price +0.2%)
    assert d.is_already_pending("BP", "buy", 692, 47.58) is not None
    # Outside tolerance (qty +10%) → fresh
    assert d.is_already_pending("BP", "buy", 740, 47.49) is None


def test_intent_dedup_clears_on_fill():
    """Once an intent fills (or rejects), clear_filled() must remove
    the pending stamp so the next legitimate same-intent request
    isn't blocked."""
    from services.order_intent_dedup import OrderIntentDedup
    d = OrderIntentDedup()
    d.mark_pending("SOFI", "buy", 1000, 16.10)
    cleared = d.clear_filled("SOFI", "buy", qty=1000, price=16.10)
    assert cleared == 1
    # Now resubmit — should NOT be blocked
    assert d.is_already_pending("SOFI", "buy", 1000, 16.10) is None


def test_intent_dedup_auto_expires_stale_entries():
    """An intent older than INTENT_TTL_SECONDS must auto-expire so
    a stuck pending doesn't block all future trades for that symbol."""
    from services.order_intent_dedup import OrderIntentDedup, INTENT_TTL_SECONDS
    d = OrderIntentDedup()
    d.mark_pending("HOOD", "buy", 290, 73.10)
    # Fast-forward by mutating the entry's submitted_at
    for entry in d._pending.values():
        entry.submitted_at = datetime.now(timezone.utc) - timedelta(
            seconds=INTENT_TTL_SECONDS + 5
        )
    # Stale → not blocking
    assert d.is_already_pending("HOOD", "buy", 290, 73.10) is None


def test_intent_dedup_distinguishes_buy_from_sell():
    """Bot may legitimately have both a BUY and a SELL pending on the
    same symbol (e.g. open + scaled-out exit). Dedup must NOT collapse
    these — keyed by (symbol, side, …)."""
    from services.order_intent_dedup import OrderIntentDedup
    d = OrderIntentDedup()
    d.mark_pending("SOFI", "buy", 1000, 16.10)
    assert d.is_already_pending("SOFI", "sell", 1000, 16.10) is None


def test_trade_execution_calls_intent_dedup_before_place():
    """Source-level pin: `trade_execution.execute_trade` must check
    intent dedup BEFORE calling `place_bracket_order`."""
    import inspect
    from services import trade_execution
    src = inspect.getsource(trade_execution)
    # The dedup import + check must appear before place_bracket_order
    assert "get_order_intent_dedup" in src
    assert "is_already_pending" in src
    assert "mark_pending" in src
    # Sequence check: is_already_pending must appear before
    # place_bracket_order in the source
    pre_idx = src.find("is_already_pending")
    place_idx = src.find("place_bracket_order(trade)")
    assert pre_idx > 0 and place_idx > 0
    assert pre_idx < place_idx, "intent dedup must run BEFORE place_bracket_order"


# ─── B. Direction-safe reconcile ─────────────────────────────────────────

def test_direction_stability_requires_30s_history():
    """is_direction_stable must return False when no history exists or
    when direction has flipped within the 30s window (today's SOFI bug)."""
    from services.position_reconciler import (
        record_ib_direction_observation,
        is_direction_stable,
        _ib_direction_history,
    )
    # Clear state
    _ib_direction_history.clear()
    # No history → unstable
    stable, reason = is_direction_stable("SOFI", "long")
    assert stable is False
    assert "no_history" in reason

    # Add fresh observations — not enough history yet
    record_ib_direction_observation("SOFI", "long")
    stable, reason = is_direction_stable("SOFI", "long")
    assert stable is False
    assert "insufficient_history" in reason


def test_direction_stability_detects_recent_flip():
    """The exact bug from 2026-05-01 SOFI: direction flipped within
    the stability window from short → long. Reconcile must refuse."""
    from services.position_reconciler import (
        record_ib_direction_observation,
        is_direction_stable,
        _ib_direction_history,
    )
    _ib_direction_history.clear()
    # Simulate: 60s ago SOFI was short, then went long 5s ago (flatten transit)
    now = datetime.now(timezone.utc)
    _ib_direction_history["SOFI"] = [
        (now - timedelta(seconds=60), "short"),
        (now - timedelta(seconds=5), "long"),
    ]
    stable, reason = is_direction_stable("SOFI", "long")
    assert stable is False
    assert "flipped_within" in reason


def test_direction_stability_passes_after_30s_continuous():
    """If direction has been continuously consistent for ≥30s,
    reconcile is allowed to proceed."""
    from services.position_reconciler import (
        is_direction_stable,
        _ib_direction_history,
    )
    _ib_direction_history.clear()
    now = datetime.now(timezone.utc)
    # 60s of consistent long observations
    _ib_direction_history["AAPL"] = [
        (now - timedelta(seconds=60), "long"),
        (now - timedelta(seconds=30), "long"),
        (now - timedelta(seconds=10), "long"),
        (now - timedelta(seconds=2), "long"),
    ]
    stable, reason = is_direction_stable("AAPL", "long")
    assert stable is True
    assert reason == ""


def test_reconcile_method_includes_direction_stability_gate():
    """Source-level pin: reconcile_orphan_positions must call
    is_direction_stable BEFORE creating the BotTrade."""
    import inspect
    from services.position_reconciler import PositionReconciler
    src = inspect.getsource(PositionReconciler.reconcile_orphan_positions)
    assert "is_direction_stable" in src
    assert "direction_unstable" in src


# ─── C. Wrong-direction phantom sweep ────────────────────────────────────

def test_position_manager_sweeps_wrong_direction_phantoms():
    """Source-level pin: position_manager.update_open_positions must
    detect bot trades whose direction disagrees with IB's net direction
    for the symbol, and close-state them as wrong_direction_phantom_swept."""
    import inspect
    from services.position_manager import PositionManager
    src = inspect.getsource(PositionManager.update_open_positions)
    assert "wrong_direction_phantom_swept_v19_29" in src
    # Must check IB's opposite-direction qty before sweeping
    assert "ib_qty_opp_dir" in src
    assert "opp = " in src


# ─── D. EOD no-new-entries gate ──────────────────────────────────────────

def test_opportunity_evaluator_has_eod_gates():
    """Source-level pin: opportunity_evaluator.evaluate_opportunity must
    enforce both 3:45 soft cut and 3:55 hard cut in ET."""
    import inspect
    from services.opportunity_evaluator import OpportunityEvaluator
    src = inspect.getsource(OpportunityEvaluator.evaluate_opportunity)
    assert "v19.29" in src
    assert "EOD-HARD-CUT" in src
    assert "EOD-SOFT-CUT" in src
    # Hard cut must be 15:55 (3:55pm)
    assert "15 * 60 + 55" in src
    # Soft cut must be 15:45 (3:45pm)
    assert "15 * 60 + 45" in src
    # Must skip weekends
    assert "weekday()" in src


def test_opportunity_evaluator_returns_none_on_hard_cut():
    """Source pin: when past 3:55pm ET, evaluate_opportunity must
    `return None` (no new trades) and emit the eod_no_new_entries_hard
    Unified Stream event."""
    import inspect
    from services.opportunity_evaluator import OpportunityEvaluator
    src = inspect.getsource(OpportunityEvaluator.evaluate_opportunity)
    assert "eod_no_new_entries_hard" in src
    assert "eod_no_new_entries" in src  # rejection reason code


# ─── E. EOD flatten escalation alarm ─────────────────────────────────────

def test_eod_close_emits_alarm_on_failure():
    """Source-level pin: when EOD close has failed_symbols, position_
    manager must emit a CRITICAL/HIGH/WARNING Unified Stream alarm
    (operator visibility, not just backend log)."""
    import inspect
    from services.position_manager import PositionManager
    src = inspect.getsource(PositionManager.check_eod_close)
    assert "eod_flatten_failed" in src
    assert "CRITICAL" in src or "HIGH" in src
    assert "USE 'CLOSE ALL NOW' BUTTON" in src


# ─── Integration: dedup is wired into the cleanup paths ──────────────────

def test_trade_execution_clears_intent_on_fill():
    """When an order fills, dedup.clear_filled must be called so the
    pending stamp doesn't outlive the fill."""
    import inspect
    from services import trade_execution
    src = inspect.getsource(trade_execution)
    # Both the success and rejection branches must clear the intent
    assert src.count("clear_filled(") >= 2


def test_position_manager_records_direction_observations():
    """Source-level pin: position_manager.update_open_positions must
    feed direction observations to record_ib_direction_observation()
    so the reconcile stability gate has fresh data."""
    import inspect
    from services.position_manager import PositionManager
    src = inspect.getsource(PositionManager.update_open_positions)
    assert "record_ib_direction_observation" in src
