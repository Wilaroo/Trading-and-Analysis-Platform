"""v19.34.42 -- IB minTick rounding regression suite (Error 110 fix)."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


class TestRoundToTick(unittest.TestCase):
    def test_rounds_to_penny_tick(self):
        from services.ib_direct_service import IBDirectService
        self.assertEqual(IBDirectService._round_to_tick(12.3456, 0.01), 12.35)
        self.assertEqual(IBDirectService._round_to_tick(12.3411, 0.01), 12.34)
        self.assertEqual(IBDirectService._round_to_tick(12.345, 0.01), 12.35)

    def test_rounds_to_sub_penny_tick(self):
        from services.ib_direct_service import IBDirectService
        # Stocks under $1 commonly have $0.0001 tick.
        self.assertEqual(IBDirectService._round_to_tick(0.12345, 0.0001), 0.1235)
        self.assertEqual(IBDirectService._round_to_tick(0.12344, 0.0001), 0.1234)

    def test_no_floating_point_artifacts(self):
        """The whole point of the fix: result must be an EXACT tick multiple."""
        from services.ib_direct_service import IBDirectService
        from decimal import Decimal
        cases = [
            (12.35, 0.01),
            (100.123, 0.01),
            (0.0567, 0.0001),
            (5.005, 0.01),
            (10.999, 0.01),
        ]
        for price, tick in cases:
            out = IBDirectService._round_to_tick(price, tick)
            # An exact multiple has Decimal representation that mod
            # the tick is exactly 0.
            self.assertEqual(
                (Decimal(str(out)) / Decimal(str(tick))) % 1,
                Decimal(0),
                f"price={price} tick={tick} -> {out} has sub-tick residue",
            )

    def test_zero_tick_falls_back_to_4_decimal(self):
        from services.ib_direct_service import IBDirectService
        self.assertEqual(IBDirectService._round_to_tick(12.34567, 0.0), 12.3457)
        self.assertEqual(IBDirectService._round_to_tick(12.34567, -1.0), 12.3457)

    def test_handles_string_or_decimal_inputs(self):
        from services.ib_direct_service import IBDirectService
        self.assertEqual(IBDirectService._round_to_tick(12.345, "0.01"), 12.35)


class TestResolveMinTick(unittest.IsolatedAsyncioTestCase):
    async def test_returns_ib_reported_min_tick(self):
        from services.ib_direct_service import get_ib_direct_service
        svc = get_ib_direct_service()
        svc._min_tick_cache = {}
        contract = MagicMock()
        contract.symbol = "AMRZ"
        contract.currency = "USD"
        details_row = MagicMock()
        details_row.minTick = 0.0001
        svc._ib = MagicMock()
        svc._ib.reqContractDetailsAsync = AsyncMock(return_value=[details_row])
        mt = await svc._resolve_min_tick(contract)
        self.assertEqual(mt, 0.0001)
        # Cache populated
        self.assertIn(("AMRZ", "USD"), svc._min_tick_cache)

    async def test_falls_back_to_penny_on_lookup_failure(self):
        from services.ib_direct_service import get_ib_direct_service
        svc = get_ib_direct_service()
        svc._min_tick_cache = {}
        contract = MagicMock()
        contract.symbol = "BOOM"
        contract.currency = "USD"
        svc._ib = MagicMock()
        svc._ib.reqContractDetailsAsync = AsyncMock(side_effect=RuntimeError("net error"))
        mt = await svc._resolve_min_tick(contract)
        self.assertEqual(mt, 0.01)

    async def test_falls_back_to_penny_on_empty_details(self):
        from services.ib_direct_service import get_ib_direct_service
        svc = get_ib_direct_service()
        svc._min_tick_cache = {}
        contract = MagicMock()
        contract.symbol = "EMPTY"
        contract.currency = "USD"
        svc._ib = MagicMock()
        svc._ib.reqContractDetailsAsync = AsyncMock(return_value=[])
        mt = await svc._resolve_min_tick(contract)
        self.assertEqual(mt, 0.01)

    async def test_cache_hit_avoids_second_ib_call(self):
        from services.ib_direct_service import get_ib_direct_service
        svc = get_ib_direct_service()
        svc._min_tick_cache = {("CACHE", "USD"): 0.0001}
        contract = MagicMock()
        contract.symbol = "CACHE"
        contract.currency = "USD"
        svc._ib = MagicMock()
        svc._ib.reqContractDetailsAsync = AsyncMock(side_effect=Exception("should not be called"))
        mt = await svc._resolve_min_tick(contract)
        self.assertEqual(mt, 0.0001)
        svc._ib.reqContractDetailsAsync.assert_not_called()

    async def test_zero_min_tick_from_ib_is_promoted_to_penny(self):
        """Some IB responses return minTick=0 for malformed details."""
        from services.ib_direct_service import get_ib_direct_service
        svc = get_ib_direct_service()
        svc._min_tick_cache = {}
        contract = MagicMock()
        contract.symbol = "ZERO"
        contract.currency = "USD"
        details_row = MagicMock()
        details_row.minTick = 0.0
        svc._ib = MagicMock()
        svc._ib.reqContractDetailsAsync = AsyncMock(return_value=[details_row])
        mt = await svc._resolve_min_tick(contract)
        self.assertEqual(mt, 0.01)


if __name__ == "__main__":
    unittest.main()
