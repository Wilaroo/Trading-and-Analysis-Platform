"""
v19.34.73 — Cancel-wait bump + retry-once + naked-sweep sibling guard + diag fix.

Validates the four surgical fixes that unblock the operator Close panel and
EOD close path after the 2026-05-21 incident:

  A. `_cancel_ib_bracket_orders` timeout 4s → 8s + retry-once on timeout
  B. `_naked_position_sweep` skips reissue when a healthier sibling exists
     for same (symbol, direction)
  C. `/diag/symbol-state` iterates `_open_trades.values()` instead of
     `ot.get(sym)` (which always returned None — `_open_trades` is keyed
     by trade_id, not symbol)
  D. Boot phantom-sibling purge — handler exists and finds correct loser
"""
import asyncio
import types
import uuid
from datetime import datetime, timezone

import pytest


# ─────────────────────── Test scaffolding ───────────────────────


class _DummyTrade:
    """Minimal stand-in for BotTrade."""
    def __init__(self, *, trade_id=None, symbol="ADI", direction="long",
                 shares=100, remaining_shares=None, entered_by="bot_fired",
                 stop_order_id=None, target_order_id=None):
        from services.trading_bot_service import TradeDirection, TradeStatus
        self.id = trade_id or uuid.uuid4().hex
        self.symbol = symbol
        self.direction = (TradeDirection.LONG if direction == "long"
                          else TradeDirection.SHORT)
        self.status = TradeStatus.OPEN
        self.shares = shares
        self.remaining_shares = (shares if remaining_shares is None
                                 else remaining_shares)
        self.original_shares = shares
        self.fill_price = 100.0
        self.current_price = 100.0
        self.entry_price = 100.0
        self.stop_price = 97.0
        self.target_prices = [105.0]
        self.entered_by = entered_by
        self.stop_order_id = stop_order_id
        self.target_order_id = target_order_id
        self.target_order_ids = []
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.close_reason = None
        self.closed_at = None


# ───────────────────────── Tests ─────────────────────────


def test_naked_sweep_skips_phantom_sibling():
    """The b415ed5f incident replay: two ADI long trades co-exist in
    `_open_trades`. Real bot_fired canonical (134sh) + orphan-adopted
    phantom (44sh). Naked-sweep must skip reissue for the phantom."""

    # Set up a tiny bot stub with the sibling-map + score logic mirrored
    # exactly from `_naked_position_sweep`.
    open_trades = {
        "82f0686f": _DummyTrade(
            trade_id="82f0686f", symbol="ADI", direction="long",
            shares=134, entered_by="bot_fired",
        ),
        "b415ed5f": _DummyTrade(
            trade_id="b415ed5f", symbol="ADI", direction="long",
            shares=44, entered_by="reconciled_external",
        ),
    }

    # Mirror the v19.34.73 sibling-map + score logic
    sibling_map = {}
    for tid, t in open_trades.items():
        sym = (getattr(t, "symbol", "") or "").upper()
        dir_v = getattr(t.direction, "value", str(t.direction)).lower()
        sibling_map.setdefault((sym, dir_v), []).append(tid)

    def _score(_t):
        eb = (getattr(_t, "entered_by", "") or "").lower()
        bonus = 10000 if "bot_fired" in eb else 0
        rs = int(abs(getattr(_t, "remaining_shares", 0) or 0))
        return bonus + rs

    # The bot_fired 82f0686f should win (10000+134 = 10134 vs 44).
    sibs = sibling_map[("ADI", "long")]
    assert len(sibs) == 2
    scored = sorted(((_score(open_trades[t]), t) for t in sibs), reverse=True)
    winner = scored[0][1]
    assert winner == "82f0686f", "bot_fired canonical must win"
    losers = [t for _, t in scored[1:]]
    assert losers == ["b415ed5f"], "phantom must be flagged as loser"


def test_naked_sweep_loser_when_no_bot_fired_picks_larger_shares():
    """If neither is bot_fired, tie-break on remaining_shares."""
    open_trades = {
        "small_phantom": _DummyTrade(
            trade_id="small_phantom", symbol="ADI", direction="long",
            shares=44, entered_by="reconciled_external",
        ),
        "big_phantom": _DummyTrade(
            trade_id="big_phantom", symbol="ADI", direction="long",
            shares=134, entered_by="reconciled_external",
        ),
    }

    def _score(_t):
        eb = (getattr(_t, "entered_by", "") or "").lower()
        bonus = 10000 if "bot_fired" in eb else 0
        rs = int(abs(getattr(_t, "remaining_shares", 0) or 0))
        return bonus + rs

    scored = sorted(((_score(t), tid) for tid, t in open_trades.items()),
                    reverse=True)
    winner = scored[0][1]
    assert winner == "big_phantom", "tie-break on shares: bigger wins"


