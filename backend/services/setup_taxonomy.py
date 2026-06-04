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
    # puppy_dog = small-cap "follow the leader" w/ a SHORTER consolidation than
    #   big_dog → same consolidation-breakout momentum management (operator 2026-06).
    "puppy_dog",
    # gap_pick_roll = gap → pullback → ROLL/continue in the gap direction
    #   (trend-following momentum); distinct from gap_fade (mean-reversion).
    "gap_pick_roll",
}
_FADE_CLASS: Set[str] = {
    "bella_fade", "first_move_up", "first_move_down", "backside", "rubber_band",
    "off_sides", "vwap_fade", "mean_reversion", "gap_fade", "time_of_day_fade",
    "volume_capitulation",
    # tidal_wave: OUR detector implements it as intraday mean-reversion
    #   (enhanced_scanner regime map = FADE/STRONG_DOWNTREND), so it lives in the
    #   fade class to match execution. NOTE: standard-usage "tidal wave" is a
    #   momentum volume-surge — naming conflict flagged for operator decision.
    "tidal_wave",
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

# ── strategy_family (the edge thesis) — aligned to the AI feature-extractor
#    family keys (MOMENTUM/BREAKOUT/REVERSAL/MEAN_REVERSION/RANGE/TREND_CONTINUATION)
#    so the taxonomy and the model share one vocabulary (consistency-map §3).
#    This is a finer split of setup_class: momentum→{continuation,breakout},
#    fade→{reversion,reversal}.
_BREAKOUT_FAMILY: Set[str] = {
    "orb", "premarket_high_break", "hod_breakout", "breakout", "range_break",
    "squeeze", "big_dog", "puppy_dog", "gap_give_go", "chart_pattern",
    # higher-timeframe breakouts
    "daily_breakout", "daily_squeeze", "weekly_breakout", "vcp_breakout",
    "three_week_tight", "pocket_pivot", "bull_flag_break", "bear_flag_break",
    "ascending_triangle_break", "descending_triangle_break",
    "cup_with_high_handle", "base_breakout", "stage_2_breakout",
    "multi_quarter_base_break", "fifty_two_week_high_break",
}
_REVERSAL_FAMILY: Set[str] = {
    "first_move_up", "first_move_down", "backside", "off_sides",
    "volume_capitulation", "bouncy_ball", "breakdown",
    "stage_3_to_4_breakdown", "death_cross_filtered", "two_hundred_day_loss",
}
_REVERSION_FAMILY: Set[str] = {
    "vwap_fade", "mean_reversion", "rubber_band", "gap_fade", "bella_fade",
    "time_of_day_fade", "tidal_wave",
}
# Reversal setups that historically RUN (so exit_archetype = runner despite
# being a reversal): backside-of-parabolic, capitulation snaps, breakdown rides.
_RUNNER_REVERSALS: Set[str] = {
    "backside", "volume_capitulation", "bouncy_ball",
}
_FAMILY_TO_AI_KEY: Dict[str, str] = {
    "continuation": "TREND_CONTINUATION",
    "breakout": "BREAKOUT",
    "reversion": "MEAN_REVERSION",
    "reversal": "REVERSAL",
    "rotation": "RANGE",
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


def strategy_family(raw) -> str:
    """The trade's edge thesis (descriptive, orthogonal to exit management).

    Returns one of: 'continuation', 'breakout', 'reversion', 'reversal',
    'rotation', 'swing', 'position', 'unknown'. A momentum stock CAN be a
    reversal — family describes the thesis, exit_archetype describes management.
    """
    base = canonicalize(raw)
    if not base:
        return "unknown"
    if base in _BREAKOUT_FAMILY:
        return "breakout"
    if base in _REVERSAL_FAMILY:
        return "reversal"
    if base in _REVERSION_FAMILY:
        return "reversion"
    cls = setup_class(base)
    if cls == "momentum":
        return "continuation"
    if cls == "fade":
        return "reversion"
    if cls in ("swing", "position"):
        if any(t in base for t in ("break", "squeeze", "pivot", "tight",
                                   "flag", "triangle", "cup")):
            return "breakout"
        return "continuation"
    return "unknown"


def exit_archetype_prior(raw) -> str:
    """Default exit-management archetype for a setup — the axis brackets read.

    Returns: 'runner' | 'target' | 'swing_hold' | 'position_hold'.
    This is a PRIOR; the live system later overrides it from the setup's
    own MFE/MAE distribution once it has enough samples (consistency-map §6).
      runner       = tight stop, scale partials, trail an EMA, ride extension
      target       = fixed R targets, scale out at levels, no runner
      swing_hold   = multi-day, wider stop, HTF partials
      position_hold= weeks-months, widest stop, stage/fundamental
    """
    base = canonicalize(raw)
    if not base:
        return "target"
    cls = setup_class(base)
    if cls == "swing":
        return "swing_hold"
    if cls == "position":
        return "position_hold"
    if base in _RUNNER_REVERSALS:
        return "runner"
    # scalps scale out fast → target (no big runner) even when continuation
    try:
        if style_of(base) == "scalp":
            return "target"
    except Exception:  # pragma: no cover
        pass
    if strategy_family(base) in ("continuation", "breakout"):
        return "runner"
    return "target"


def ai_feature_family(raw) -> str:
    """Map a setup to the AI feature-extractor family key
    (TREND_CONTINUATION / BREAKOUT / MEAN_REVERSION / REVERSAL / RANGE).
    Callers prepend 'SHORT_' for short-direction extractors. Lets the
    feature pipeline be driven by strategy_family instead of an implicit map.
    """
    return _FAMILY_TO_AI_KEY.get(strategy_family(raw), "MOMENTUM")


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


def export_taxonomy() -> dict:
    """Machine-readable snapshot of the canonical taxonomy — the SINGLE feed
    for the `/api/sentcom/taxonomy` endpoint, `agents/vocabulary.py` (NIA), and
    (via that endpoint) the frontend. Built entirely from this SSOT so every
    consumer stays in lock-step and cannot drift."""
    setups: Dict[str, Dict[str, str]] = {}
    for base in sorted(ALL_CANONICAL_SETUPS):
        try:
            style = style_of(base)
        except Exception:
            style = "unknown"
        setups[base] = {
            "strategy_family": strategy_family(base),
            "exit_archetype": exit_archetype_prior(base),
            "style": style,
            "class": setup_class(base),
            "ai_feature_family": ai_feature_family(base),
        }
    return {
        "version": "v19.34.270",
        "strategy_families": ["continuation", "breakout", "reversion",
                              "reversal", "rotation"],
        "exit_archetypes": ["runner", "target", "swing_hold", "position_hold"],
        "family_to_ai_key": dict(_FAMILY_TO_AI_KEY),
        "edge_excluded_exact": sorted(_EDGE_EXCLUDED_EXACT),
        "edge_excluded_prefixes": list(_EDGE_EXCLUDED_PREFIXES),
        "setups": setups,
    }


def vocabulary_section() -> str:
    """Human-readable taxonomy block for `agents/vocabulary.py` — generated from
    `export_taxonomy()` so the NIA/agent prompt stays in lock-step with the SSOT."""
    t = export_taxonomy()
    by_family: Dict[str, list] = {f: [] for f in t["strategy_families"]}
    for base, meta in t["setups"].items():
        by_family.setdefault(meta["strategy_family"], []).append(base)
    lines = [
        "=== STRATEGY FAMILY x EXIT ARCHETYPE (SSOT — services/setup_taxonomy.py) ===",
        "",
        "Every setup carries TWO orthogonal tags (plus the trade_style horizon):",
        "  strategy_family (edge thesis): continuation · breakout · reversion · reversal · rotation",
        "  exit_archetype  (management):  runner (tight stop + trail a runner) ·",
        "    target (fixed R targets, no runner) · swing_hold · position_hold",
        "",
        "canonical_setup collapses directional variants for grouping",
        "  (e.g. vwap_fade_long / vwap_fade_short -> vwap_fade).",
        "",
        "SETUPS BY STRATEGY FAMILY:",
    ]
    for fam in t["strategy_families"]:
        names = sorted(by_family.get(fam, []))
        if names:
            lines.append(f"  {fam}: " + ", ".join(names))
    lines += [
        "",
        "EXIT ARCHETYPE NOTE (a reversal CAN run; a continuation scalp can be a target):",
        "  runner examples:  squeeze, orb, vwap_continuation, backside, bouncy_ball",
        "  target examples:  vwap_fade, mean_reversion, bella_fade, gap_give_go (scalp)",
        "",
        "Artifacts EXCLUDED from edge/grading: reconciled_*, approaching_*, imported_from_ib.",
        "GET /api/sentcom/taxonomy returns the full machine-readable taxonomy.",
    ]
    return "\n".join(lines)
