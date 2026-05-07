"""v19.34.37 — Scanner cards flicker fix regression tests.

The bug: in pre-market the operator saw 5 scanner cards most of the time
that "blipped" to 9 cards every 10-12 seconds, then back to 5. Two
backend bugs caused this:

1. `services/sentcom_service.py::get_recent_alerts()` hardcoded
   `live_alerts[:5]` — silently truncated the caller's `limit` (the
   /api/sentcom/alerts route signature accepted limits up to 500).

2. The frontend REST poll then overwrote fresh 9-card WS state with the
   truncated 5-card REST snapshot every 60 seconds.

Fix: respect the caller's `limit` in get_recent_alerts(), and add a
client-side anti-flicker guard so REST never downgrades fresh WS state.
"""

from pathlib import Path


def test_recent_alerts_respects_caller_limit():
    """get_recent_alerts must use `limit`, not the legacy hardcoded 5."""
    src = Path("/app/backend/services/sentcom_service.py").read_text("utf-8")
    # Locate the get_recent_alerts function
    idx = src.index("async def get_recent_alerts")
    block = src[idx:idx + 3000]
    # The buggy `[:5]` truncation must be gone
    assert "live_alerts[:5]" not in block, (
        "sentcom_service.get_recent_alerts still has the legacy live_alerts[:5] "
        "hardcap — REST endpoint will silently truncate to 5 alerts regardless "
        "of caller limit, causing the V5 scanner cards to flicker."
    )
    # And it must respect the caller's `limit`
    assert "live_alerts[:limit]" in block, (
        "get_recent_alerts must slice live_alerts by the caller's `limit` arg."
    )


def test_frontend_anti_flicker_guard_present():
    """useSentComAlerts must skip REST overwrites while WS is fresh."""
    src = Path("/app/frontend/src/components/sentcom/hooks/useSentComAlerts.js").read_text("utf-8")
    # Anti-flicker guard must exist
    assert "lastWsUpdateAt" in src, (
        "useSentComAlerts no longer tracks last WS update time — REST poll "
        "will overwrite fresh WS state again."
    )
    assert "WS_FRESHNESS_MS" in src, (
        "useSentComAlerts no longer has a freshness threshold for the WS-vs-REST "
        "race — the flicker may return."
    )
    # The fetchAlerts must early-return when WS is fresh
    assert "Date.now() - lastWsUpdateAt.current < WS_FRESHNESS_MS" in src, (
        "useSentComAlerts.fetchAlerts no longer checks WS freshness before "
        "calling setAlerts — REST will downgrade fresh WS state."
    )
