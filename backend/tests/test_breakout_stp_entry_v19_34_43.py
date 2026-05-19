"""v19.34.43 -- Breakout entry order-type (STP / STP_LMT) regression suite."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _make_trade(symbol="AAPL", direction="long", shares=100,
                entry_price=10.00, setup_type="daily_breakout", setup_variant=None):
    t = MagicMock()
    t.symbol = symbol
    t.id = "T-T-1"
    t.direction = MagicMock(); t.direction.value = direction
    t.shares = shares
    t.entry_price = entry_price
    t.setup_type = setup_type
    t.setup_variant = setup_variant or setup_type
    return t


class TestBreakoutOrderTypeMap(unittest.TestCase):
    def test_default_map_has_known_breakouts(self):
        from services.trade_executor_service import _BREAKOUT_ENTRY_ORDER_TYPES
        self.assertEqual(_BREAKOUT_ENTRY_ORDER_TYPES.get("daily_breakout"), "STP")
        self.assertEqual(_BREAKOUT_ENTRY_ORDER_TYPES.get("orb_breakout"), "STP")
        self.assertEqual(_BREAKOUT_ENTRY_ORDER_TYPES.get("bouncy_ball"), "STP_LMT")
        self.assertEqual(_BREAKOUT_ENTRY_ORDER_TYPES.get("daily_squeeze"), "STP_LMT")

    def test_non_breakouts_fall_through_to_lmt(self):
        from services.trade_executor_service import _BREAKOUT_ENTRY_ORDER_TYPES
        # These should NOT be in the breakout map (so they use LMT).
        for setup in ("accumulation_entry", "vwap_fade_long",
                      "vwap_fade_short", "backside", "nine_ema_scalp"):
            self.assertNotIn(setup, _BREAKOUT_ENTRY_ORDER_TYPES)


class TestPlaceEntryStopOrders(unittest.IsolatedAsyncioTestCase):
    async def _make_svc(self):
        from services.ib_direct_service import get_ib_direct_service
        svc = get_ib_direct_service()
        svc._min_tick_cache = {("AAPL", "USD"): 0.01}
        # Stub IB
        svc.ensure_connected = AsyncMock(return_value=True)
        svc.is_authorized_to_trade = MagicMock(return_value=True)
        svc.config.read_only = False
        # Capture the order that gets placed
        captured = {}
        fake_ib = MagicMock()
        fake_ib.qualifyContractsAsync = AsyncMock()
        def _place(contract, order):
            captured["contract"] = contract
            captured["order"] = order
            ib_trade = MagicMock()
            ib_trade.order = order
            ib_trade.order.orderId = 555
            status = MagicMock()
            status.status = "Submitted"
            status.filled = 0
            status.avgFillPrice = 0.0
            ib_trade.orderStatus = status
            return ib_trade
        fake_ib.placeOrder = _place
        svc._ib = fake_ib
        return svc, captured

    async def test_stp_entry_uses_StopOrder(self):
        from ib_async import StopOrder
        svc, captured = await self._make_svc()
        trade = _make_trade(entry_price=10.00, setup_type="daily_breakout")
        await svc.place_entry(trade, order_type="STP", stop_price=10.00,
                              wait_for_fill_s=0.6)
        self.assertIsInstance(captured["order"], StopOrder)
        self.assertEqual(captured["order"].action, "BUY")
        self.assertEqual(captured["order"].auxPrice, 10.00)
        self.assertEqual(captured["order"].totalQuantity, 100)

    async def test_stp_lmt_entry_uses_StopLimitOrder(self):
        from ib_async import StopLimitOrder
        svc, captured = await self._make_svc()
        trade = _make_trade(entry_price=10.00, setup_type="bouncy_ball")
        await svc.place_entry(trade, order_type="STP_LMT",
                              stop_price=10.00, limit_price=10.05,
                              wait_for_fill_s=0.6)
        self.assertIsInstance(captured["order"], StopLimitOrder)
        self.assertEqual(captured["order"].action, "BUY")
        self.assertEqual(captured["order"].auxPrice, 10.00)   # stop trigger
        self.assertEqual(captured["order"].lmtPrice, 10.05)    # limit cap

    async def test_stp_without_stop_price_fails(self):
        svc, _ = await self._make_svc()
        trade = _make_trade()
        res = await svc.place_entry(trade, order_type="STP", wait_for_fill_s=0.1)
        self.assertFalse(res["success"])
        self.assertIn("stop_price required", res["error"])

    async def test_stp_lmt_without_limit_price_fails(self):
        svc, _ = await self._make_svc()
        trade = _make_trade()
        res = await svc.place_entry(trade, order_type="STP_LMT",
                                    stop_price=10.00, wait_for_fill_s=0.1)
        self.assertFalse(res["success"])
        self.assertIn("limit_price required", res["error"])

    async def test_lmt_path_unchanged(self):
        """Regression: legacy LMT path still works as before."""
        from ib_async import LimitOrder
        svc, captured = await self._make_svc()
        trade = _make_trade()
        await svc.place_entry(trade, order_type="LMT", limit_price=10.05,
                              wait_for_fill_s=0.1)
        self.assertIsInstance(captured["order"], LimitOrder)
        self.assertEqual(captured["order"].lmtPrice, 10.05)

    async def test_short_breakout_stp(self):
        """SELL STP (short breakdown) uses SELL action and stop trigger."""
        from ib_async import StopOrder
        svc, captured = await self._make_svc()
        trade = _make_trade(direction="short", entry_price=10.00,
                            setup_type="daily_breakout")
        await svc.place_entry(trade, order_type="STP", stop_price=10.00,
                              wait_for_fill_s=0.1)
        self.assertIsInstance(captured["order"], StopOrder)
        self.assertEqual(captured["order"].action, "SELL")

    async def test_min_tick_rounding_applied_to_stop_price(self):
        """v19.34.42 minTick rounding applies to STP entries too."""
        from ib_async import StopOrder
        svc, captured = await self._make_svc()
        trade = _make_trade(entry_price=10.0067)
        await svc.place_entry(trade, order_type="STP", stop_price=10.0067,
                              wait_for_fill_s=0.1)
        # minTick=0.01 → 10.0067 rounds to 10.01
        self.assertEqual(captured["order"].auxPrice, 10.01)


if __name__ == "__main__":
    unittest.main()
