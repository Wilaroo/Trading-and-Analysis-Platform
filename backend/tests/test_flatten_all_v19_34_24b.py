"""
test_flatten_all_v19_34_24b.py — pins two latent bugs in
`/api/safety/flatten-all` that caused EVERY click to silently no-op.

Bug class:
  (a) Import name was wrong: `from services.trading_bot_service import
      get_trading_bot` — the actual exported accessor is named
      `get_trading_bot_service` (server.py:469). The wrong name raised
      ImportError immediately, swallowed by the broad except into the
      response's `close_errors` field as a JSON string, leaving the
      operator looking at `success: True` + `positions_requested_close: 0`
      with no actionable signal that flatten-all hadn't actually run.
  (b) Trade-id key was `trade_id`, not `id`. The BotTrade dataclass
      (services/trading_bot_service.py:586) defines `id: str` and
      `bot._open_trades` is `Dict[str, BotTrade]` keyed by `id`. The
      pre-fix `getattr(t, "trade_id", None)` always returned None, so
      every position would have bailed on `if not trade_id: continue`
      even if (a) hadn't crashed first.

Operator-discovered 2026-02-XX after attempted flatten of 17 positions:
log showed `positions_requested_close: 0` and `close_errors: [{stage:
"close-positions", err: "cannot import name 'get_trading_bot' from
'services.trading_bot_service'"}]`. Zero close orders left the backend.

Tests below cover:
  - flatten-all calls the correct singleton accessor
    (`get_trading_bot_service`) and processes every open trade.
  - Each `BotTrade.id` is correctly extracted and passed to
    `bot.close_trade`.
  - Successful closes increment `positions_succeeded`.
  - `bot.close_trade` returning False or raising is recorded in
    `close_errors` without aborting the loop.
  - Confirm guard (`?confirm=FLATTEN`) still required.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_bot_with_open_trades(*trade_ids):
    """Build a bot stub whose `_open_trades` matches the real shape:
    Dict[str, BotTrade-like-namespace] keyed by `id`."""
    bot = MagicMock()
    bot._open_trades = {
        tid: SimpleNamespace(id=tid, symbol=f"SYM{i}")
        for i, tid in enumerate(trade_ids)
    }
    bot.close_trade = AsyncMock(return_value=True)
    return bot


# ─────────────────────────────────────────────────────────────────────
# 1. Happy path: 3 open trades, all close cleanly.
# ─────────────────────────────────────────────────────────────────────
def test_flatten_all_calls_close_trade_for_every_open_position():
    from routers.safety_router import flatten_all

    bot = _make_bot_with_open_trades("t-FDX-1", "t-UPS-1", "t-BMNR-1")

    fake_db = MagicMock()
    fake_db.order_queue.update_many = AsyncMock(
        return_value=SimpleNamespace(modified_count=0)
    )
    fake_client = MagicMock()
    fake_client.__getitem__.return_value = fake_db

    with patch("services.trading_bot_service.get_trading_bot_service",
               return_value=bot, create=True), \
         patch("motor.motor_asyncio.AsyncIOMotorClient",
               return_value=fake_client, create=True), \
         patch.dict("os.environ", {"MONGO_URL": "mongodb://x", "DB_NAME": "test"}):
        result = _run(flatten_all(confirm="FLATTEN"))

    assert result["success"] is True, result
    summary = result["summary"]
    assert summary["positions_requested_close"] == 3
    assert summary["positions_succeeded"] == 3
    assert summary["positions_failed"] == 0
    assert summary["close_errors"] == []

    # close_trade fired with each `id` (the BotTrade.id field, NOT the
    # legacy `trade_id` that pre-fix code looked for).
    called_ids = sorted(
        c.args[0] for c in bot.close_trade.await_args_list
    )
    assert called_ids == ["t-BMNR-1", "t-FDX-1", "t-UPS-1"]
    # Reason stamped consistently for forensic correlation.
    for c in bot.close_trade.await_args_list:
        assert c.kwargs.get("reason") == "emergency_flatten_all"


# ─────────────────────────────────────────────────────────────────────
# 2. Mixed outcome: one success, one returns False, one raises.
# ─────────────────────────────────────────────────────────────────────
def test_flatten_all_records_failures_without_aborting_loop():
    from routers.safety_router import flatten_all

    bot = MagicMock()
    bot._open_trades = {
        "OK":   SimpleNamespace(id="OK"),
        "NOPE": SimpleNamespace(id="NOPE"),
        "BOOM": SimpleNamespace(id="BOOM"),
    }

    async def _close(trade_id, reason="manual"):
        if trade_id == "OK":
            return True
        if trade_id == "NOPE":
            return False
        raise RuntimeError("IB rejected: INSUFFICIENT_QUANTITY")

    bot.close_trade = _close

    fake_db = MagicMock()
    fake_db.order_queue.update_many = AsyncMock(
        return_value=SimpleNamespace(modified_count=0)
    )
    fake_client = MagicMock()
    fake_client.__getitem__.return_value = fake_db

    with patch("services.trading_bot_service.get_trading_bot_service",
               return_value=bot, create=True), \
         patch("motor.motor_asyncio.AsyncIOMotorClient",
               return_value=fake_client, create=True), \
         patch.dict("os.environ", {"MONGO_URL": "mongodb://x", "DB_NAME": "test"}):
        result = _run(flatten_all(confirm="FLATTEN"))

    summary = result["summary"]
    assert summary["positions_requested_close"] == 3
    assert summary["positions_succeeded"] == 1
    assert summary["positions_failed"] == 2
    err_ids = sorted(e.get("trade_id") for e in summary["close_errors"])
    assert err_ids == ["BOOM", "NOPE"]
    boom_err = next(e for e in summary["close_errors"] if e["trade_id"] == "BOOM")
    assert "INSUFFICIENT_QUANTITY" in boom_err["err"]


# ─────────────────────────────────────────────────────────────────────
# 3. Defensive: legacy dict-shaped trade with `trade_id` (not `id`)
#    still resolves — fallback chain in the fix supports it.
# ─────────────────────────────────────────────────────────────────────
def test_flatten_all_fallback_supports_legacy_trade_id_attribute():
    from routers.safety_router import flatten_all

    bot = MagicMock()
    bot._open_trades = {
        "legacy-1": {"trade_id": "legacy-1", "symbol": "OLD"},
    }
    bot.close_trade = AsyncMock(return_value=True)

    fake_db = MagicMock()
    fake_db.order_queue.update_many = AsyncMock(
        return_value=SimpleNamespace(modified_count=0)
    )
    fake_client = MagicMock()
    fake_client.__getitem__.return_value = fake_db

    with patch("services.trading_bot_service.get_trading_bot_service",
               return_value=bot, create=True), \
         patch("motor.motor_asyncio.AsyncIOMotorClient",
               return_value=fake_client, create=True), \
         patch.dict("os.environ", {"MONGO_URL": "mongodb://x", "DB_NAME": "test"}):
        result = _run(flatten_all(confirm="FLATTEN"))

    summary = result["summary"]
    assert summary["positions_succeeded"] == 1
    bot.close_trade.assert_awaited_once_with(
        "legacy-1", reason="emergency_flatten_all"
    )


# ─────────────────────────────────────────────────────────────────────
# 4. Confirm guard still required (?confirm=FLATTEN).
# ─────────────────────────────────────────────────────────────────────
def test_flatten_all_requires_confirm_param():
    from fastapi import HTTPException
    from routers.safety_router import flatten_all

    with pytest.raises(HTTPException) as exc:
        _run(flatten_all(confirm=""))
    assert exc.value.status_code == 400
    assert "FLATTEN" in str(exc.value.detail)


# ─────────────────────────────────────────────────────────────────────
# 5. v19.34.25 — Envelope honesty: every close fails → success=False.
#    Pre-fix the response was hardcoded `success: True`, so today's
#    v19.34.24b import bug (positions_requested_close: 0 + stage error)
#    returned a green envelope while the bot did nothing. This pin
#    locks down the new contract.
# ─────────────────────────────────────────────────────────────────────
def test_flatten_all_returns_failure_when_every_close_fails():
    from routers.safety_router import flatten_all

    bot = MagicMock()
    bot._open_trades = {
        "T1": SimpleNamespace(id="T1"),
        "T2": SimpleNamespace(id="T2"),
    }
    bot.close_trade = AsyncMock(return_value=False)   # every close fails

    fake_db = MagicMock()
    fake_db.order_queue.update_many = AsyncMock(
        return_value=SimpleNamespace(modified_count=0)
    )
    fake_client = MagicMock()
    fake_client.__getitem__.return_value = fake_db

    with patch("services.trading_bot_service.get_trading_bot_service",
               return_value=bot, create=True), \
         patch("motor.motor_asyncio.AsyncIOMotorClient",
               return_value=fake_client, create=True), \
         patch.dict("os.environ", {"MONGO_URL": "mongodb://x", "DB_NAME": "test"}):
        result = _run(flatten_all(confirm="FLATTEN"))

    assert result["success"] is False, result      # the actual regression pin
    assert result["summary"]["positions_requested_close"] == 2
    assert result["summary"]["positions_succeeded"] == 0
    assert result["summary"]["positions_failed"] == 2


# ─────────────────────────────────────────────────────────────────────
# 6. v19.34.25 — Envelope honesty: closure-step itself crashes (the
#    exact v19.34.24b import-bug shape) → success=False.
# ─────────────────────────────────────────────────────────────────────
def test_flatten_all_returns_failure_when_close_step_crashes():
    from routers.safety_router import flatten_all

    fake_db = MagicMock()
    fake_db.order_queue.update_many = AsyncMock(
        return_value=SimpleNamespace(modified_count=0)
    )
    fake_client = MagicMock()
    fake_client.__getitem__.return_value = fake_db

    # Make the import inside flatten_all fail — same shape as the
    # v19.34.24b operator bug (`get_trading_bot` not found).
    def _boom(*args, **kwargs):
        raise ImportError("cannot import name 'get_trading_bot'")

    with patch("services.trading_bot_service.get_trading_bot_service",
               side_effect=_boom, create=True), \
         patch("motor.motor_asyncio.AsyncIOMotorClient",
               return_value=fake_client, create=True), \
         patch.dict("os.environ", {"MONGO_URL": "mongodb://x", "DB_NAME": "test"}):
        result = _run(flatten_all(confirm="FLATTEN"))

    assert result["success"] is False, result
    assert any(e.get("stage") == "close-positions"
               for e in result["summary"]["close_errors"])
    assert result["summary"]["positions_requested_close"] == 0


# ─────────────────────────────────────────────────────────────────────
# 7. v19.34.25 — Envelope honesty: mixed (some succeed) → success=True.
#    At least one close worked, so "flatten-all initiated" is honest.
# ─────────────────────────────────────────────────────────────────────
def test_flatten_all_returns_success_when_at_least_one_close_works():
    from routers.safety_router import flatten_all

    bot = MagicMock()
    bot._open_trades = {
        "T1": SimpleNamespace(id="T1"),
        "T2": SimpleNamespace(id="T2"),
    }

    async def _close(trade_id, reason="manual"):
        return trade_id == "T1"   # only T1 succeeds

    bot.close_trade = _close

    fake_db = MagicMock()
    fake_db.order_queue.update_many = AsyncMock(
        return_value=SimpleNamespace(modified_count=0)
    )
    fake_client = MagicMock()
    fake_client.__getitem__.return_value = fake_db

    with patch("services.trading_bot_service.get_trading_bot_service",
               return_value=bot, create=True), \
         patch("motor.motor_asyncio.AsyncIOMotorClient",
               return_value=fake_client, create=True), \
         patch.dict("os.environ", {"MONGO_URL": "mongodb://x", "DB_NAME": "test"}):
        result = _run(flatten_all(confirm="FLATTEN"))

    assert result["success"] is True, result   # one close worked → honest "ok"
    assert result["summary"]["positions_succeeded"] == 1
    assert result["summary"]["positions_failed"] == 1
