"""
trade_style_classifier.py — v19.34.161 (Feb 2026)

Single source of truth on the BACKEND for "what trade-style bucket does
this setup belong to?". Mirrors EXACTLY the JS in
`frontend/src/utils/tradeStyleMeta.js` (SETUP_TO_STYLE table,
DIRECTIONAL_SUFFIXES, STYLE_ALIAS, resolution chain) so the per-style
P&L card and any future server-side style aggregation agrees with what
the UI renders.

When you add a new setup to `SETUP_TO_STYLE` here, also add it to the JS
file (and vice versa). The 38-case smoke test in
`frontend/src/utils/__tests__/tradeStyleMeta.smoke.js` is the
ground-truth contract.

Public API:
    resolve_trade_style(row: dict) -> str   ∈ {scalp, intraday,
                                               multi_day, swing,
                                               investment, position,
                                               unknown}
    is_scalp(row: dict) -> bool             — convenience
    style_bucket_for_setup(setup_name: str, trade_style: str = None,
                            timeframe: str = None) -> str
                                            — same resolution given just
                                              the raw fields (handy from
                                              alert_outcomes rows where
                                              the schema is partial).

Used by:
    routers/trading_bot.py `/pnl-by-style`
    scripts/setup_sl_tp_audit.py
    (future) services for any per-style server-side metric
"""
from __future__ import annotations

from typing import Any, Dict, Optional


# ── style metadata (label / horizon / bucket) ────────────────────────────────

TRADE_STYLE_META: Dict[str, Dict[str, str]] = {
    "scalp":      {"label": "Scalp",      "horizon": "Minutes — 1 hour",     "bucket": "scalp"},
    "intraday":   {"label": "Intraday",   "horizon": "1 — 6 hours",          "bucket": "intraday"},
    "multi_day":  {"label": "Multi-day",  "horizon": "1 — 5 days",           "bucket": "swing"},
    "swing":      {"label": "Swing",      "horizon": "1 — 3 weeks",          "bucket": "swing"},
    "investment": {"label": "Investment", "horizon": "3 weeks — 3 months",   "bucket": "investment"},
    "position":   {"label": "Position",   "horizon": "3+ months",            "bucket": "position"},
    "unknown":    {"label": "Unknown",    "horizon": "Not classified",       "bucket": "unknown"},
}

# Setup → style fallback table. Mirrors SETUP_TO_STYLE in tradeStyleMeta.js
# (kept in sync with `SETUP_REGISTRY` in services/smb_integration.py).
SETUP_TO_STYLE: Dict[str, str] = {
    # ── SCALP (23) ────────────────────────────────────────────────────
    "9_ema_scalp": "scalp", "abc_scalp": "scalp", "backside": "scalp",
    "bella_fade": "scalp", "fashionably_late": "scalp",
    "first_move_down": "scalp", "first_move_up": "scalp",
    "gap_fade": "scalp", "gap_give_go": "scalp", "gap_pick_roll": "scalp",
    "hitchhiker": "scalp", "mean_reversion": "scalp", "off_sides": "scalp",
    "off_sides_short": "scalp", "puppy_dog": "scalp", "rubber_band": "scalp",
    "rubber_band_long": "scalp", "rubber_band_short": "scalp",
    "second_chance": "scalp", "spencer_scalp": "scalp", "tidal_wave": "scalp",
    "time_of_day_fade": "scalp", "volume_capitulation": "scalp", "vwap_fade": "scalp",
    # ── INTRADAY (20) ─────────────────────────────────────────────────
    "back_through_open": "intraday", "big_dog": "intraday", "breakdown": "intraday",
    "breaking_news": "intraday", "breakout": "intraday", "chart_pattern": "intraday",
    "first_vwap_pullback": "intraday", "hod_breakout": "intraday",
    "lod_breakdown": "intraday", "opening_drive": "intraday", "orb": "intraday",
    "range_break": "intraday", "relative_strength": "intraday",
    "relative_weakness": "intraday", "squeeze": "intraday",
    "up_through_open": "intraday", "vwap_bounce": "intraday",
    "vwap_continuation": "intraday", "premarket_high_break": "intraday",
    "the_3_30_trade": "intraday", "bouncy_ball": "intraday",
    # ── SWING / MULTI-DAY ─────────────────────────────────────────────
    "base_breakout": "swing", "breakdown_confirmed": "multi_day",
    "daily_breakout": "multi_day", "daily_squeeze": "multi_day",
    "day_2_continuation": "swing", "gap_fill_open": "swing",
    "trend_continuation": "multi_day", "pocket_pivot": "swing",
    "vcp_breakout": "swing", "three_week_tight": "swing",
    "bull_flag_break": "swing", "bear_flag_break": "swing",
    "ascending_triangle_break": "swing", "descending_triangle_break": "swing",
    "cup_with_high_handle": "swing", "accumulation_entry": "swing",
    # ── INVESTMENT ────────────────────────────────────────────────────
    "weekly_breakout": "investment", "multi_quarter_base_break": "investment",
    "rs_leader_break": "investment", "fifty_two_week_high_break": "investment",
    "power_trend_stack": "investment",
    # ── POSITION ──────────────────────────────────────────────────────
    "stage_2_breakout": "position", "stage_1_to_2_transition": "position",
    "stage_3_to_4_breakdown": "position", "golden_cross_filtered": "position",
    "death_cross_filtered": "position", "two_hundred_day_reclaim": "position",
    "two_hundred_day_loss": "position",
}

