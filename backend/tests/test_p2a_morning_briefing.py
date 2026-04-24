"""
P2-A — Morning Briefing rich UI.

Contracts for:
    - overnight_sentiment_service (window computation, batch, threshold)
    - live_data_router new endpoints (watchlist, top-movers, overnight-sentiment)
    - Morning Briefing modal wiring
    - NIA DataCacheProvider warning fix (hoisted setCached)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ====================== overnight_sentiment_service ======================

def test_compute_windows_has_yesterday_close_and_premarket():
    from services.overnight_sentiment_service import compute_windows
    # Fix "now" at Tue 2026-04-28 14:00 UTC (≈ 10:00 ET, post 09:30 so premarket frozen)
    now = datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc)
    w = compute_windows(now_utc=now)
    assert "yesterday_close" in w
    assert "premarket" in w
    yc = w["yesterday_close"]
    pm = w["premarket"]
    assert yc["start"] < yc["end"]
    assert pm["start"] < pm["end"]
    # yesterday_close must end exactly where premarket starts (midnight ET today)
    assert yc["end"] == pm["start"]
    # yesterday_close window is exactly 8 hours (16:00→24:00 ET)
    assert yc["end"] - yc["start"] == timedelta(hours=8)


def test_compute_windows_premarket_frozen_after_0930():
    """Once the wall clock is past 09:30 ET, premarket end must freeze
    at 09:30 ET (not continue to follow `now`)."""
    from services.overnight_sentiment_service import compute_windows
    # 20:00 UTC ≈ 16:00 ET (post-open, after premarket)
    now = datetime(2026, 4, 28, 20, 0, tzinfo=timezone.utc)
    w = compute_windows(now_utc=now)
    pm = w["premarket"]
    # Premarket must be exactly 9.5 hours long when frozen (00:00 → 09:30 ET)
    assert pm["end"] - pm["start"] == timedelta(hours=9, minutes=30)


def test_swing_threshold_is_locked_at_0_30():
    from services.overnight_sentiment_service import SWING_THRESHOLD
    assert SWING_THRESHOLD == 0.30, (
        "User-locked swing threshold is ±0.30 — do not drift without approval"
    )


def test_max_symbols_cap_is_12():
    from services.overnight_sentiment_service import MAX_SYMBOLS
    assert MAX_SYMBOLS == 12, (
        "Briefing budget: ≤12 symbols per overnight-sentiment call"
    )


@pytest.mark.asyncio
async def test_compute_batch_bounded_and_ranked(monkeypatch):
    """Batch must cap at MAX_SYMBOLS and sort notable-first then by |swing|."""
    from services import overnight_sentiment_service as svc

    # Stub compute_symbol with deterministic scores
    swings = {"AAA": 0.40, "BBB": 0.10, "CCC": -0.35, "DDD": 0.00}

    async def fake_compute_symbol(sym):
        s = swings.get(sym, 0.0)
        return {
            "symbol": sym,
            "swing": s,
            "notable": abs(s) >= 0.30,
            "swing_direction": "up" if s > 0.30 else "down" if s < -0.30 else "flat",
            "sentiment_yesterday_close": 0.0,
            "sentiment_premarket": s,
            "news_count_overnight": 2,
            "top_headline": None,
            "top_headline_ts": None,
            "news_count_yesterday_close": 1,
            "news_count_premarket": 1,
            "window": {},
        }
    monkeypatch.setattr(svc, "compute_symbol", fake_compute_symbol)

    # 15 symbols — batch must cap at 12
    out = await svc.compute_batch([f"SYM{i}" for i in range(15)] + list(swings.keys()))
    assert len(out) <= svc.MAX_SYMBOLS

    out2 = await svc.compute_batch(["BBB", "DDD", "AAA", "CCC"])
    syms = [r["symbol"] for r in out2]
    # Notable first: AAA (|0.4|) and CCC (|0.35|) before BBB (|0.1|) and DDD (0)
    assert syms.index("AAA") < syms.index("BBB")
    assert syms.index("CCC") < syms.index("BBB")
    # Within notables: AAA (0.40) before CCC (0.35)
    assert syms.index("AAA") < syms.index("CCC")


# ====================== live_data_router new endpoints ==================

LIVE_ROUTER_SRC = Path("/app/backend/routers/live_data_router.py").read_text(encoding="utf-8")


def test_briefing_watchlist_endpoint_exists():
    assert '"/briefing-watchlist"' in LIVE_ROUTER_SRC


def test_briefing_top_movers_endpoint_exists():
    assert '"/briefing-top-movers"' in LIVE_ROUTER_SRC


def test_overnight_sentiment_endpoint_exists():
    assert '"/overnight-sentiment"' in LIVE_ROUTER_SRC


def test_watchlist_builder_uses_positions_scanner_and_indices():
    """The dynamic watchlist must draw from all three sources per user choice (A)."""
    assert "ib_live_snapshot" in LIVE_ROUTER_SRC, (
        "Briefing watchlist must include open positions (ib_live_snapshot)"
    )
    assert "market_scanner_results" in LIVE_ROUTER_SRC, (
        "Briefing watchlist must include scanner top-10 (market_scanner_results)"
    )
    assert "_CORE_INDICES" in LIVE_ROUTER_SRC, (
        "Briefing watchlist must include core indices (SPY/QQQ/IWM/DIA/VIX)"
    )
    # Cap at 12
    assert "[:12]" in LIVE_ROUTER_SRC, (
        "Briefing watchlist must cap at 12 symbols to match overnight-sentiment budget"
    )


# ====================== Frontend wiring ==================================

MODAL_SRC = Path("/app/frontend/src/components/MorningBriefingModal.jsx").read_text(encoding="utf-8")
HOOK_SRC = Path("/app/frontend/src/components/sentcom/v5/useBriefingLiveData.js").read_text(encoding="utf-8")


def test_modal_uses_useBriefingLiveData_hook():
    assert "useBriefingLiveData" in MODAL_SRC, (
        "MorningBriefingModal must use the useBriefingLiveData hook"
    )


def test_modal_renders_top_movers_section():
    assert 'testid="briefing-section-top-movers"' in MODAL_SRC, (
        "Modal must render a 'Top movers · watchlist' section"
    )
    assert 'briefing-mover-${s.symbol}' in MODAL_SRC or \
           'briefing-mover-' in MODAL_SRC, (
        "Top movers section must expose per-symbol test ids"
    )


def test_modal_renders_overnight_sentiment_section():
    assert 'testid="briefing-section-overnight-sentiment"' in MODAL_SRC
    assert "Overnight sentiment swings" in MODAL_SRC
    assert "briefing-sentiment-${r.symbol}" in MODAL_SRC or \
           "briefing-sentiment-" in MODAL_SRC


def test_modal_refresh_button_reloads_both_feeds():
    assert "reload(); live.reload();" in MODAL_SRC, (
        "Refresh button must reload both the original briefing feed and the live-data feed"
    )


def test_hook_hits_both_endpoints():
    assert "/api/live/briefing-top-movers" in HOOK_SRC
    assert "/api/live/overnight-sentiment" in HOOK_SRC


def test_hook_fetches_in_parallel():
    """Two endpoints must be awaited via Promise.all for fast render."""
    assert "Promise.all" in HOOK_SRC


# ====================== NIA DataCacheProvider warning fix ================

NIA_SRC = Path("/app/frontend/src/components/NIA/index.jsx").read_text(encoding="utf-8")


def test_nia_setCached_no_longer_inside_setData():
    """React warning fix: the concrete call site of setCached('niaData', ...)
    must live inside a useEffect block, not inside a setData updater.
    Previously the code wrapped setCached inside `setData(current => {...})`
    which triggers the render-phase setState warning."""
    # The concrete call site
    idx = NIA_SRC.find("setCached('niaData', data, 60000)")
    assert idx > 0, (
        "Expected the hoisted 'setCached(\\'niaData\\', data, 60000)' form to exist"
    )
    # Look at the 200 chars BEFORE this call — must be inside a useEffect hook,
    # not inside a setData updater
    before = NIA_SRC[max(0, idx - 200): idx]
    assert "useEffect(" in before, (
        "setCached must be hoisted INTO a useEffect so cache write happens after commit"
    )
    assert "setData(current =>" not in before, (
        "setCached must NOT be inside a setData(current => ...) updater (render-phase warning)"
    )


def test_nia_has_dedicated_cache_persistence_effect():
    """The hoisted setCached must live in a useEffect that watches `data`."""
    assert "setCached('niaData', data, 60000)" in NIA_SRC, (
        "NIA must persist `data` to cache via a dedicated useEffect"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
