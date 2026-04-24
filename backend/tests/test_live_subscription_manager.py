"""
Phase 2 — Live Subscription Layer contracts.

Lock in the ref-counted subscription manager, cap enforcement, heartbeat
TTL sweep, and pusher-side endpoint invariants. All tests run without a
real pusher or IB gateway — the pusher RPC client is disabled via
ENABLE_LIVE_BAR_RPC=false so subscribe/unsubscribe stay in-process.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


# ---------- common fixture: isolated manager instance per test -----------

@pytest.fixture(autouse=True)
def _isolate_manager(monkeypatch):
    """Reset manager singleton + disable pusher forwarding so tests don't
    hit network. Runs on every test."""
    monkeypatch.setenv("ENABLE_LIVE_BAR_RPC", "false")
    monkeypatch.delenv("IB_PUSHER_RPC_URL", raising=False)
    from services import ib_pusher_rpc, live_subscription_manager
    ib_pusher_rpc._client_instance = None
    live_subscription_manager.reset_live_subscription_manager()
    yield
    live_subscription_manager.reset_live_subscription_manager()


# ---------------------- ref-counting semantics ---------------------------

def test_subscribe_first_time_creates_state():
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    res = mgr.subscribe("SPY")
    assert res["accepted"] is True
    assert res["newly_subscribed"] is True
    assert res["ref_count"] == 1
    assert res["symbol"] == "SPY"


def test_subscribe_twice_increments_ref_count():
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    mgr.subscribe("spy")  # lowercase — must normalize
    r2 = mgr.subscribe("SPY")
    assert r2["ref_count"] == 2
    assert r2["newly_subscribed"] is False


def test_unsubscribe_decrements_then_removes():
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    mgr.subscribe("SPY"); mgr.subscribe("SPY"); mgr.subscribe("SPY")
    r1 = mgr.unsubscribe("SPY")
    assert r1["fully_unsubscribed"] is False
    assert r1["ref_count"] == 2
    r2 = mgr.unsubscribe("SPY"); r3 = mgr.unsubscribe("SPY")
    assert r2["fully_unsubscribed"] is False
    assert r3["fully_unsubscribed"] is True
    assert r3["ref_count"] == 0


def test_unsubscribe_not_subscribed_rejected():
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    res = mgr.unsubscribe("NOSUCH")
    assert res["accepted"] is False
    assert res["reason"] == "not_subscribed"


def test_subscribe_rejects_empty_symbol():
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    assert mgr.subscribe("")["accepted"] is False
    assert mgr.subscribe(None)["accepted"] is False
    assert mgr.subscribe("   ")["accepted"] is False


# ---------------------- cap enforcement ----------------------------------

def test_subscribe_cap_rejects_beyond_max(monkeypatch):
    monkeypatch.setenv("MAX_LIVE_SUBSCRIPTIONS", "3")
    from services.live_subscription_manager import (
        get_live_subscription_manager,
        reset_live_subscription_manager,
    )
    reset_live_subscription_manager()
    mgr = get_live_subscription_manager()
    assert mgr.subscribe("AAA")["accepted"] is True
    assert mgr.subscribe("BBB")["accepted"] is True
    assert mgr.subscribe("CCC")["accepted"] is True
    blocked = mgr.subscribe("DDD")
    assert blocked["accepted"] is False
    assert blocked["reason"] == "cap_reached"
    assert blocked["active_subscriptions"] == 3
    assert blocked["max_subscriptions"] == 3


def test_subscribe_cap_allows_duplicates_even_at_max(monkeypatch):
    """Re-subscribing an existing symbol must succeed even at cap — ref-count
    bump does not create a new subscription slot."""
    monkeypatch.setenv("MAX_LIVE_SUBSCRIPTIONS", "2")
    from services.live_subscription_manager import (
        get_live_subscription_manager,
        reset_live_subscription_manager,
    )
    reset_live_subscription_manager()
    mgr = get_live_subscription_manager()
    mgr.subscribe("AAA"); mgr.subscribe("BBB")
    r = mgr.subscribe("AAA")  # dup — must succeed, ref_count bumps to 2
    assert r["accepted"] is True
    assert r["newly_subscribed"] is False
    assert r["ref_count"] == 2


def test_default_cap_is_60():
    """The handoff-locked default is 60 (half of IB's ~100 L1 ceiling)."""
    from services.live_subscription_manager import (
        DEFAULT_MAX_SUBSCRIPTIONS,
        _max_subs,
    )
    assert DEFAULT_MAX_SUBSCRIPTIONS == 60
    # When env var is unset, _max_subs must return 60
    os.environ.pop("MAX_LIVE_SUBSCRIPTIONS", None)
    assert _max_subs() == 60


# ---------------------- heartbeat + sweep --------------------------------

def test_heartbeat_touches_last_heartbeat_at():
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    mgr.subscribe("SPY")
    # Snapshot the initial heartbeat time
    snap1 = mgr.list_subscriptions()["subscriptions"][0]
    time.sleep(0.02)
    mgr.heartbeat("SPY")
    snap2 = mgr.list_subscriptions()["subscriptions"][0]
    assert snap2["last_heartbeat_at"] >= snap1["last_heartbeat_at"]


def test_heartbeat_not_subscribed_rejected():
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    assert mgr.heartbeat("NOSUCH")["accepted"] is False


def test_sweep_expires_stale_subs():
    """Sweep must remove subs whose last_heartbeat_at is older than TTL."""
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    mgr.subscribe("AAA"); mgr.subscribe("BBB")

    # Use a point in the future well past the 300s default TTL
    far_future = time.time() + 10_000
    expired = mgr.sweep_expired(now=far_future)
    assert sorted(expired) == ["AAA", "BBB"]
    assert mgr.list_subscriptions()["active_count"] == 0


def test_sweep_preserves_recent_subs():
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    mgr.subscribe("AAA")
    # Run sweep immediately — nothing should expire
    expired = mgr.sweep_expired()
    assert expired == []
    assert mgr.list_subscriptions()["active_count"] == 1


def test_default_heartbeat_ttl_is_5_minutes():
    from services.live_subscription_manager import (
        DEFAULT_HEARTBEAT_TTL_SECONDS,
        _ttl_seconds,
    )
    assert DEFAULT_HEARTBEAT_TTL_SECONDS == 300
    os.environ.pop("LIVE_SUB_HEARTBEAT_TTL_S", None)
    assert _ttl_seconds() == 300


# ---------------------- list_subscriptions shape -------------------------

def test_list_subscriptions_has_required_fields():
    from services.live_subscription_manager import get_live_subscription_manager
    mgr = get_live_subscription_manager()
    mgr.subscribe("AAA")
    out = mgr.list_subscriptions()
    for key in ("active_count", "max_subscriptions", "heartbeat_ttl_seconds", "subscriptions"):
        assert key in out
    sub = out["subscriptions"][0]
    for key in ("symbol", "ref_count", "first_subscribed_at",
                "last_heartbeat_at", "age_seconds", "idle_seconds"):
        assert key in sub


# ---------------------- Windows pusher RPC source contracts --------------

PUSHER_PATH = Path("/app/documents/scripts/ib_data_pusher.py")


def _pusher_src() -> str:
    return PUSHER_PATH.read_text(encoding="utf-8")


def test_pusher_declares_subscribe_unsubscribe_subscriptions():
    src = _pusher_src()
    for route in ('"/rpc/subscribe"', '"/rpc/unsubscribe"', '"/rpc/subscriptions"'):
        assert route in src, f"Phase 2 RPC endpoint {route} missing from pusher"


def test_pusher_subscribe_uses_existing_subscribe_market_data():
    """/rpc/subscribe must reuse the existing subscribe_market_data method
    — re-implementing IB qualify/req logic separately would drift."""
    src = _pusher_src()
    assert "pusher.subscribe_market_data(new_syms" in src, (
        "/rpc/subscribe must call pusher.subscribe_market_data for consistency"
    )


def test_pusher_unsubscribe_cancels_mkt_data_and_cleans_buffers():
    """/rpc/unsubscribe must call cancelMktData AND remove from buffers."""
    src = _pusher_src()
    assert "cancelMktData(contract)" in src, (
        "/rpc/unsubscribe must call ib.cancelMktData to free the slot"
    )
    assert "pusher.subscribed_contracts.pop(sym" in src, (
        "/rpc/unsubscribe must remove symbol from subscribed_contracts"
    )
    assert "pusher.quotes_buffer.pop(sym" in src, (
        "/rpc/unsubscribe must clear quotes_buffer so stale data doesn't persist"
    )


# ---------------------- DGX router endpoint contracts --------------------

LIVE_ROUTER_PATH = Path("/app/backend/routers/live_data_router.py")


def test_router_has_phase2_endpoints():
    src = LIVE_ROUTER_PATH.read_text(encoding="utf-8")
    for ep in (
        '"/subscribe/{symbol}"',
        '"/unsubscribe/{symbol}"',
        '"/heartbeat/{symbol}"',
        '"/subscriptions"',
    ):
        assert ep in src, f"Phase 2 DGX endpoint {ep} missing from live_data_router"


# ---------------------- frontend hook contracts --------------------------

HOOK_PATH = Path("/app/frontend/src/hooks/useLiveSubscription.js")


def test_hook_exists_and_exports_both_variants():
    src = HOOK_PATH.read_text(encoding="utf-8")
    assert "export function useLiveSubscription" in src, (
        "single-symbol hook must be exported"
    )
    assert "export function useLiveSubscriptions" in src, (
        "multi-symbol hook (for Scanner top-10) must be exported"
    )


def test_hook_calls_subscribe_and_unsubscribe_paths():
    src = HOOK_PATH.read_text(encoding="utf-8")
    assert "/api/live/subscribe/" in src
    assert "/api/live/unsubscribe/" in src
    assert "/api/live/heartbeat/" in src


def test_hook_heartbeat_is_2_minutes():
    """Heartbeat must fire well under the backend 5-min TTL — use 2min."""
    src = HOOK_PATH.read_text(encoding="utf-8")
    assert "2 * 60 * 1000" in src or "HEARTBEAT_MS = 120000" in src, (
        "hook must heartbeat every 2 minutes (under 5-min backend TTL)"
    )


def test_hook_wired_into_chartpanel():
    src = Path("/app/frontend/src/components/sentcom/panels/ChartPanel.jsx").read_text(encoding="utf-8")
    assert "useLiveSubscription" in src, (
        "ChartPanel must import + call useLiveSubscription for focused symbol"
    )


def test_hook_wired_into_enhanced_ticker_modal():
    src = Path("/app/frontend/src/components/EnhancedTickerModal.jsx").read_text(encoding="utf-8")
    assert "useLiveSubscription" in src, (
        "EnhancedTickerModal must import + call useLiveSubscription"
    )


def test_scanner_auto_subs_top_10():
    src = Path("/app/frontend/src/components/sentcom/v5/ScannerCardsV5.jsx").read_text(encoding="utf-8")
    assert "useLiveSubscriptions" in src, (
        "Scanner must use multi-sub hook for top-10 auto-subscribe"
    )
    assert "cards.slice(0, 10)" in src, (
        "Scanner must limit auto-subs to top-10 cards"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