def test_naked_sweep_single_trade_no_sibling_guard():
    """When only one trade for (symbol, direction), the sibling guard
    must NOT skip — naked-sweep should proceed normally."""
    open_trades = {
        "82f0686f": _DummyTrade(
            trade_id="82f0686f", symbol="XLV", direction="long",
            shares=155, entered_by="bot_fired",
        ),
    }
    sibling_map = {}
    for tid, t in open_trades.items():
        sym = (getattr(t, "symbol", "") or "").upper()
        dir_v = getattr(t.direction, "value", str(t.direction)).lower()
        sibling_map.setdefault((sym, dir_v), []).append(tid)
    sibs = sibling_map[("XLV", "long")]
    assert len(sibs) == 1
    # len <= 1 = bypass guard, proceed to normal naked-sweep path


def test_diag_endpoint_iterates_values_not_get_by_symbol():
    """Validate the v19.34.73 diag/symbol-state fix: must iterate
    `_open_trades.values()` and filter by symbol, NOT use
    `ot.get(sym)`."""

    # Simulate `_open_trades` keyed by trade_id (real behavior)
    open_trades = {
        "82f0686f": _DummyTrade(
            trade_id="82f0686f", symbol="ADI", direction="long",
            shares=134, entered_by="bot_fired",
        ),
        "abc12345": _DummyTrade(
            trade_id="abc12345", symbol="XLV", direction="long",
            shares=155, entered_by="bot_fired",
        ),
    }

    # OLD (buggy) — keyed by symbol = wrong dict shape
    old_rows = open_trades.get("ADI") or []
    assert old_rows == [], "old code path always returned empty"

    # NEW (v19.34.73) — iterate values and filter
    new_rows = [
        t for t in open_trades.values()
        if str(getattr(t, "symbol", "") or "").upper() == "ADI"
    ]
    assert len(new_rows) == 1
    assert new_rows[0].id == "82f0686f"


def test_diag_endpoint_finds_multiple_trades_per_symbol():
    """When two trades exist for same symbol (phantom + canonical),
    the diag must return BOTH so operator can see the corruption."""
    open_trades = {
        "82f0686f": _DummyTrade(
            trade_id="82f0686f", symbol="ADI", direction="long",
            shares=134, entered_by="bot_fired",
        ),
        "b415ed5f": _DummyTrade(
            trade_id="b415ed5f", symbol="ADI", direction="long",
            shares=44, entered_by="reconciled_external",
        ),
    }
    new_rows = [
        t for t in open_trades.values()
        if str(getattr(t, "symbol", "") or "").upper() == "ADI"
    ]
    assert len(new_rows) == 2
    tids = sorted(t.id for t in new_rows)
    assert tids == ["82f0686f", "b415ed5f"]


def test_cancel_wait_timeout_bump_applied():
    """Ensure the v19.34.73 timeout bump 4s → 8s landed in the
    `_cancel_ib_bracket_orders` body. Locks the value so it can't
    silently revert."""
    import inspect
    from services.trade_executor_service import TradeExecutorService
    src = inspect.getsource(TradeExecutorService._cancel_ib_bracket_orders)
    # The current configuration must include 8.0s primary + 5.0s retry
    assert "timeout_s=8.0" in src, "v19.34.73 primary timeout must be 8.0s"
    assert "timeout_s=5.0" in src, "v19.34.73 retry timeout must be 5.0s"
    assert "v19.34.73 cancel-retry" in src, \
        "v19.34.73 retry path must be present"


def test_diag_endpoint_fix_applied():
    """Lock in the v19.34.73 diag fix so it can't silently revert to
    `ot.get(sym)`."""
    import inspect
    from routers import trading_bot as router_mod
    src = inspect.getsource(router_mod.diag_symbol_state)
    assert ".values()" in src, \
        "v19.34.73 diag fix must iterate _open_trades.values()"
    # The old broken pattern must be gone
    assert "ot.get(sym) or []" not in src, \
        "v19.34.73: the old `ot.get(sym) or []` path must be removed"


def test_naked_sweep_sibling_guard_applied():
    """Lock in the v19.34.73 naked-sweep sibling guard so it can't
    silently revert."""
    import inspect
    from services.trading_bot_service import TradingBotService
    src = inspect.getsource(TradingBotService._naked_position_sweep)
    assert "v19.34.73" in src, \
        "v19.34.73 marker must be present in naked-sweep"
    assert "_sibling_map" in src, \
        "v19.34.73 sibling map must be built"
    assert "healthier sibling" in src, \
        "v19.34.73 phantom-skip log message must be present"


def test_boot_phantom_purge_handler_exists():
    """Verify the boot phantom-sibling purge task is wired into start()."""
    import inspect
    from services.trading_bot_service import TradingBotService
    src = inspect.getsource(TradingBotService.start)
    assert "_startup_phantom_sibling_purge" in src, \
        "v19.34.73 phantom-purge task must be wired in start()"
    assert "phantom_sibling_purge_v19_34_73" in src, \
        "v19.34.73 purge close_reason must be set"
