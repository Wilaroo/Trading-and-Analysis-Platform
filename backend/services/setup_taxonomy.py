"""
setup_taxonomy.py — Canonical setup taxonomy & single normalization point.
=============================================================================

WHY THIS EXISTS (2026-06 investigation, see memory/SETUP_TAXONOMY_INVESTIGATION_2026-06.md):
The same setup concept lived in 5 unsynced tables, each with its own alias map
and its own suffix-stripping:
  1. enhanced_scanner._enabled_setups          (base names)
  2. enhanced_scanner._check_* detectors        (stamp *_long/_short/_confirmed variants)
  3. smb_integration.SETUP_REGISTRY + SMB_SETUP_ALIASES
  4. market_setup_classifier.TRADE_ALIASES + EXPERIMENTAL_TRADES
  5. trade_style_classifier.SETUP_TO_STYLE (+ frontend tradeStyleMeta.js)

Live DB audit (diag_setup_inventory.py, 2026-06) proved this fragments stats:
  - vwap_fade_long + vwap_fade_short graded as 2 buckets (367 trades total)
  - mean_reversion_long/_short, rubber_band_long/_short, breakout/breakout_confirmed split
  - reconciled_*/imported_from_ib/carry_forward_watch/approaching_* polluting edge stats
  - bouncy_ball fell to 'unknown' style (now fixed in the style maps)

This module is the ONE place that answers:
  - canonicalize(raw)      -> base setup name (strips ALL variant suffixes + applies aliases)
  - is_edge_excluded(raw)  -> True for reconciliation/import/watchlist/precursor artifacts
                              (these must NOT count toward per-setup edge / grading)
  - setup_class(raw)       -> 'momentum' | 'fade' | 'swing' | 'position' | 'unknown'
                              (the dimension INTRADAY_BRACKET_V2 scopes on)
  - is_momentum_class(raw) -> convenience for bracket scoping
  - style_of(raw)          -> delegates to trade_style_classifier (no duplication)

Direction is intentionally NOT collapsed: callers that need direction-split edge
read the raw variant; callers that need config (style/stop/bracket/F-gate) call
canonicalize() first. "Split for grading, canonical for config."

NOTE: setups that fire as their OWN distinct trades (puppy_dog, tidal_wave,
vwap_bounce) are deliberately NOT merged into their matrix-aliases here — that
is a strategy decision pending operator sign-off. Only true never-fire synonyms
and directional/style suffixes are normalized.
"""
from __future__ import annotations

from typing import Dict, Optional, Set

# ── suffix normalization (longest match wins) ──────────────────────────────
# Order matters only for the "longest wins" scan; we sort by length anyway.
_VARIANT_SUFFIXES = (
    "_scalp_long", "_scalp_short", "_scalp",
    "_long", "_short", "_buy", "_sell",
    "_confirmed", "_intraday",
)
_SUFFIXES_BY_LEN = tuple(sorted(_VARIANT_SUFFIXES, key=len, reverse=True))

# ── conservative alias map ─────────────────────────────────────────────────
# Only TRUE synonyms that do NOT fire independently in the live DB (per audit).
# puppy_dog / tidal_wave / vwap_bounce are EXCLUDED on purpose (they fire as
# distinct trades with their own stats — merging them is a pending decision).
_ALIASES: Dict[str, str] = {
    "big_dawg": "big_dog",
    "gap_and_go": "gap_give_go",
    "bounce": "rubber_band",
    "stuffed": "off_sides",
    "market_play": "hitchhiker",
    "changing_fundamentals": "breaking_news",
    "above_the_clouds": "hod_breakout",
    "afternoon_to_light": "hod_breakout",
    "back_through": "back_through_open",
    "opening_range_breakout": "orb",
    "scalp": "spencer_scalp",
}

# ── artifacts that must NEVER count toward per-setup edge / grading ─────────
# Exact names + prefix families. From audit sections [B]/[D].
_EDGE_EXCLUDED_EXACT: Set[str] = {
    "imported_from_ib",
    "carry_forward_watch",
    "day_2_continuation_watch",
    "gap_fill_open_watch",
}
_EDGE_EXCLUDED_PREFIXES = ("reconciled_", "approaching_")

