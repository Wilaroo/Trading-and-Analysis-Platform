"""v19.34.209 — blocking HTTP (Finnhub/FMP) must run off the event loop.

Reproduces the close-all incident: several `async def` enrichment methods called
synchronous `requests.get(..., timeout=10..20)` directly on the asyncio loop,
freezing it (wedge watchdog: "EVENT LOOP BLOCKED") — which hung the close API
and starved the pusher/ib_direct heartbeats. The fix wraps each call in
`await asyncio.to_thread(...)`. This test asserts a slow upstream no longer
blocks the loop.
"""
import asyncio
import time

import services.fundamental_data_service as fds
import services.news_service as ns
import services.earnings_service as es
import services.quality_service as qs


class _FakeResp:
    status_code = 200

    def json(self):
        return {"name": "Test Co", "exchange": "NASDAQ", "marketCapitalization": 1000}


def _slow_get(*args, **kwargs):
    # Simulate a slow Finnhub/FMP response doing blocking socket I/O.
    time.sleep(0.4)
    return _FakeResp()


def _run_with_heartbeat(coro_factory):
    """Run an async op while a 50ms heartbeat ticks; return (result, ticks)."""
    async def scenario():
        ticks = {"n": 0}

        async def heartbeat():
            try:
                while True:
                    await asyncio.sleep(0.05)
                    ticks["n"] += 1
            except asyncio.CancelledError:
                pass

        hb = asyncio.create_task(heartbeat())
        try:
            result = await coro_factory()
        finally:
            hb.cancel()
            await asyncio.gather(hb, return_exceptions=True)
        return result, ticks["n"]

    return asyncio.run(scenario())


def test_company_profile_does_not_block_loop(monkeypatch):
    monkeypatch.setattr(fds.requests, "get", _slow_get)
    svc = fds.FundamentalDataService()
    svc._finnhub_key = "test"
    result, ticks = _run_with_heartbeat(lambda: svc.get_company_profile("AAPL"))
    assert result is not None and result["name"] == "Test Co"
    # During the 0.4s blocking get the loop must keep ticking (>=4).
    # Pre-fix (sync requests.get on the loop) this was ~0.
    assert ticks >= 4, f"event loop was blocked (only {ticks} heartbeat ticks)"


def test_all_offender_modules_import_asyncio():
    # Guards against a future edit re-introducing a bare requests.get on the loop.
    import inspect
    for mod in (fds, ns, es, qs):
        src = inspect.getsource(mod)
        assert "import asyncio" in src, f"{mod.__name__} missing import asyncio"
        # no bare synchronous requests.get assignment left on an async path
        assert "= requests.get(" not in src, \
            f"{mod.__name__} still has a bare requests.get( on the event loop"
