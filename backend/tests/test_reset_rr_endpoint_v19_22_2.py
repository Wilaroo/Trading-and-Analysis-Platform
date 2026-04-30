"""
v19.22.2 — Reset-RR endpoint must AWAIT the Mongo save before returning.

The v19.21 reset endpoint fired-and-forgot the persistence write via
`asyncio.create_task(_save_state())`. Operator caught it 2026-05-01:
calling /reset-rr-defaults set the in-memory state to 1.7, but the next
backend restart (to deploy unrelated changes) reloaded the OLD 2.5 from
Mongo because the create_task() never finished before the response
returned. v19.22.2 makes the handler `async def` and awaits the save
so it's guaranteed durable through restarts.
"""
import os
import sys
import inspect
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_reset_rr_endpoint_is_async():
    """v19.22.2 promotes the handler to `async def` so it can await the
    Mongo persistence call. Pre-fix it was a sync def with create_task."""
    from routers.trading_bot import reset_rr_defaults
    assert inspect.iscoroutinefunction(reset_rr_defaults), (
        "reset_rr_defaults must be `async def` so the Mongo save can "
        "be awaited (v19.22.2). Sync version had a fire-and-forget bug."
    )


@pytest.mark.asyncio
async def test_reset_rr_endpoint_awaits_save_and_reports_persisted_flag():
    """The handler must call _save_state() (awaited) and return a
    `persisted_to_mongo` bool so the operator can verify the write hit
    Mongo before the response returned."""
    from routers import trading_bot as tb
    import asyncio

    save_calls = []

    class _FakeBot:
        class _RP:
            min_risk_reward = 9.9
            setup_min_rr = {}
            max_risk_per_trade = 0
            max_daily_loss = 0
            starting_capital = 0
            max_position_pct = 0
            max_open_positions = 0
            max_notional_per_trade = 0
        risk_params = _RP()

        async def _save_state(self):
            save_calls.append("save")

        def get_status(self):
            return {"risk_params": {
                "min_risk_reward": self.risk_params.min_risk_reward,
                "setup_min_rr": dict(self.risk_params.setup_min_rr),
                "max_risk_per_trade": self.risk_params.max_risk_per_trade,
                "max_daily_loss": self.risk_params.max_daily_loss,
                "starting_capital": self.risk_params.starting_capital,
                "max_position_pct": self.risk_params.max_position_pct,
                "max_open_positions": self.risk_params.max_open_positions,
                "max_notional_per_trade": self.risk_params.max_notional_per_trade,
            }}

    fake = _FakeBot()
    tb._trading_bot = fake
    try:
        result = await tb.reset_rr_defaults()
        assert result["success"] is True
        assert result["persisted_to_mongo"] is True
        # In-memory state was reset
        assert fake.risk_params.min_risk_reward == 1.7
        assert fake.risk_params.setup_min_rr["gap_fade"] == 1.5
        # _save_state was actually called (not fire-and-forget)
        assert save_calls == ["save"]
    finally:
        tb._trading_bot = None


@pytest.mark.asyncio
async def test_reset_rr_endpoint_survives_save_failure():
    """If Mongo write fails for any reason, the endpoint should still
    succeed (in-memory state IS reset) but report `persisted_to_mongo: False`
    so the operator can decide whether to retry."""
    from routers import trading_bot as tb

    class _FakeBot:
        class _RP:
            min_risk_reward = 9.9
            setup_min_rr = {}
            max_risk_per_trade = 0
            max_daily_loss = 0
            starting_capital = 0
            max_position_pct = 0
            max_open_positions = 0
            max_notional_per_trade = 0
        risk_params = _RP()

        async def _save_state(self):
            raise RuntimeError("mongo unavailable")

        def get_status(self):
            return {"risk_params": {
                "min_risk_reward": self.risk_params.min_risk_reward,
                "setup_min_rr": dict(self.risk_params.setup_min_rr),
                "max_risk_per_trade": 0, "max_daily_loss": 0,
                "starting_capital": 0, "max_position_pct": 0,
                "max_open_positions": 0, "max_notional_per_trade": 0,
            }}

    fake = _FakeBot()
    tb._trading_bot = fake
    try:
        result = await tb.reset_rr_defaults()
        assert result["success"] is True
        assert result["persisted_to_mongo"] is False
        # In-memory still got reset (operator can retry, periodic save will pick it up)
        assert fake.risk_params.min_risk_reward == 1.7
    finally:
        tb._trading_bot = None
