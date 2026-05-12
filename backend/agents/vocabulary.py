"""
agents/vocabulary.py  ·  v19.34.99
─────────────────────────────────────────────────────────────────────────────
Shared vocabulary reference for every orchestrator-routed agent.

When data flowing into an agent's verified-context section contains:
  - trade_style:   "scalp" | "intraday" | "multi_day" | "swing" | "investment" | "position"
  - setup_type:    one of the 60+ registered setups

…each agent should be able to translate that to human-readable language
without inventing horizons or descriptions. This module holds the canonical
mapping, appended to every agent's system prompt by `inject_vocabulary()`.

Keep this in lock-step with:
  - backend/services/smb_integration.py    (SETUP_REGISTRY)
  - frontend/src/utils/tradeStyleMeta.js   (UI side)
"""

VOCABULARY_BLOCK = """
=== SENTCOM SHARED VOCABULARY (v19.34.95+) ===

5 TRADE STYLES (hold horizons):
  scalp       — Minutes to 1 hour. Target 1R. Auto-recycle intraday.
  intraday    — 1 to 6 hours. Target 3-5R. Auto-recycle intraday.
  multi_day   — 1 to 5 days. Max-conviction Bellafiore A+ hold.
  swing       — 1 to 3 weeks. Daily-bar driven.
  investment  — 3 weeks to 3 months. Weekly/multi-quarter base.
  position    — 3+ months. Weinstein stage / 200-day / golden cross.

PORTFOLIO EXPOSURE CAPS (long-horizon only):
  30% across open trade_style="position" trades.
  55% combined across trade_style in {multi_day, swing, investment, position}.
  Scalp + intraday are immune (recycle intraday). When a trade is blocked
  or downsized, the response carries `exposure_cap_warnings: [...]`.

KEY SETUPS BY HORIZON (subset — full registry has 68):
  Scalp:       rubber_band, hitchhiker, spencer_scalp, bella_fade, gap_fade
  Intraday:    orb, breakout, breakdown, first_vwap_pullback, opening_drive
  Swing:       pocket_pivot, vcp_breakout, three_week_tight, bull_flag_break,
               cup_with_high_handle, ascending_triangle_break
  Investment:  weekly_breakout, multi_quarter_base_break, rs_leader_break,
               fifty_two_week_high_break, power_trend_stack
  Position:    stage_2_breakout, stage_1_to_2_transition,
               stage_3_to_4_breakdown, golden_cross_filtered,
               death_cross_filtered, two_hundred_day_reclaim,
               two_hundred_day_loss, accumulation_entry

When verified data shows `trade_style` / `setup_type`, USE those words verbatim
in your response. When unclear, ask which horizon the operator is asking about.
""".strip()


def inject_vocabulary(base_prompt: str) -> str:
    """Append the shared vocabulary block to an agent's system prompt.

    Idempotent — if the block is already present, returns the prompt unchanged.
    """
    if not base_prompt:
        return VOCABULARY_BLOCK
    if "SENTCOM SHARED VOCABULARY" in base_prompt:
        return base_prompt
    return f"{base_prompt}\n\n{VOCABULARY_BLOCK}"
