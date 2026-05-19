"""v19.34.40 — EOD direct-close hardening regression suite."""
import os, sys, types, unittest
from unittest.mock import AsyncMock, MagicMock, patch

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _make_trade(symbol="AAPL", direction="long", shares=100, remaining=None):
    t = MagicMock()
    t.symbol = symbol
    t.id = "T-TEST-1"
    t.direction = MagicMock()
    t.direction.value = direction
    t.shares = shares
    t.remaining_shares = remaining if remaining is not None else shares
    t.current_price = 150.0
    return t


class TestIBDirectPlaceCloseMarket(unittest.IsolatedAsyncioTestCase):
    async def test_returns_failure_when_not_connected(self):
        from services.ib_direct_service import get_ib_direct_service
        svc = get_ib_direct_service()
        with patch.object(svc, "ensure_connected", AsyncMock(return_value=False)):
            res = await svc.place_close_market(_make_trade())
        self.assertFalse(res["success"])
        self.assertIn("not_connected", res["error"])
        self.assertFalse(res.get("simulated", True))

    async def test_returns_failure_in_read_only_mode(self):
        from services.ib_direct_service import get_ib_direct_service
        svc = get_ib_direct_service()
        with patch.object(svc, "ensure_connected", AsyncMock(return_value=True)):
            original_ro = svc.config.read_only
            try:
                svc.config.read_only = True
                res = await svc.place_close_market(_make_trade())
            finally:
                svc.config.read_only = original_ro
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "ib_direct_read_only_mode")


class TestExecutorCloseHardFail(unittest.IsolatedAsyncioTestCase):
    async def test_hard_fail_when_pusher_offline_and_path_not_direct(self):
        from services.trade_executor_service import TradeExecutorService, ExecutorMode
        svc = TradeExecutorService.__new__(TradeExecutorService)
        svc._mode = ExecutorMode.LIVE
        svc._ensure_initialized = lambda: True
        svc._order_path_mode = lambda: "pusher"
        fake_ib = types.ModuleType("routers.ib")
        fake_ib.queue_order = MagicMock(return_value="O-1")
        fake_ib.get_order_result = MagicMock(return_value=None)
        fake_ib.is_pusher_connected = MagicMock(return_value=False)
        with patch.dict(sys.modules, {"routers.ib": fake_ib}):
            res = await svc._ib_close_position(_make_trade())
        self.assertFalse(res["success"])
        self.assertTrue(res.get("pusher_offline"))
        self.assertFalse(res.get("simulated", False))
        self.assertEqual(res["error"], "pusher_offline_cannot_close_in_live_mode")

    async def test_direct_path_routes_to_ib_direct(self):
        from services.trade_executor_service import TradeExecutorService, ExecutorMode
        svc = TradeExecutorService.__new__(TradeExecutorService)
        svc._mode = ExecutorMode.LIVE
        svc._ensure_initialized = lambda: True
        svc._order_path_mode = lambda: "direct"
        svc._cancel_ib_bracket_orders = AsyncMock()
        svc._maybe_schedule_shadow_observe = MagicMock()
        fake_direct = MagicMock()
        fake_direct.place_close_market = AsyncMock(return_value={
            "success": True, "order_id": 999, "fill_price": 150.42,
            "status": "filled", "filled_qty": 100, "broker": "ib_direct"})
        fake_mod = types.ModuleType("services.ib_direct_service")
        fake_mod.get_ib_direct_service = lambda: fake_direct
        fake_ib = types.ModuleType("routers.ib")
        fake_ib.queue_order = MagicMock()
        fake_ib.get_order_result = MagicMock()
        fake_ib.is_pusher_connected = MagicMock(return_value=True)
        with patch.dict(sys.modules, {"routers.ib": fake_ib, "services.ib_direct_service": fake_mod}):
            res = await svc._ib_close_position(_make_trade())
        self.assertTrue(res["success"])
        self.assertEqual(res["order_id"], 999)
        self.assertEqual(res["broker"], "ib_direct")
        fake_direct.place_close_market.assert_awaited_once()
        svc._cancel_ib_bracket_orders.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
