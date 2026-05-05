"""
bracket_tif.py — v19.34.5 (2026-05-05)

Single source of truth for bracket order TIF (time-in-force) classification.

THE BUG THIS FIXES
==================
Pre-v19.34.5, every bracket's stop+target legs were hard-coded
`time_in_force: "GTC"` regardless of trade_style. For intraday trades, GTC
legs survive EOD/restarts/weekends, sit alive at IB indefinitely, and
randomly fire when price touches their levels — creating "Sell Short" /
"Buy to Cover" transactions the bot didn't intend and doesn't track.

Forensic evidence (2026-05-04): -17 STX short opened by an orphan GTC SELL
leg firing at 3:57 PM AFTER the bot's EOD market-flatten took position to 0.
IB classified the orphan fill as "Sell Short" because the long was already
flat. Bot had no `bot_trades` row for it, no log entry, no audit trail.

THE RULE
========
- INTRADAY trades (scalp, intraday, move_2_move, trade_2_hold) → TIF = DAY
- SWING/POSITION trades (multi_day, a_plus, swing, position, investment) → TIF = GTC
- Unknown/missing trade_style → TIF = DAY (matches the platform's intraday-by-
  default posture; fail-safe direction is "die at EOD" not "linger forever")

`outside_rth` follows TIF: DAY orders should NOT fire pre-market or
after-hours (the bot doesn't manage those windows). GTC orders need
outside_rth=True to provide legitimate overnight stop protection.

Usage from the executor / reconciler / bracket builder:

    from services.bracket_tif import bracket_tif

    tif, outside_rth = bracket_tif(trade.trade_style, trade.timeframe)
    bracket["stop"]["time_in_force"] = tif
    bracket["stop"]["outside_rth"] = outside_rth
    bracket["target"]["time_in_force"] = tif
    bracket["target"]["outside_rth"] = outside_rth

Tested by `tests/test_bracket_tif_v19_34_5.py` (8 cases covering both
canonical names, deprecated aliases, and unknown fallback).
"""
from __future__ import annotations

# Canonical intraday styles. These trades MUST be flat by EOD; any open
# bracket leg should die when the parent is flattened.
_INTRADAY_STYLES: frozenset[str] = frozenset({
    "scalp",          # TradeStyle.SCALP — minutes to 1 hour
    "intraday",       # TradeStyle.INTRADAY — 1-6 hours
    "move_2_move",    # alias for SCALP
    "trade_2_hold",   # alias for INTRADAY
    "day_trade",      # legacy alias seen in some scoring paths
})

# Canonical swing/position styles. These trades legitimately need overnight
# stop protection — bracket legs MUST be GTC + outside_rth=True.
_OVERNIGHT_STYLES: frozenset[str] = frozenset({
    "multi_day",      # TradeStyle.MULTI_DAY — 1-5 days
    "a_plus",         # alias for MULTI_DAY
    "swing",          # 1-2 weeks
    "position",       # weeks-months
    "investment",     # months+
    "long_term",      # rare but seen
})

# Canonical timeframe values that imply overnight hold even when trade_style
# is missing or stale (e.g. carryover rows from before this enum was wired).
_OVERNIGHT_TIMEFRAMES: frozenset[str] = frozenset({
    "multi_day",
    "swing",
    "position",
    "investment",
    "long_term",
    "weekly",
    "monthly",
})


def bracket_tif(
    trade_style: str | None,
    timeframe: str | None = None,
) -> tuple[str, bool]:
    """
    Returns (time_in_force, outside_rth) for a bracket order's stop/target legs.

    Decision tree:
      1. If trade_style is in OVERNIGHT_STYLES → ("GTC", True)
      2. If trade_style is in INTRADAY_STYLES → ("DAY", False)
      3. If trade_style is missing/unknown but timeframe is in
         OVERNIGHT_TIMEFRAMES → ("GTC", True)
      4. Default fallback → ("DAY", False) (fail-safe to "die at EOD")

    Examples:
        >>> bracket_tif("scalp")
        ('DAY', False)
        >>> bracket_tif("intraday")
        ('DAY', False)
        >>> bracket_tif("multi_day")
        ('GTC', True)
        >>> bracket_tif("swing")
        ('GTC', True)
        >>> bracket_tif("trade_2_hold")  # deprecated alias
        ('DAY', False)
        >>> bracket_tif(None)
        ('DAY', False)
        >>> bracket_tif("", timeframe="swing")
        ('GTC', True)
        >>> bracket_tif("garbage_value")
        ('DAY', False)
    """
    style = (trade_style or "").strip().lower()
    tf = (timeframe or "").strip().lower()

    if style in _OVERNIGHT_STYLES:
        return ("GTC", True)
    if style in _INTRADAY_STYLES:
        return ("DAY", False)
    # Unknown style — consult timeframe as a tiebreaker.
    if tf in _OVERNIGHT_TIMEFRAMES:
        return ("GTC", True)
    # Final fallback: intraday by default (platform's strong default posture).
    return ("DAY", False)


def is_overnight_trade(
    trade_style: str | None,
    timeframe: str | None = None,
) -> bool:
    """Convenience wrapper — True if the trade should hold overnight."""
    tif, _ = bracket_tif(trade_style, timeframe)
    return tif == "GTC"
