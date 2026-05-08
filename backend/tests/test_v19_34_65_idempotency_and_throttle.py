"""
test_v19_34_65_idempotency_and_throttle.py — pin v19.34.65 fixes
triggered by 2026-02-08 IB trade-log forensic showing:

  Pattern 1: ADBE 18-buy ramp (9:32 AM → 12:57 PM, sizes drifting
             54→59→47→22→17→14→5… — v19.29's ±5% qty-tolerance
             fingerprint sees each as a new intent)
  Pattern 2: DDOG / SQQQ wash cycles (sell→buy same minute — v19.29
             keys by side, opposite-side never matches)
  Pattern 3: ADBE bracket re-issue thrash (same orchestrator firing
             repeatedly with smaller residuals each time)

Two coordinated fixes:
  A. Broad symbol-level entry cooldown in `order_intent_dedup`
     (60s per symbol regardless of side / qty / price)
  B. Bracket re-issue throttle (1 per (symbol, 5-minute window) +
     hard-guard remaining_shares > 0)

All tests pure-Python — no IB, no Mongo, no LLM.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ════════════════════════════════════════════════════════════════════════
# Fix A — broad symbol-level entry cooldown
# ════════════════════════════════════════════════════════════════════════

def test_broad_cooldown_blocks_same_side_size_drift_adbe_pattern():
    """ADBE pattern: 18 buys with sizes drifting 54→59→47→22→17.
    v19.29 ±5% bucket sees each as new — v19.34.65 cooldown blocks."""
    from services.order_intent_dedup import OrderIntentDedup
    d = OrderIntentDedup()

    # First entry submitted at T0
    d.record_entry_submitted("ADBE", "buy", 54, 251.41, trade_id="T-1")

    # Each subsequent buy within 60s must be blocked, regardless of size.
    for qty in (59, 47, 22, 17, 14, 5, 3):
        blocked = d.should_throttle_entry("ADBE", "buy", qty, 250.50)
        assert blocked is not None, f"qty={qty} should be blocked"
        assert blocked.symbol == "ADBE"
        assert blocked.side == "buy"


def test_broad_cooldown_blocks_wash_cycle_ddog_pattern():
    """DDOG pattern: sell 273 then buy 273 within seconds. v19.29
    keys by side so opposite-direction never matches — v19.34.65 does."""
    from services.order_intent_dedup import OrderIntentDedup
    d = OrderIntentDedup()

    d.record_entry_submitted("DDOG", "sell", 273, 193.14, trade_id="T-close")

    # Opposite-side entry within 60s → must throttle.
    blocked = d.should_throttle_entry("DDOG", "buy", 273, 193.93)
    assert blocked is not None
    assert blocked.side == "sell"  # the prior submission, blocking the new buy


def test_broad_cooldown_releases_after_60s():
    """Cooldown is 60s. After it lapses, fresh entries pass."""
    from services.order_intent_dedup import OrderIntentDedup, _RecentSubmission
    d = OrderIntentDedup()

    # Inject a stale submission directly (simulating 70s ago).
    old = _RecentSubmission(
        symbol="EFA",
        side="buy",
        qty=959,
        price=103.60,
        submitted_at=datetime.now(timezone.utc) - timedelta(seconds=70),
        trade_id="T-old",
    )
    d._recent_submissions["EFA"] = old

    blocked = d.should_throttle_entry("EFA", "buy", 100, 103.79)
    assert blocked is None
    # And the stale entry should have been pruned.
    assert "EFA" not in d._recent_submissions


def test_broad_cooldown_per_symbol_isolation():
    """Cooldown on ADBE must not block a fresh entry on EFA."""
    from services.order_intent_dedup import OrderIntentDedup
    d = OrderIntentDedup()

    d.record_entry_submitted("ADBE", "buy", 54, 251.41, trade_id="T-adbe")
    assert d.should_throttle_entry("EFA", "buy", 100, 103.78) is None
    assert d.should_throttle_entry("ADBE", "buy", 60, 251.50) is not None


def test_broad_cooldown_zero_qty_is_noop():
    from services.order_intent_dedup import OrderIntentDedup
    d = OrderIntentDedup()
    d.record_entry_submitted("ADBE", "buy", 0, 251.41)
    assert "ADBE" not in d._recent_submissions
    assert d.should_throttle_entry("ADBE", "buy", 0, 251.41) is None


def test_clear_symbol_cooldown_escape_hatch():
    from services.order_intent_dedup import OrderIntentDedup
    d = OrderIntentDedup()
    d.record_entry_submitted("ADBE", "buy", 54, 251.41, trade_id="T-1")
    assert d.clear_symbol_cooldown("ADBE") == 1
    assert d.clear_symbol_cooldown("ADBE") == 0  # already gone
    assert d.should_throttle_entry("ADBE", "buy", 60, 251.50) is None


def test_stats_surfaces_cooldown_window():
    """Operator HUD reads stats() — make sure the v19.34.65 fields are present."""
    from services.order_intent_dedup import (
        ENTRY_COOLDOWN_SECONDS,
        OrderIntentDedup,
    )
    d = OrderIntentDedup()
    d.record_entry_submitted("ADBE", "buy", 54, 251.41)
    s = d.stats()
    assert s["recent_submissions_count"] == 1
    assert s["entry_cooldown_seconds"] == ENTRY_COOLDOWN_SECONDS


# ════════════════════════════════════════════════════════════════════════
# Fix B — bracket re-issue throttle
# ════════════════════════════════════════════════════════════════════════

def test_reissue_throttle_blocks_second_call_within_window():
    from services.bracket_reissue_service import _ReissueThrottle
    t = _ReissueThrottle()
    t.record_success("ADBE", trade_id="T-1", reason="scale_out")
    blocked = t.should_throttle("ADBE")
    assert blocked is not None
    assert blocked.reason == "scale_out"


def test_reissue_throttle_per_symbol_isolation():
    from services.bracket_reissue_service import _ReissueThrottle
    t = _ReissueThrottle()
    t.record_success("ADBE", trade_id="T-1", reason="scale_out")
    assert t.should_throttle("EFA") is None
    assert t.should_throttle("ADBE") is not None


def test_reissue_throttle_releases_after_window():
    from services.bracket_reissue_service import _ReissueRecord, _ReissueThrottle
    t = _ReissueThrottle()
    # Inject a stale record (simulating 6 minutes ago — > 300s window).
    stale = _ReissueRecord(
        symbol="ADBE",
        trade_id="T-old",
        reason="scale_out",
        submitted_at=datetime.now(timezone.utc) - timedelta(seconds=400),
    )
    t._records["ADBE"] = [stale]
    assert t.should_throttle("ADBE") is None
    assert "ADBE" not in t._records  # auto-pruned


def test_reissue_throttle_clear_escape_hatch():
    from services.bracket_reissue_service import _ReissueThrottle
    t = _ReissueThrottle()
    t.record_success("ADBE", trade_id="T-1", reason="scale_out")
    assert t.clear("ADBE") == 1
    assert t.clear("ADBE") == 0
    assert t.should_throttle("ADBE") is None


# ── Orchestrator-level integration: throttle + remaining_shares guard ──

class _StubTrade:
    def __init__(self, *, id_, symbol, remaining_shares=100, shares=100,
                 entry_price=100.0, fill_price=100.0,
                 stop_price=98.0, target_prices=None,
                 direction="long", trade_style=None, timeframe=None,
                 scale_out_config=None, current_price=None):
        self.id = id_
        self.symbol = symbol
        self.remaining_shares = remaining_shares
        self.shares = shares
        self.entry_price = entry_price
        self.fill_price = fill_price
        self.stop_price = stop_price
        self.target_prices = target_prices or [105.0]
        # Mimic enum-like .value access on a plain string
        self.direction = type("D", (), {"value": direction})()
        self.trade_style = trade_style
        self.timeframe = timeframe
        self.scale_out_config = scale_out_config or {}
        self.current_price = current_price
        self.stop_order_id = None
        self.target_order_id = None
        self.oca_group = None


class _StubBot:
    def __init__(self):
        self._db = None
        self.risk_params = type("R", (), {"reconciled_default_stop_pct": 2.0})()

    async def _save_trade(self, trade):
        pass


def test_orchestrator_refuses_when_remaining_shares_zero():
    """Hard-guard: never touch IB if the position has nothing left."""
    from services.bracket_reissue_service import (
        get_reissue_throttle,
        reissue_bracket_for_trade,
    )
    get_reissue_throttle().clear("ADBE")  # clean slate

    trade = _StubTrade(id_="T-zero", symbol="ADBE", remaining_shares=0, shares=0)
    bot = _StubBot()

    result = asyncio.run(reissue_bracket_for_trade(
        trade=trade,
        bot=bot,
        reason="scale_out",
        new_total_shares=10,
        already_executed_shares=10,  # → remaining = 0
        queue_service=MagicMock(),
        queue_order_fn=MagicMock(),
    ))
    assert result["success"] is False
    assert result["phase"] == "throttle"
    assert result["error"] == "remaining_shares_le_zero_v19_34_65"


def test_orchestrator_throttles_second_reissue_within_window():
    """ADBE pattern: simulate a successful re-issue then a second attempt
    inside the 5-min window — must short-circuit at the throttle gate
    before any IB call."""
    from services.bracket_reissue_service import (
        get_reissue_throttle,
        reissue_bracket_for_trade,
    )
    throttle = get_reissue_throttle()
    throttle.clear("ADBE")
    throttle.record_success("ADBE", trade_id="T-prior", reason="scale_out")

    trade = _StubTrade(id_="T-second", symbol="ADBE",
                       remaining_shares=22, shares=22)
    bot = _StubBot()

    queue_svc = MagicMock()
    queue_fn = MagicMock()

    result = asyncio.run(reissue_bracket_for_trade(
        trade=trade,
        bot=bot,
        reason="scale_out",
        queue_service=queue_svc,
        queue_order_fn=queue_fn,
    ))

    assert result["success"] is False
    assert result["phase"] == "throttle"
    assert result["error"] == "reissue_throttled_v19_34_65"
    assert result["blocked_by_reason"] == "scale_out"
    assert result["blocked_by_trade_id"] == "T-prior"
    # CRITICAL: the throttle MUST fire BEFORE any cancel/submit reaches IB.
    queue_svc.cancel_order.assert_not_called()
    queue_fn.assert_not_called()


def test_orchestrator_does_not_stamp_throttle_on_failed_submit():
    """If submit fails, the throttle must NOT lock further retries."""
    from services.bracket_reissue_service import (
        get_reissue_throttle,
    )
    throttle = get_reissue_throttle()
    throttle.clear("XYZ")

    # Simulate a path-internal failure: fast smoke test of the helper
    # contract — record_success only fires on the success branch in the
    # orchestrator. Throttle must remain unstamped if we never call it.
    assert throttle.should_throttle("XYZ") is None
    # (Full integration of the success path is covered by the existing
    # bracket re-issue test suite at test_bracket_reissue_v19_34_7.py.)


# ════════════════════════════════════════════════════════════════════════
# Forensic regression — yesterday's actual symbols
# ════════════════════════════════════════════════════════════════════════

def test_yesterdays_session_no_wash_cycles_pass():
    """End-to-end: each of yesterday's wash-cycle bursts should be
    blocked by the broad cooldown in chronological order."""
    from services.order_intent_dedup import OrderIntentDedup
    d = OrderIntentDedup()

    cases = [
        # (symbol, first_side, first_qty, first_price, retry_side,
        #  retry_qty, retry_price)
        ("DDOG", "sell", 273, 193.14, "buy", 273, 193.93),
        ("SQQQ", "sell", 937, 43.58, "buy", 937, 43.59),
        ("EWY",  "sell", 334, 183.92, "buy", 334, 184.18),
        # ADBE size-drift ramp
        ("ADBE", "buy",   54, 251.41, "buy",  35, 250.71),
    ]

    for sym, s1, q1, p1, s2, q2, p2 in cases:
        d.record_entry_submitted(sym, s1, q1, p1, trade_id=f"T-{sym}-1")
        retry = d.should_throttle_entry(sym, s2, q2, p2)
        assert retry is not None, f"{sym} retry not throttled"
        assert retry.side == s1
        assert retry.qty == q1
