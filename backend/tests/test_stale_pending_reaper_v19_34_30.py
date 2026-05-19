import inspect
def test_pending_reaper_loop_is_defined_and_scheduled():
    from services import trading_bot_service
    src = inspect.getsource(trading_bot_service)
    assert "_stale_pending_reaper_loop" in src
    assert "self._pending_reaper_task = asyncio.create_task(" in src
    assert "PENDING_REAPER_ENABLED" in src
    assert "PENDING_REAPER_MAX_AGE_S" in src
