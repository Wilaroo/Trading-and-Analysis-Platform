"""
v19.34.192 — EOD/close-path bracket-cancel dispatch via ib_direct.

Root cause (EOD deadlock, recurring): `_cancel_ib_bracket_orders` dispatched
its cancels through `routers.ib._ib_service.cancel_order()` — the legacy
`IBService` worker thread, which on this DGX deployment is the stale/
disconnected direct-ib_insync worker serialized on a 1-worker queue. The
cancel never reached IB before the 8s+5s terminal-wait expired, so every EOD
close aborted with `bracket_cancel_timeout_race_risk`; cross-session DAY/GTC
orders also threw `10147 OrderId not found`.

Fix: route the cancel dispatch through the DGX-native `ib_direct` socket
(IB Gateway "Master API client ID = 11", v19.34.190). `ib_direct.cancel_order`
cancels via the live order OBJECT (which carries `permId`) looked up from the
`_ib.trades()` cache that `_fetch_live_open_order_ids` freshly populates via
`reqAllOpenOrders`. Master clientId 11 lets clientId-11 cancel cross-session
orders → dodges 10147. Legacy IBService remains a fallback so a cancel is
never silently dropped. The 8s+5s OCA-race / flip-protection contract is
untouched.

These tests lock the dispatch-preference + fallback contract (no IB hardware).
"""
import asyncio
import sys
import types

from services.trade_executor_service import TradeExecutorService


def _make_svc():
    # Bypass __init__ (touches broker config); the helper reads no
    # instance state beyond `self`.
    return object.__new__(TradeExecutorService)


class _FakeIBD:
    """Fake ib_direct service. Records cancel calls."""

    def __init__(self, connected=True, result=None):
        self._connected = connected
        self._result = result if result is not None else {"success": True}
        self.cancelled = []

    async def ensure_connected(self):
        return self._connected

    async def cancel_order(self, oid):
        self.cancelled.append(int(oid))
        return self._result


class _FakeIBService:
    """Fake legacy IBService worker. Records cancel calls."""

    def __init__(self, ok=True):
        self._ok = ok
        self.cancelled = []

    async def cancel_order(self, oid):
        self.cancelled.append(int(oid))
        return self._ok


def _install_ib_service(monkeypatch, fake):
    # `from routers.ib import _ib_service` — inject a light fake module so we
    # don't import the heavy real router.
    mod = types.ModuleType("routers.ib")
    mod._ib_service = fake
    monkeypatch.setitem(sys.modules, "routers.ib", mod)


def _install_ib_direct(monkeypatch, fake):
    monkeypatch.setattr(
        "services.ib_direct_service.get_ib_direct_service",
        lambda: fake, raising=False,
    )


# ── 1. happy path: ib_direct connected + success → IBService NOT used ──────
def test_dispatch_prefers_ib_direct(monkeypatch):
    svc = _make_svc()
    ibd = _FakeIBD(connected=True, result={"success": True})
    ibs = _FakeIBService(ok=True)
    _install_ib_direct(monkeypatch, ibd)
    _install_ib_service(monkeypatch, ibs)

    ok = asyncio.run(svc._dispatch_bracket_cancel_v192(10913, "AAPL"))

    assert ok is True
    assert ibd.cancelled == [10913]
    assert ibs.cancelled == [], "legacy IBService must NOT be hit when ib_direct succeeds"


# ── 2. ib_direct returns failure (e.g. 10147) → falls back to IBService ────
def test_dispatch_falls_back_on_ib_direct_failure(monkeypatch):
    svc = _make_svc()
    ibd = _FakeIBD(connected=True, result={"success": False, "error": "10147 not found"})
    ibs = _FakeIBService(ok=True)
    _install_ib_direct(monkeypatch, ibd)
    _install_ib_service(monkeypatch, ibs)

    ok = asyncio.run(svc._dispatch_bracket_cancel_v192(222, "TSLA"))

    assert ok is True
    assert ibd.cancelled == [222]
    assert ibs.cancelled == [222], "fallback to legacy IBService expected"


# ── 3. ib_direct unavailable (None) → falls back to IBService ──────────────
def test_dispatch_falls_back_when_ib_direct_none(monkeypatch):
    svc = _make_svc()
    ibs = _FakeIBService(ok=True)
    monkeypatch.setattr(
        "services.ib_direct_service.get_ib_direct_service",
        lambda: None, raising=False,
    )
    _install_ib_service(monkeypatch, ibs)

    ok = asyncio.run(svc._dispatch_bracket_cancel_v192(7, "NVDA"))

    assert ok is True
    assert ibs.cancelled == [7]


# ── 4. ib_direct not connected → falls back to IBService ───────────────────
def test_dispatch_falls_back_when_ib_direct_disconnected(monkeypatch):
    svc = _make_svc()
    ibd = _FakeIBD(connected=False)
    ibs = _FakeIBService(ok=True)
    _install_ib_direct(monkeypatch, ibd)
    _install_ib_service(monkeypatch, ibs)

    ok = asyncio.run(svc._dispatch_bracket_cancel_v192(99, "MSFT"))

    assert ok is True
    assert ibd.cancelled == [], "disconnected ib_direct must not be used"
    assert ibs.cancelled == [99]


# ── 5. no transport at all → returns False, never raises ───────────────────
def test_dispatch_no_transport_returns_false(monkeypatch):
    svc = _make_svc()
    monkeypatch.setattr(
        "services.ib_direct_service.get_ib_direct_service",
        lambda: None, raising=False,
    )
    _install_ib_service(monkeypatch, None)

    ok = asyncio.run(svc._dispatch_bracket_cancel_v192(1, "AMD"))
    assert ok is False


# ── 6. _cancel_ib_bracket_orders ROUTES through the v192 helper (not IBService)
def test_cancel_ib_bracket_orders_uses_v192_dispatch(monkeypatch):
    """End-to-end: a trade with one live bracket child must dispatch its
    cancel through `_dispatch_bracket_cancel_v192`, never the old direct
    `_ib_service.cancel_order` import inside the loop."""
    svc = _make_svc()

    trade = types.SimpleNamespace(
        symbol="AAPL",
        stop_order_id=10913,
        target_order_id=None,
        target_order_ids=[],
    )

    # Fresh open-orders shows the child as live → it must be cancelled.
    async def _fake_fetch_live():
        return {10913}
    monkeypatch.setattr(svc, "_fetch_live_open_order_ids", _fake_fetch_live)

    dispatched = []

    async def _fake_dispatch(oid, symbol):
        dispatched.append((int(oid), symbol))
        return True
    monkeypatch.setattr(svc, "_dispatch_bracket_cancel_v192", _fake_dispatch)

    # ib_direct connected; wait reports the child terminal (cancelled).
    class _FakeIBD:
        async def ensure_connected(self):
            return True

        async def wait_for_orders_terminal(self, oids, timeout_s=8.0, poll_iv_s=0.1):
            return {"cancelled": list(oids), "filled": [], "other_terminal": [],
                    "unknown": [], "timeout": []}
    monkeypatch.setattr(
        "services.ib_direct_service.get_ib_direct_service",
        lambda: _FakeIBD(), raising=False,
    )

    result = asyncio.run(svc._cancel_ib_bracket_orders(trade))

    assert dispatched == [(10913, "AAPL")], "cancel must route through v192 dispatch helper"
    assert 10913 in result["issued"]
    assert 10913 in result["cancelled"]
    assert result["filled"] == [] and result["timeout"] == []
