"""P5c: PositionManager.trim_position bookkeeping + internal-stop tighten.

Verifies the REAL trim path (with a fake executor): correct shares decrement
(keeps a runner), realized_pnl update, partial_exits record, and that the
bot-side ratchet stop is tightened toward price without crossing it.
"""
import os
import asyncio

os.environ["THESIS_INVALIDATION_TRIM_TIGHTEN"] = "true"
os.environ["THESIS_INVALIDATION_TRIM_TIGHTEN_FRAC"] = "0.5"

from services.position_manager import PositionManager
from services.trading_bot_service import TradeDirection


class _FakeExec:
    async def execute_partial_exit(self, trade, shares):
        return {"success": True, "fill_price": trade.current_price, "shares": shares}


class _FakeBot:
    def __init__(self):
        self._trade_executor = _FakeExec()

    def _apply_commission(self, trade, shares):
        return 0.0


class _FakeTrade:
    def __init__(self):
        self.id = "p5c_trade"
        self.symbol = "TESTX"
        self.direction = TradeDirection.LONG
        self.fill_price = 100.0
        self.current_price = 106.0          # +6 in profit
        self.stop_price = 98.0
        self.remaining_shares = 100
        self.realized_pnl = 0.0
        self.scale_out_config = {}
        self.trailing_stop_config = {"current_stop": 98.0, "mode": "original"}


async def main():
    pm = PositionManager()
    bot = _FakeBot()
    t = _FakeTrade()

    res = await pm.trim_position(t, 0.5, bot, reason="thesis_invalidation:regime_hostile_cell")
    print("TRIM:", res)
    assert res["success"] is True, res
    # 0.5 * 100 = 50 trimmed, runner = 50
    assert res["shares_trimmed"] == 50, res
    assert t.remaining_shares == 50, t.remaining_shares
    # P&L on the trimmed 50 sh: (106 - 100) * 50 = 300
    assert abs(t.realized_pnl - 300.0) < 1e-6, t.realized_pnl
    assert t.scale_out_config.get("partial_exits"), "must record the partial"
    assert t.scale_out_config["partial_exits"][0]["target_idx"] == "thesis_trim"
    # stop tightened toward price: from 98 toward 106 by 0.5 -> 102, capped < 106*(1-0.003)
    new_stop = t.trailing_stop_config["current_stop"]
    print("new_stop:", new_stop)
    assert 98.0 < new_stop < t.current_price, new_stop
    assert abs(new_stop - 102.0) < 0.5, new_stop

    # Runner with only 1 share -> cannot trim (keep a runner)
    t2 = _FakeTrade()
    t2.remaining_shares = 1
    res2 = await pm.trim_position(t2, 0.5, bot, reason="x")
    assert res2["success"] is False and res2["shares_trimmed"] == 0, res2
    print("RUNNER-GUARD OK — P5c TRIM BOOKKEEPING PASS")


if __name__ == "__main__":
    asyncio.run(main())
