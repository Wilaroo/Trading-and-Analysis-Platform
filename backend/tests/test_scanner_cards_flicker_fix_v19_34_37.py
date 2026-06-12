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

# v322w — portable test paths: this file previously hardcoded "/app/..."
# (dev-container path) which crashes on the DGX. Auto-fixed by
# scripts/fix_test_paths_portable.py.
import pathlib as _pl
_REPO_ROOT = str(_pl.Path(__file__).resolve().parents[2])

from pathlib import Path


def test_recent_alerts_respects_caller_limit():
    """get_recent_alerts must use `limit`, not the legacy hardcoded 5."""
    src = Path((_REPO_ROOT + "/backend/services/sentcom_service.py")).read_text("utf-8")
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
    src = Path((_REPO_ROOT + "/frontend/src/components/sentcom/hooks/useSentComAlerts.js")).read_text("utf-8")
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


def test_setups_watching_has_no_artificial_caps():
    """v19.34.38 — get_setups_watching must surface every qualified setup.

    Pre-v19.34.38 had three caps that hid legitimate watchlist symbols on
    high-momentum mornings:
      1. live_alerts[:10]            — primary scanner source
      2. scanner.get_recent_alerts(limit=5)  — secondary source
      3. return setups[:6]           — final cap
    All three are removed; the scanner's own enabled-setup / timeframe-fit /
    per-symbol qualification filters are the source of truth.
    """
    src = Path((_REPO_ROOT + "/backend/services/sentcom_service.py")).read_text("utf-8")
    idx = src.index("async def get_setups_watching")
    end = src.index("async def get_recent_alerts", idx)
    block = src[idx:end]

    assert "live_alerts[:10]" not in block, (
        "get_setups_watching still has the legacy live_alerts[:10] cap."
    )
    assert "limit=5)" not in block, (
        "get_setups_watching still calls scanner.get_recent_alerts(limit=5)."
    )
    assert "return setups[:6]" not in block, (
        "get_setups_watching still has the final setups[:6] cap."
    )
    # And the new uncapped contract must be in place
    assert "for alert in live_alerts:" in block, (
        "Primary scanner source must iterate the full live_alerts list."
    )
    assert "return setups\n" in block, (
        "get_setups_watching must return the full setups list, not a slice."
    )


def test_scanner_card_just_arrived_pulse_wired():
    """v19.34.38d — scanner cards get a 1.5s pulse the first time they appear."""
    src = Path((_REPO_ROOT + "/frontend/src/components/sentcom/v5/ScannerCardsV5.jsx")).read_text("utf-8")
    # The tracker refs must exist
    assert "seenRef" in src and "newKeys" in src, (
        "ScannerCardsV5 lost the first-seen tracker (seenRef / newKeys). "
        "New scanner hits will no longer pulse on arrival."
    )
    # Both flat and grouped render paths must thread isNew into ScannerCard
    assert src.count("isNew={newKeys.has(") >= 2, (
        "ScannerCardsV5 no longer threads isNew={newKeys.has(...)} into both "
        "the flat and grouped render paths — pulse won't fire in one of them."
    )
    # ScannerCard signature must accept isNew, and apply the className
    assert ", isNew, " in src, "ScannerCard signature must accept isNew prop."
    assert "${isNew ? ' just-arrived' : ''}" in src, (
        "ScannerCard no longer applies the .just-arrived className when isNew is true."
    )

    # CSS animation must exist
    css = Path((_REPO_ROOT + "/frontend/src/components/sentcom/v5/useV5Styles.js")).read_text("utf-8")
    assert "v5-card-arrive" in css, (
        "useV5Styles is missing the @keyframes v5-card-arrive animation."
    )
    assert "prefers-reduced-motion" in css, (
        "useV5Styles must respect prefers-reduced-motion for accessibility."
    )
