"""v19.34.43 -- Breakout entry (STP / STP_LMT) regression suite."""
import os, sys, unittest
from unittest.mock import AsyncMock, MagicMock

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _make_trade(symbol="AAPL", direction="long", shares=100,
                entry_price=10.00, setup_type="daily_breakout"):
    t = MagicMock()
    t.symbol = symbol
    t.id = "T-T-1"
    t.direction = MagicMock(); t.direction.value = direction
    t.shares = shares
    t.entry_price = entry_price
    t.setup_type = setup_type
    t.setup_variant = setup_type
    return t


class TestBreakoutOrderTypeMap(unittest.TestCase):
    def test_default_map(self):
        from services.trade_executor_service import _BREAKOUT_ENTRY_ORDER_TYPES
        self.assertEqual(_BREAKOUT_ENTRY_ORDER_TYPES.get("daily_breakout"), "STP")
        self.assertEqual(_BREAKOUT_ENTRY_ORDER_TYPES.get("orb_breakout"), "STP")
        self.assertEqual(_BREAKOUT_ENTRY_ORDER_TYPES.get("bouncy_ball"), "STP_LMT")
        self.assertEqual(_BREAKOUT_ENTRY_ORDER_TYPES.get("daily_squeeze"), "STP_LMT")

    def test_non_breakouts_excluded(self):
        from services.trade_executor_service import _BREAKOUT_ENTRY_ORDER_TYPES
        for s in ("accumulation_entry", "vwap_fade_long", "backside", "nine_ema_scalp"):
            self.assertNotIn(s, _BREAKOUT_ENTRY_ORDER_TYPES)


class TestPlaceEntryStopOrders(unittest.IsolatedAsyncioTestCase):
    async def _make_svc(self):
        from services.ib_direct_service import get_ib_direct_service
        svc = get_ib_direct_service()
        svc._min_tick_cache = {("AAPL", "USD"): 0.01}
        svc.ensure_connected = AsyncMock(return_value=True)
        svc.is_authorized_to_trade = MagicMock(return_value=True)
        svc.config.read_only = False
        captured = {}
        fake_ib = MagicMock()
        fake_ib.qualifyContractsAsync = AsyncMock()
        def _place(contract, order):
            captured["order"] = order
            tr = MagicMock(); tr.order = order; tr.order.orderId = 555
            st = MagicMock(); st.status = "Submitted"; st.filled = 0; st.avgFillPrice = 0.0
            tr.orderStatus = st
            return tr
        fake_ib.placeOrder = _place
        svc._ib = fake_ib
        return svc, captured

    async def test_stp_uses_StopOrder(self):
        from ib_async import StopOrder
        svc, cap = await self._make_svc()
        await svc.place_entry(_make_trade(), order_type="STP",
                              stop_price=10.00, wait_for_fill_s=0.5)
        self.assertIsInstance(cap["order"], StopOrder)
        self.assertEqual(cap["order"].action, "BUY")
        self.assertEqual(cap["order"].auxPrice, 10.00)

    async def test_stp_lmt_uses_StopLimitOrder(self):
        from ib_async import StopLimitOrder
        svc, cap = await self._make_svc()
        await svc.place_entry(_make_trade(setup_type="bouncy_ball"),
                              order_type="STP_LMT", stop_price=10.00,
                              limit_price=10.05, wait_for_fill_s=0.5)
        self.assertIsInstance(cap["order"], StopLimitOrder)
        self.assertEqual(cap["order"].auxPrice, 10.00)
        self.assertEqual(cap["order"].lmtPrice, 10.05)

    async def test_stp_no_stop_price_fails(self):
        svc, _ = await self._make_svc()
        res = await svc.place_entry(_make_trade(), order_type="STP",
                                    wait_for_fill_s=0.1)
        self.assertFalse(res["success"])
        self.assertIn("stop_price required", res["error"])

    async def test_stp_lmt_no_limit_price_fails(self):
        svc, _ = await self._make_svc()
        res = await svc.place_entry(_make_trade(), order_type="STP_LMT",
                                    stop_price=10.00, wait_for_fill_s=0.1)
        self.assertFalse(res["success"])
        self.assertIn("limit_price required", res["error"])

    async def test_legacy_lmt_unchanged(self):
        from ib_async import LimitOrder
        svc, cap = await self._make_svc()
        await svc.place_entry(_make_trade(), order_type="LMT",
                              limit_price=10.05, wait_for_fill_s=0.1)
        self.assertIsInstance(cap["order"], LimitOrder)
        self.assertEqual(cap["order"].lmtPrice, 10.05)

    async def test_short_breakdown_uses_SELL(self):
        from ib_async import StopOrder
        svc, cap = await self._make_svc()
        await svc.place_entry(_make_trade(direction="short"), order_type="STP",
                              stop_price=10.00, wait_for_fill_s=0.1)
        self.assertIsInstance(cap["order"], StopOrder)
        self.assertEqual(cap["order"].action, "SELL")

    async def test_min_tick_rounding_on_stop_price(self):
        svc, cap = await self._make_svc()
        await svc.place_entry(_make_trade(), order_type="STP",
                              stop_price=10.0067, wait_for_fill_s=0.1)
        # 10.0067 -> 10.01 with $0.01 minTick (v19.34.42)
        self.assertEqual(cap["order"].auxPrice, 10.01)


if __name__ == "__main__":
    unittest.main()
