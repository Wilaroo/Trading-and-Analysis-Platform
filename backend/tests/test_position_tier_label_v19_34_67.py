"""v19.34.67 — Position tier-chip labelling tests.

Pre-fix bug: every position rendered as "DAY 2 <dir>" regardless of actual
setup, because:
  1. Bot defaults `trade_style='trade_2_hold'` on every BotTrade (SMB
     classification = "Intraday Swing 1-6h", NOT a day counter).
  2. Frontend `STYLE_HUMAN_MAP['trade_2_hold'] = 'DAY 2'` literally
     mistranslated the SMB class as a day counter.
  3. No fall-through chain to surface the real setup label.

This test replicates the post-fix JS `tierLabel()` logic in Python so we
get pytest coverage of the decision tree. If the production JS diverges
from this spec, both must be updated together.
"""

# ───── helpers (mirror the JS logic exactly) ─────
STYLE_HUMAN_MAP = {
    "day_2_continuation": "DAY 2",
    "day_2_failure": "DAY 2 FAIL",
    "relative_strength_position": "RS POS",
    "relative_strength": "RS",
    "base_breakout": "BREAKOUT",
    "accumulation_entry": "ACCUM",
    "mean_reversion_long": "MEAN REV",
    "mean_reversion_short": "MEAN REV",
    "mean_reversion": "MEAN REV",
    "earnings_momentum": "EARN MOM",
    "sector_rotation": "ROTATION",
    "opening_range_break": "ORB",
    "opening_drive": "ORD",
    "the_3_30_trade": "3:30",
    "9_ema_scalp": "9-EMA",
    "vwap_continuation": "VWAP",
    "vwap_bounce": "VWAP",
    "vwap_fade_long": "VWAP FADE",
    "vwap_fade_short": "VWAP FADE",
    "premarket_high_break": "PMH",
    "bouncy_ball": "BOUNCY",
    "bella_fade": "FADE",
    "off_sides_short": "OFF SIDES",
    "off_sides": "OFF SIDES",
    "back_through_open": "BACK THRU",
    "up_through_open": "UP THRU",
    "gap_pick_roll": "PICK ROLL",
    "gap_fade": "GAP FADE",
    "reconciled_orphan": "ADOPTED",
    "reconciled": "ADOPTED",
}
GENERIC_TRADE_STYLE_KEYS = {
    "trade_2_hold", "trade_2_continuation", "move_2_move", "a_plus",
}


def humanize_style(raw):
    if not raw:
        return ""
    key = str(raw).lower()
    if key in STYLE_HUMAN_MAP:
        return STYLE_HUMAN_MAP[key]
    return key.replace("_", " ").upper()[:12]


def tier_label(pos):
    dir_ = (pos.get("direction") or pos.get("side") or "").lower()
    dir_text = "short" if dir_ == "short" else "long"
    raw_ts = str(pos.get("trade_style") or "").strip().lower()
    is_generic = raw_ts in GENERIC_TRADE_STYLE_KEYS
    style = (
        (not is_generic and humanize_style(pos.get("trade_style")))
        or humanize_style(pos.get("setup_variant"))
        or humanize_style(pos.get("setup_type"))
        or humanize_style(pos.get("scan_tier"))
        or humanize_style(pos.get("timeframe"))
    )
    if not style:
        return dir_text.upper()
    return f"{style} {dir_text}"


# ───── operator-reported regressions (Feb 2026) ─────
def test_cf_reconciled_orphan_renders_as_adopted():
    """CF: trade_style=trade_2_hold, setup_type=reconciled_orphan
    → before: "DAY 2 short"   ❌
    → after:  "ADOPTED short" ✅"""
    pos = {
        "symbol": "CF", "direction": "short",
        "trade_style": "trade_2_hold",
        "setup_variant": "",
        "setup_type": "reconciled_orphan",
        "scan_tier": "reconciled",
        "timeframe": "intraday",
    }
    assert tier_label(pos) == "ADOPTED short"


def test_intu_mean_reversion_renders_as_mean_rev():
    """INTU: setup_variant=mean_reversion_long
    → before: "DAY 2 long"     ❌
    → after:  "MEAN REV long"  ✅"""
    pos = {
        "symbol": "INTU", "direction": "long",
        "trade_style": "trade_2_hold",
        "setup_variant": "mean_reversion_long",
        "setup_type": "mean_reversion_long",
        "scan_tier": "intraday",
        "timeframe": "intraday",
    }
    assert tier_label(pos) == "MEAN REV long"


