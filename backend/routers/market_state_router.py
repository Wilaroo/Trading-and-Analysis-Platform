"""
Market State Router — single canonical surface for "is the market open?".

Promoted out of `services/live_bar_cache` (2026-02) so the same answer is
shared by the chart panel, freshness inspector banner, autonomy gate, and
any future ops dashboard. See `services/market_state.py` for the logic.
"""
from __future__ import annotations

from fastapi import APIRouter

from services.market_state import get_snapshot

router = APIRouter(prefix="/api", tags=["Market State"])


@router.get("/market-state")
def market_state():
    """Return the canonical market-state snapshot.

    Response shape (stable):
      {
        "success": true,
        "state": "rth" | "extended" | "overnight" | "weekend",
        "label": "Regular trading hours" | …,
        "is_weekend": bool,
        "is_market_open": bool,
        "is_market_closed": bool,
        "buffers_active": bool,    # weekend OR overnight
        "now_utc": iso,
        "now_et": iso,
        "et_weekday": 0..6,
        "et_hhmm": int,
        "tz": "America/New_York"
      }
    """
    snap = get_snapshot()
    return {"success": True, **snap}