# ── class map (momentum vs fade) — drives INTRADAY_BRACKET_V2 scope ────────
# Grounded in the operator's own cheat-sheet exit rules:
#   momentum = trail an EMA after 1-2 legs (tight stop + runner)
#   fade     = fixed two-wave mean reversion (1-2 tries, no runner)
_MOMENTUM_CLASS: Set[str] = {
    "opening_drive", "orb", "premarket_high_break", "back_through_open",
    "up_through_open", "vwap_continuation", "vwap_bounce", "hod_breakout",
    "breakout", "range_break", "gap_give_go", "gap_pick_roll", "big_dog",
    "squeeze", "the_3_30_trade", "bouncy_ball", "second_chance", "hitchhiker",
    "spencer_scalp", "9_ema_scalp", "abc_scalp", "first_vwap_pullback",
    "fashionably_late", "breaking_news", "chart_pattern",
}
_FADE_CLASS: Set[str] = {
    "bella_fade", "first_move_up", "first_move_down", "backside", "rubber_band",
    "off_sides", "vwap_fade", "mean_reversion", "gap_fade", "time_of_day_fade",
    "volume_capitulation", "tidal_wave", "puppy_dog",
}
# Higher-timeframe families (swing/position scanner) — never intraday brackets.
_SWING_CLASS: Set[str] = {
    "accumulation_entry", "daily_breakout", "daily_squeeze", "day_2_continuation",
    "gap_fill_open", "trend_continuation", "pocket_pivot", "vcp_breakout",
    "three_week_tight", "bull_flag_break", "bear_flag_break",
    "ascending_triangle_break", "descending_triangle_break", "cup_with_high_handle",
    "base_breakout", "breakdown_confirmed", "breakdown",
}
_POSITION_CLASS: Set[str] = {
    "weekly_breakout", "multi_quarter_base_break", "rs_leader_break",
    "fifty_two_week_high_break", "power_trend_stack", "stage_2_breakout",
    "stage_1_to_2_transition", "stage_3_to_4_breakdown", "golden_cross_filtered",
    "death_cross_filtered", "two_hundred_day_reclaim", "two_hundred_day_loss",
}


def _norm(v) -> str:
    return str(v or "").strip().lower()


def _strip_suffix(name: str) -> str:
    for suf in _SUFFIXES_BY_LEN:
        if name.endswith(suf) and len(name) > len(suf):
            return name[: -len(suf)]
    return name


def canonicalize(raw) -> str:
    """Resolve a raw setup_type/variant to its canonical base name.

    Strips the longest matching variant suffix, then applies the alias
    table. Idempotent and safe on already-canonical names.
    """
    k = _norm(raw)
    if not k:
        return ""
    # alias may apply pre- or post-strip; do strip then alias, then re-alias once.
    base = _strip_suffix(k)
    base = _ALIASES.get(base, base)
    return base


def is_edge_excluded(raw) -> bool:
    """True for reconciliation/import/watchlist/precursor labels that must be
    excluded from per-setup edge, grade math, and EV leaderboards."""
    k = _norm(raw)
    if not k:
        return True
    if k in _EDGE_EXCLUDED_EXACT:
        return True
    return k.startswith(_EDGE_EXCLUDED_PREFIXES)


def setup_class(raw) -> str:
    """Classify the canonical setup into a management class.

    Returns one of: 'momentum', 'fade', 'swing', 'position', 'unknown'.
    """
    base = canonicalize(raw)
    if not base:
        return "unknown"
    if base in _MOMENTUM_CLASS:
        return "momentum"
    if base in _FADE_CLASS:
        return "fade"
    if base in _SWING_CLASS:
        return "swing"
    if base in _POSITION_CLASS:
        return "position"
    return "unknown"


def is_momentum_class(raw) -> bool:
    """Intraday momentum/continuation class — the scope for INTRADAY_BRACKET_V2."""
    return setup_class(raw) == "momentum"


def style_of(raw) -> str:
    """Resolved trade-style bucket for a raw setup name. Delegates to
    trade_style_classifier so there is exactly one style source of truth."""
    try:
        from services.trade_style_classifier import style_bucket_for_setup
    except Exception:  # pragma: no cover - import path fallback
        from backend.services.trade_style_classifier import style_bucket_for_setup
    return style_bucket_for_setup(canonicalize(raw))


# Full known-setup roster (for diagnostics / coverage checks). Union of all
# classes; canonical names only.
ALL_CANONICAL_SETUPS: Set[str] = (
    _MOMENTUM_CLASS | _FADE_CLASS | _SWING_CLASS | _POSITION_CLASS
)