def test_c_squeeze_renders_as_squeeze():
    """C: setup_variant=squeeze → "SQUEEZE short" (via fallback truncation)."""
    pos = {
        "symbol": "C", "direction": "short",
        "trade_style": "trade_2_hold",
        "setup_variant": "squeeze",
        "setup_type": "squeeze",
        "scan_tier": "swing",
        "timeframe": "swing",
    }
    assert tier_label(pos) == "SQUEEZE short"


def test_aep_accumulation_entry_renders_as_accum():
    """AEP: setup_variant=accumulation_entry → "ACCUM long"."""
    pos = {
        "symbol": "AEP", "direction": "long",
        "trade_style": "trade_2_hold",
        "setup_variant": "accumulation_entry",
        "setup_type": "accumulation_entry",
        "scan_tier": "position",
        "timeframe": "position",
    }
    assert tier_label(pos) == "ACCUM long"


# ───── SMB style classifications must never appear as the chip ─────
def test_trade_2_hold_never_appears_as_label():
    """The string "DAY 2" must NEVER come from `trade_2_hold` alone."""
    pos = {
        "direction": "long",
        "trade_style": "trade_2_hold",
        "setup_variant": "accumulation_entry",
    }
    label = tier_label(pos)
    assert "DAY 2" not in label
    assert label == "ACCUM long"


def test_move_2_move_falls_through():
    pos = {
        "direction": "short",
        "trade_style": "move_2_move",
        "setup_variant": "9_ema_scalp",
    }
    assert tier_label(pos) == "9-EMA short"


def test_a_plus_falls_through():
    pos = {
        "direction": "long",
        "trade_style": "a_plus",
        "setup_variant": "earnings_momentum",
    }
    assert tier_label(pos) == "EARN MOM long"


def test_trade_2_continuation_falls_through():
    pos = {
        "direction": "long",
        "trade_style": "trade_2_continuation",
        "setup_variant": "vwap_continuation",
    }
    assert tier_label(pos) == "VWAP long"


# ───── legit Day-2 setups SHOULD still render as "DAY 2" ─────
def test_day_2_continuation_setup_still_renders_as_day_2():
    """Linda Raschke's Day-2 continuation pattern is a real setup name —
    when it shows up in setup_variant, "DAY 2" IS the correct chip."""
    pos = {
        "direction": "long",
        "trade_style": "trade_2_hold",
        "setup_variant": "day_2_continuation",
    }
    assert tier_label(pos) == "DAY 2 long"


def test_day_2_failure_setup_still_renders():
    pos = {
        "direction": "short",
        "trade_style": "trade_2_hold",
        "setup_variant": "day_2_failure",
    }
    assert tier_label(pos) == "DAY 2 FAIL short"


# ───── non-generic trade_style is still preferred when valid ─────
def test_non_generic_trade_style_wins():
    """When trade_style is a real setup name (e.g. legacy data),
    it should win over setup_variant."""
    pos = {
        "direction": "long",
        "trade_style": "squeeze",
        "setup_variant": "accumulation_entry",
    }
    assert tier_label(pos) == "SQUEEZE long"


# ───── empty / unknown handling ─────
def test_empty_string_setup_variant_falls_through():
    """Empty-string setup_variant (the CF case) must not block the chain."""
    pos = {
        "direction": "long",
        "trade_style": "trade_2_hold",
        "setup_variant": "",
        "setup_type": "reconciled_orphan",
    }
    assert tier_label(pos) == "ADOPTED long"


def test_nothing_set_returns_direction_only():
    pos = {"direction": "long"}
    assert tier_label(pos) == "LONG"


def test_short_with_no_setup_returns_SHORT():
    pos = {"direction": "short"}
    assert tier_label(pos) == "SHORT"


def test_unknown_setup_truncates_to_12():
    pos = {
        "direction": "long",
        "trade_style": "trade_2_hold",
        "setup_variant": "this_is_a_really_long_made_up_name",
    }
    label = tier_label(pos)
    # "THIS IS A RE" — 12 chars, then " long"
    assert label.endswith(" long")
    assert len(label.split(" long")[0]) <= 12
