"""
Regression tests for v19.34.261 — two EOD safety hardenings:

(#2) EOD re-sweep safety net in PositionManager.check_eod_close — after the
     main close pass sets `_eod_close_executed_today=True`, a close_at_eod
     position that ARRIVES later (late orphan adoption / late parent fill)
     must still be flattened while we're before the bell, instead of being
     permanently short-circuited (the 2026-06-03 class of bug).

(#3) `orphan_gtc_reconciler.classify_intraday_entries_for_eod_sweep` now
     decides EOD-sweep eligibility from the trade-style POLICY
     (`is_eod_sweep_eligible`), NOT the stale per-trade `close_at_eod`
     attribute (79 stored-vs-policy mismatches found 2026-06-03).
"""
import ast
import inspect

from services.orphan_gtc_reconciler import (
    classify_intraday_entries_for_eod_sweep,
    VERDICT_EOD_INTRADAY_ENTRY,
)
from services.position_manager import PositionManager


# ───────────────────────── #3 — policy-driven EOD entry sweep ─────────────────────────

def _order(oid, symbol):
    return {
        "ib_order_id": oid, "symbol": symbol, "action": "BUY",
        "order_type": "LMT", "time_in_force": "DAY", "quantity": 10,
        # status omitted → normalises falsy → passes the working-order gate
    }


def test_intraday_sweep_uses_policy_not_stored_flag():
    """A multi_day trade with a STALE stored close_at_eod=True must NOT be
    swept (policy says hold). An intraday trade with a stale close_at_eod=
    False MUST be swept (policy says close). Decisions follow the policy."""
    orders = [_order(111, "CIEN"), _order(222, "AAPL")]
    trades = [
        # mismatch: stored=True but policy(multi_day)=hold → must be LEFT ALIVE
        {"id": "t-hold", "entry_order_id": 111, "symbol": "CIEN",
         "trade_style": "multi_day", "setup_type": "rs_leader_break",
         "close_at_eod": True, "status": "pending"},
        # mismatch: stored=False but policy(intraday)=close → must be SWEPT
        {"id": "t-close", "entry_order_id": 222, "symbol": "AAPL",
         "trade_style": "intraday", "setup_type": "squeeze",
         "close_at_eod": False, "status": "pending"},
    ]
    verdicts = classify_intraday_entries_for_eod_sweep(
        ib_open_orders=orders, bot_trades=trades,
    )
    swept_ids = {v.bot_trade_id for v in verdicts}
    assert all(v.verdict == VERDICT_EOD_INTRADAY_ENTRY for v in verdicts)
    assert "t-close" in swept_ids, "intraday entry (policy=close) must be swept"
    assert "t-hold" not in swept_ids, (
        "multi_day entry (policy=hold) must NOT be swept despite stale "
        "close_at_eod=True — v19.34.261 policy SSOT"
    )


def test_intraday_sweep_holds_position_style_overnight():
    """A `position`-style entry is never swept (GTC overnight protection)."""
    verdicts = classify_intraday_entries_for_eod_sweep(
        ib_open_orders=[_order(333, "QQQ")],
        bot_trades=[{
            "id": "t-pos", "entry_order_id": 333, "symbol": "QQQ",
            "trade_style": "position", "setup_type": "stage_2_breakout",
            "close_at_eod": True, "status": "pending",
        }],
    )
    assert verdicts == [], "position-style pending entry must be left alive"


def test_reconciler_no_longer_reads_stored_flag_directly():
    """Structural guard: the stale `close_at_eod is not True` check is gone,
    replaced by the policy helper."""
    src = inspect.getsource(classify_intraday_entries_for_eod_sweep)
    assert "is_eod_sweep_eligible" in src
    assert 'matched.get("close_at_eod") is not True' not in src


# ───────────────────────── #2 — EOD re-sweep safety net ─────────────────────────

def test_eod_resweep_block_present_and_falls_through():
    """The executed_today gate must NOT unconditionally return: when residual
    close_at_eod positions remain before the bell, it falls through to the
    main close pass; otherwise it returns."""
    src = inspect.getsource(PositionManager.check_eod_close)
    assert "v19.34.261 EOD-RESWEEP" in src, "re-sweep block missing"
    assert "_eod_resweep_last_ts" in src, "re-sweep throttle missing"

    gate = src.find("if bot._eod_close_executed_today:")
    assert gate > 0
    # Within the gate block, there must be a guarded `else: return` (not a
    # bare unconditional return), and the residual computation must precede
    # the main eod_trades build.
    resweep = src.find("EOD-RESWEEP")
    eod_trades_build = src.find("eod_trades = {")
    assert gate < resweep < eod_trades_build, (
        "re-sweep must sit between the executed_today gate and the main "
        "close pass so residual positions fall through to it"
    )
    # The gate must throttle (so in-flight closes aren't double-fired).
    assert ">= 30.0" in src or ">= 30" in src


def test_check_eod_close_still_parses():
    import services.position_manager as pm
    ast.parse(inspect.getsource(pm))
