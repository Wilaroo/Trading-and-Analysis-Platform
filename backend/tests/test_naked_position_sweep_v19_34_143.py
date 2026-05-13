"""v19.34.143 — Naked-sweep upgrades: simulated stop IDs + emergency
hard %-stop fallback.

Bug from the 2026-02-13 handoff: TE / EGO / KTOS were sitting on the
operator's screen with NO bracket protection. Two ways this happens
post-reconcile:

  1. `attach_oca_stop_target` ran while the IB pusher was offline →
     returned `SIM-STP-{trade.id}` simulated IDs. The bracket was
     never actually placed at IB, but the bot looks bracketed.
     Pre-v19.34.143 the naked sweep matched `SIM-STP-*` against the
     live-order set (empty match → NAKED detected) but downstream
     `attach_oca_stop_target` happily returns SIM IDs AGAIN because
     pusher is still offline. We need the sweep to BOTH detect the
     simulation AND clear the stale ID so the lifecycle event is
     accurate.

  2. The trade's `stop_price` / `target_prices` got nuked somewhere
     up the chain. `attach_oca_stop_target` bails with
     "missing stop_price or target_price" and the trade stays NAKED
     forever. v19.34.143 synthesizes an emergency 2% hard stop / 3%
     target off entry so the attach call has valid prices to work
     with.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_trade(*, tid, symbol, shares, stop_order_id, entry_price=100.0,
                stop_price=None, target_prices=None, direction="long"):
    t = MagicMock()
    t.id = tid
    t.symbol = symbol
    t.remaining_shares = shares
    t.shares = shares
    t.stop_order_id = stop_order_id
    t.target_order_id = None
    t.target_order_ids = []
    t.oca_group = None
    t.fill_price = entry_price
    t.entry_price = entry_price
    t.stop_price = stop_price
    t.target_prices = list(target_prices) if target_prices else None
    direction_mock = MagicMock()
    direction_mock.value = direction
    t.direction = direction_mock
    return t


def _make_bot(*, executor, open_trades):
    from services.trading_bot_service import TradingBotService
    bot = TradingBotService.__new__(TradingBotService)
    bot._trade_executor = executor
    bot._open_trades = open_trades
    bot._db = None
    bot._save_trade = MagicMock(return_value=None)
    return bot


def _make_executor(*, mode="LIVE", oca_result=None):
    executor = MagicMock()
    executor.mode = mode
    if oca_result is not None:
        executor.attach_oca_stop_target = AsyncMock(return_value=oca_result)
    return executor


def _patch_fetch(ib_orders, source_tier="pusher_orders_snapshot"):
    return patch(
        "services.orphan_gtc_reconciler._fetch_ib_open_orders",
        new_callable=AsyncMock,
        return_value=(ib_orders, {"tier": source_tier, "ok": True}),
    )


# ────────────────────────────────────────────────────────────────────
# 1. Simulated stop_id (SIM-STP-*) must be treated as NAKED even when
#    the live-order set is empty (pusher offline cascade).
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sim_stp_prefix_treated_as_naked():
    """A `SIM-STP-*` id means the prior attach ran with the pusher
    offline — the bracket was never actually placed at IB."""
    executor = _make_executor(oca_result={
        "success": True, "stop_order_id": "STP-REAL-99",
        "target_order_id": "TGT-REAL-99", "oca_group": "OCA-REAL-99",
    })
    trade = _make_trade(
        tid="t-te", symbol="TE", shares=7204,
        stop_order_id="SIM-STP-t-te", stop_price=5.10,
        target_prices=[5.70], direction="short",
    )
    bot = _make_bot(executor=executor, open_trades={"t-te": trade})

    with _patch_fetch([]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        result = await bot._naked_position_sweep()

    assert result["checked"] == 1
    assert result["naked_found"] == 1
    assert result["reissued"] == 1
    # The new real stop ID overwrote the simulated one.
    assert trade.stop_order_id == "STP-REAL-99"


@pytest.mark.asyncio
async def test_adopt_stop_prefix_treated_as_naked():
    """`ADOPT-STOP-{id}` is the marker emitted by attach_oca_stop_target
    when the pusher returned a simulated id during orphan-adopt."""
    executor = _make_executor(oca_result={
        "success": True, "stop_order_id": "STP-REAL", "oca_group": "OCA-REAL",
    })
    trade = _make_trade(
        tid="t-ego", symbol="EGO", shares=2046,
        stop_order_id="ADOPT-STOP-t-ego", stop_price=35.20,
        target_prices=[36.50], direction="short",
    )
    bot = _make_bot(executor=executor, open_trades={"t-ego": trade})

    with _patch_fetch([]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        result = await bot._naked_position_sweep()

    assert result["naked_found"] == 1
    assert result["reissued"] == 1


@pytest.mark.asyncio
async def test_real_stop_id_in_live_orders_not_flagged_naked():
    """Sanity: a real IB stop id that's in the live snapshot must NOT
    be treated as naked just because v19.34.143 widened the check."""
    executor = _make_executor()
    executor.attach_oca_stop_target = AsyncMock()
    trade = _make_trade(
        tid="t-aapl", symbol="AAPL", shares=100,
        stop_order_id="12345", entry_price=200.0,
        stop_price=196.0, target_prices=[206.0], direction="long",
    )
    bot = _make_bot(executor=executor, open_trades={"t-aapl": trade})

    with _patch_fetch([{"ib_order_id": "12345", "symbol": "AAPL"}]):
        result = await bot._naked_position_sweep()

    assert result["checked"] == 1
    assert result["naked_found"] == 0
    executor.attach_oca_stop_target.assert_not_awaited()


# ────────────────────────────────────────────────────────────────────
# 2. Emergency hard %-stop fallback when stop_price/target nuked.
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_stop_price_synthesizes_emergency_stop_long():
    """LONG trade with stop_price=None — sweep must synthesize a 2%
    hard stop ($98 on a $100 entry) BEFORE calling attach so the
    attach can succeed."""
    executor = _make_executor(oca_result={
        "success": True, "stop_order_id": "STP-EMRG",
        "target_order_id": "TGT-EMRG", "oca_group": "OCA-EMRG",
    })
    trade = _make_trade(
        tid="t-naked", symbol="TE", shares=100,
        stop_order_id=None, entry_price=100.0,
        stop_price=None, target_prices=None, direction="long",
    )
    bot = _make_bot(executor=executor, open_trades={"t-naked": trade})

    with _patch_fetch([]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        result = await bot._naked_position_sweep()

    assert result["naked_found"] == 1
    assert result["reissued"] == 1
    # 2% below 100 = 98.00.
    assert trade.stop_price == pytest.approx(98.0, abs=0.01)
    # 1.5R target: stop_distance=2 → target_distance=3 → entry+3 = 103.
    assert trade.target_prices == [pytest.approx(103.0, abs=0.01)]


@pytest.mark.asyncio
async def test_missing_stop_price_synthesizes_emergency_stop_short():
    """SHORT trade with stop_price=0 — emergency stop goes ABOVE entry."""
    executor = _make_executor(oca_result={
        "success": True, "stop_order_id": "STP-EMRG", "oca_group": "OCA-EMRG",
    })
    trade = _make_trade(
        tid="t-short", symbol="TE", shares=200,
        stop_order_id=None, entry_price=50.0,
        stop_price=0, target_prices=[], direction="short",
    )
    bot = _make_bot(executor=executor, open_trades={"t-short": trade})

    with _patch_fetch([]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        result = await bot._naked_position_sweep()

    assert result["reissued"] == 1
    # 2% above 50 = 51.00.
    assert trade.stop_price == pytest.approx(51.0, abs=0.01)
    # target: 50 - 1.5 = 48.50.
    assert trade.target_prices == [pytest.approx(48.5, abs=0.01)]


@pytest.mark.asyncio
async def test_valid_stop_price_not_overwritten():
    """If the trade already has a valid stop_price/target, the sweep
    must NOT overwrite them with the synthetic emergency numbers."""
    executor = _make_executor(oca_result={
        "success": True, "stop_order_id": "STP-NEW", "oca_group": "OCA-NEW",
    })
    trade = _make_trade(
        tid="t-keep", symbol="MSFT", shares=50,
        stop_order_id=None, entry_price=400.0,
        stop_price=395.5, target_prices=[410.0], direction="long",
    )
    bot = _make_bot(executor=executor, open_trades={"t-keep": trade})

    with _patch_fetch([]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        await bot._naked_position_sweep()

    # Original stop/target preserved — not clobbered by emergency synth.
    assert trade.stop_price == 395.5
    assert trade.target_prices == [410.0]


@pytest.mark.asyncio
async def test_missing_entry_skips_emergency_synth_but_still_attaches():
    """If entry/fill price is zero, we can't synthesize. The sweep
    must still try the attach (which will fail) and not crash."""
    executor = _make_executor(oca_result={
        "success": False, "error": "missing stop_price or target_price",
    })
    trade = _make_trade(
        tid="t-noentry", symbol="??", shares=10,
        stop_order_id=None, entry_price=0,
        stop_price=None, target_prices=None, direction="long",
    )
    bot = _make_bot(executor=executor, open_trades={"t-noentry": trade})

    with _patch_fetch([]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        result = await bot._naked_position_sweep()

    assert result["naked_found"] == 1
    assert result["reissued"] == 0
    assert result["reissue_failed"] == 1
    # Did not synthesize (entry was 0).
    assert trade.stop_price is None
