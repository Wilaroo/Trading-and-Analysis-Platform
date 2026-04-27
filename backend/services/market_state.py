"""
Market State — single source of truth for "what mode is the US equities
market in *right now*?".

Promoted out of `services/live_bar_cache.py` (2026-02) so the same answer
is shared by:
    * live_bar_cache TTLs            (rth=30s vs weekend=3600s)
    * backfill_readiness_service     (stale-day budget per timeframe)
    * account_guard                  (soften "no account snapshot" to
                                      "pending" when market is closed)
    * enhanced_scanner.TimeWindow    (CLOSED gate before sub-window math)
    * /api/market-state              (frontend banner + ops dashboard)

Three orthogonal pieces of information are surfaced:

  state          one of {"rth", "extended", "overnight", "weekend"}
                 — a coarse bucket good for cache TTLs + UI banners.

  is_market_open boolean — RTH only. Extended hours count as CLOSED for
                 trading-bot gating purposes.

  is_weekend     boolean — true Sat/Sun in America/New_York. Used by
                 readiness checks to widen stale-data tolerances and by
                 the UI to show the "Weekend Mode · buffers active" banner.

We deliberately do NOT consult a holiday calendar here — that would
introduce a dependency on `pandas_market_calendars` for a single boolean.
A holiday weekday rounds down to "overnight" which is conservatively safe
(15-minute cache, instead of 30-second RTH cache). When/if the user wants
holiday-aware behaviour we can extend `get_snapshot()` with an optional
`holidays` callback without breaking callers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover — Windows w/o tzdata fallback
    _ET = None


# Coarse buckets used by callers above. Intentionally orthogonal from
# `enhanced_scanner.TimeWindow` (which subdivides RTH into 9 windows).
STATE_RTH = "rth"
STATE_EXTENDED = "extended"
STATE_OVERNIGHT = "overnight"
STATE_WEEKEND = "weekend"

# Friendly labels for the banner / UI.
STATE_LABELS = {
    STATE_RTH:       "Regular trading hours",
    STATE_EXTENDED:  "Extended hours (pre/post)",
    STATE_OVERNIGHT: "Overnight (closed)",
    STATE_WEEKEND:   "Weekend",
}


def _now_et(now_utc: Optional[datetime] = None) -> datetime:
    """Return current wall-clock in America/New_York with proper EST/EDT.

    Falls back to a fixed UTC-5 offset if zoneinfo is unavailable
    (Windows tzdata package missing). The fallback drifts by 1h during
    DST but only widens 'overnight' into late-RTH on those days — safe
    because TTLs only err toward stale, not toward live.
    """
    now = now_utc or datetime.now(timezone.utc)
    if _ET is not None:
        return now.astimezone(_ET)
    # Manual fallback (no DST) — tolerate the 1h drift.
    from datetime import timedelta
    return (now - timedelta(hours=5)).replace(tzinfo=None)


def classify_market_state(now_utc: Optional[datetime] = None) -> str:
    """Return one of {'rth', 'extended', 'overnight', 'weekend'}.

    This is the canonical implementation. `services/live_bar_cache` and
    `services/backfill_readiness_service` re-export this same function so
    older imports keep working. Do NOT add a parallel implementation
    elsewhere — all callers must funnel through here.
    """
    et = _now_et(now_utc)
    if et.weekday() >= 5:
        return STATE_WEEKEND
    hhmm = et.hour * 60 + et.minute
    if 9 * 60 + 30 <= hhmm < 16 * 60:
        return STATE_RTH
    if 4 * 60 <= hhmm < 9 * 60 + 30 or 16 * 60 <= hhmm < 20 * 60:
        return STATE_EXTENDED
    return STATE_OVERNIGHT


def is_weekend(now_utc: Optional[datetime] = None) -> bool:
    """Convenience: true on Sat/Sun in America/New_York."""
    return _now_et(now_utc).weekday() >= 5


def is_market_open(now_utc: Optional[datetime] = None) -> bool:
    """Convenience: true only during RTH (09:30–16:00 ET, Mon–Fri)."""
    return classify_market_state(now_utc) == STATE_RTH


def is_market_closed(now_utc: Optional[datetime] = None) -> bool:
    """True for weekend OR overnight (i.e. nothing fresh from IB).

    Extended hours intentionally do NOT count as 'closed' here — the
    trading-bot CAN execute against IB during pre/post if explicitly
    enabled. Use `is_market_open()` for the strict RTH gate.
    """
    s = classify_market_state(now_utc)
    return s in (STATE_WEEKEND, STATE_OVERNIGHT)


def get_snapshot(now_utc: Optional[datetime] = None) -> dict:
    """Full payload for the `/api/market-state` endpoint and ops dashboards.

    Stable schema — frontend banner + scripts depend on these keys.
    """
    now = now_utc or datetime.now(timezone.utc)
    et = _now_et(now)
    state = classify_market_state(now)
    return {
        "state": state,
        "label": STATE_LABELS.get(state, state),
        "is_weekend": state == STATE_WEEKEND,
        "is_market_open": state == STATE_RTH,
        "is_market_closed": state in (STATE_WEEKEND, STATE_OVERNIGHT),
        "buffers_active": state in (STATE_WEEKEND, STATE_OVERNIGHT),
        "now_utc": now.isoformat().replace("+00:00", "Z"),
        "now_et": et.isoformat(),
        "et_weekday": et.weekday(),    # Mon=0 .. Sun=6
        "et_hhmm": et.hour * 60 + et.minute,
        "tz": "America/New_York",
    }