# Canonicalise raw trade_style strings (backend stamps and SMB classes).
STYLE_ALIAS: Dict[str, str] = {
    "scalp": "scalp", "move_2_move": "scalp",
    "intraday": "intraday", "trade_2_hold": "intraday",
    "multi_day": "multi_day", "a_plus": "multi_day", "day": "multi_day",
    "swing": "swing",
    "investment": "investment", "invest": "investment",
    "position": "position", "longterm": "position",
}

# Generic SMB classes the backend stamps as a fallback when the alert
# didn't pick a real horizon. These are SKIPPED in favour of the setup-
# derived style, mirroring tradeStyleMeta.js v19.34.32 behaviour.
GENERIC_TRADE_STYLES = {"trade_2_hold"}

# Mirror tradeStyleMeta.js v19.34.160 — strip directional suffix so
# `gap_fade_long` resolves to the same bucket as `gap_fade`.
DIRECTIONAL_SUFFIXES = ("_long", "_short", "_buy", "_sell")


def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


def _strip_directional_suffix(key: str) -> str:
    """Reduce a raw setup key toward its canonical base via the SSOT
    (`services.setup_taxonomy.canonicalize`) — strips directional/scalp/
    confirmed suffixes AND applies the canonical alias table, so misses like
    `rubber_band_scalp_long`, `breakout_confirmed`, or `big_dawg` now resolve.

    Note: `_setup_lookup` checks the RAW key in SETUP_TO_STYLE *first*, so
    explicit entries (e.g. `breakdown_confirmed`→multi_day) are unaffected —
    delegation only improves the fall-through case. Falls back to the legacy
    local strip if the SSOT import is unavailable.
    """
    try:
        from services.setup_taxonomy import canonicalize
        return canonicalize(key)
    except Exception:
        for suf in DIRECTIONAL_SUFFIXES:
            if key.endswith(suf):
                return key[: -len(suf)]
        return key


def _setup_lookup(raw: Any) -> Optional[str]:
    """Look up the raw key, falling back to the directional-stripped
    variant. Returns None on miss."""
    k = _norm(raw)
    if not k:
        return None
    if k in SETUP_TO_STYLE:
        return SETUP_TO_STYLE[k]
    stripped = _strip_directional_suffix(k)
    return SETUP_TO_STYLE.get(stripped) if stripped != k else None


def _try_key(raw: Any) -> Optional[str]:
    k = _norm(raw)
    if not k:
        return None
    if k in STYLE_ALIAS:
        return STYLE_ALIAS[k]
    if k in TRADE_STYLE_META:
        return k
    return None


def resolve_trade_style(row: Optional[Dict[str, Any]]) -> str:
    """Resolve the canonical style key for a trade-shaped dict.

    Order of precedence (matches frontend `resolveTradeStyle`):
      1. `trade_style` (canonical aliases applied)
      2. `scan_tier`
      3. `tier`
      4. `symbol_tier`
      5. `timeframe`            ← v19.34.160 — backend already stamps "scalp" sometimes
      6. setup-derived (variant > type) via SETUP_TO_STYLE with
         directional-suffix stripping
      7. fallback "unknown"

    Special case: when `trade_style` is the generic SMB fallback
    `trade_2_hold` AND a setup-derived style is available, the setup
    wins.
    """
    if not row:
        return "unknown"
    row = row if isinstance(row, dict) else {}

    setup_key = _setup_lookup(row.get("setup_variant")) or _setup_lookup(row.get("setup_type"))
    if setup_key and _norm(row.get("trade_style")) in GENERIC_TRADE_STYLES:
        return setup_key
    return (
        _try_key(row.get("trade_style"))
        or _try_key(row.get("scan_tier"))
        or _try_key(row.get("tier"))
        or _try_key(row.get("symbol_tier"))
        or _try_key(row.get("timeframe"))
        or setup_key
        or "unknown"
    )


def is_scalp(row: Optional[Dict[str, Any]]) -> bool:
    return resolve_trade_style(row) == "scalp"


def style_bucket_for_setup(
    setup_name: Optional[str],
    trade_style: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> str:
    """Convenience for callers (e.g. alert_outcomes consumers) where
    only the raw fields exist, not a full trade row."""
    return resolve_trade_style({
        "setup_type": setup_name,
        "trade_style": trade_style,
        "timeframe": timeframe,
    })


def style_label(style_key: str) -> str:
    """Human label for a resolved style key (defensive)."""
    return TRADE_STYLE_META.get(style_key, TRADE_STYLE_META["unknown"])["label"]
