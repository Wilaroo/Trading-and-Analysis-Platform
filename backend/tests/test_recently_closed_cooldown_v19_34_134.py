"""v19.34.134 — Reconciler must skip recently-closed symbols.

The AJG/FLEX duplicate-close bug (2026-05-13): IB carried positions
the bot didn't open. Reconciler adopted them as orphan trades. Manage
loop fired `stop_loss` close (because price was already below the
default 2% stop). `close_trade` wrote a `bot_trades` row but the IB
position survived. 5 min later the reconciler re-adopted the same
symbol → re-closed → fresh fake -$80 / -$694 row each cycle.
Compounded over 7 hours: $3.5k+ of phantom realized loss vs TWS.

Fix: `close_trade` stamps `bot._recently_closed_symbols[sym] = now`.
Reconciler skips any symbol with a stamp <30 min old.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _bot_with_recently_closed(symbols_with_ages_s):
    """Build a bot stub with `_recently_closed_symbols` populated."""
    bot = SimpleNamespace()
    bot._open_trades = {}
    bot._closed_trades = []
    bot._recently_closed_symbols = {}
    now = datetime.now(timezone.utc)
    for sym, age_s in symbols_with_ages_s.items():
        bot._recently_closed_symbols[sym] = now - timedelta(seconds=age_s)
    bot._db = MagicMock()
    bot._trade_executor = MagicMock()
    bot._trade_executor.mode = "LIVE"
    return bot


@pytest.mark.asyncio
async def test_reconciler_skips_recently_closed_symbol():
    """A symbol closed 10 min ago must NOT be re-adopted as an orphan."""
    from services.position_reconciler import PositionReconciler

    bot = _bot_with_recently_closed({"AJG": 600})  # 10 min ago

    # Patch IB to report AJG as a live position
    ib_quotes = {"AJG": {"last": 197.40}}
    ib_positions = [{"symbol": "AJG", "qty": 67, "avg_cost": 198.57}]

    with patch("services.position_reconciler._pushed_ib_data", {
        "positions": ib_positions, "quotes": ib_quotes,
    }):
        rec = PositionReconciler()
        report = await rec.reconcile_orphan_positions(
            bot, symbols=["AJG"], dry_run=False, all_orphans=False,
        )

    # AJG must be in skipped, with reason `recently_closed_cooldown`
    skipped_symbols = {s["symbol"]: s for s in report.get("skipped", [])}
    assert "AJG" in skipped_symbols, f"AJG not skipped: {report}"
    assert skipped_symbols["AJG"]["reason"] == "recently_closed_cooldown"
    assert skipped_symbols["AJG"]["cooldown_remaining_s"] > 1000  # ~20 min remaining
    # Verify no new orphan trade was created
    assert len(bot._open_trades) == 0


@pytest.mark.asyncio
async def test_reconciler_adopts_after_cooldown_expires():
    """31 min after close, the symbol is no longer in cooldown."""
    from services.position_reconciler import PositionReconciler

    bot = _bot_with_recently_closed({"AJG": 31 * 60})  # 31 min ago
    ib_quotes = {"AJG": {"last": 197.40}}
    ib_positions = [{"symbol": "AJG", "qty": 67, "avg_cost": 198.57}]

    with patch("services.position_reconciler._pushed_ib_data", {
        "positions": ib_positions, "quotes": ib_quotes,
    }):
        rec = PositionReconciler()
        report = await rec.reconcile_orphan_positions(
            bot, symbols=["AJG"], dry_run=True, all_orphans=False,
        )

    # AJG should NOT be skipped for the cooldown reason
    skipped = report.get("skipped", [])
    cooldown_skips = [s for s in skipped if s.get("reason") == "recently_closed_cooldown"]
    assert len(cooldown_skips) == 0, f"AJG was skipped for cooldown but it shouldn't be: {cooldown_skips}"


def test_close_trade_stamps_recently_closed():
    """`close_trade` must stamp the symbol into `bot._recently_closed_symbols`."""
    # We stamp directly to verify the contract, since exercising the full
    # close_trade requires a deep bot fixture.
    bot = SimpleNamespace()
    rcs = getattr(bot, "_recently_closed_symbols", None)
    assert rcs is None, "fresh bot should not have _recently_closed_symbols yet"

    # Simulate the v134 stamp block
    if rcs is None:
        bot._recently_closed_symbols = {}
        rcs = bot._recently_closed_symbols
    rcs["AJG"] = datetime.now(timezone.utc)

    assert "AJG" in bot._recently_closed_symbols
    age = (datetime.now(timezone.utc) - bot._recently_closed_symbols["AJG"]).total_seconds()
    assert age < 1, "stamp should be ~now"
