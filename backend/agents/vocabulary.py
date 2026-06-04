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

_STATIC_VOCABULARY_BLOCK = """
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

=== ORDER-MANAGEMENT POLICIES (v19.34.100) ===

Each trade style has a DISTINCT order policy. Bot enforces these
at order placement, stop adjustment, EOD sweep, and cancellation.
Single source of truth: `services/order_policy_registry.py`.

  style       | TIF | Outside-RTH | TP ladder                    | Stop trail   | EOD sweep?
  ──────────────────────────────────────────────────────────────────────────────────────
  scalp       | DAY | no          | 100% @ +1R                   | 0.5 × ATR    | YES
  intraday    | DAY | no          | 50% @ +2R · 50% @ +5R        | 1.5 × ATR    | YES
  multi_day   | GTC | YES         | 33% @ +2R · 33% @ +5R · 34% @ +10R | EMA-20 | NO
  swing       | GTC | YES         | 50% @ +2R · 50% @ +5R        | EMA-20       | NO
  investment  | GTC | YES         | 30% @ +3R · 30% @ +6R · 40% @ +12R | SMA-50 | NO
  position    | GTC | YES         | 25% @ +4R · 25% @ +8R · 50% @ +15R | 30wk-SMA | NO

BREAK-EVEN AUTO-PULL:
  scalp +0.5R · intraday +1R · multi_day +1.5R · swing +2R · investment +2.5R · position +3R

EOD-SWEEP PROTECTION:
  The bot's `cancel-all-pending-orders` endpoint defaults to
  `protect_long_horizon=true`, which SKIPS any pending order attached to
  a multi_day / swing / investment / position trade. Their GTC brackets
  must survive overnight. Operator can override with `false` to flatten
  EVERYTHING (rare escape hatch).

When asked "how do you manage an X trade?" or "what's our stop on a Y
trade?", quote the table above verbatim. Endpoint
`GET /api/trading-bot/order-policies` returns the full machine-readable
spec.

When verified data shows `trade_style` / `setup_type`, USE those words verbatim
in your response. When unclear, ask which horizon the operator is asking about.
""".strip()


# v19.34.270 (m4) — append the SSOT-generated strategy_family × exit_archetype
# section so the NIA/agent vocabulary stays in lock-step with
# services/setup_taxonomy.py and can never drift. Best-effort: if the SSOT is
# unavailable, fall back to the static block only.
try:
    from services.setup_taxonomy import vocabulary_section as _vocab_section
    VOCABULARY_BLOCK = _STATIC_VOCABULARY_BLOCK + "\n\n" + _vocab_section()
except Exception:
    VOCABULARY_BLOCK = _STATIC_VOCABULARY_BLOCK


def inject_vocabulary(base_prompt: str) -> str:
    """Append the shared vocabulary block to an agent's system prompt.

    Idempotent — if the block is already present, returns the prompt unchanged.
    """
    if not base_prompt:
        return VOCABULARY_BLOCK
    if "SENTCOM SHARED VOCABULARY" in base_prompt:
        return base_prompt
    return f"{base_prompt}\n\n{VOCABULARY_BLOCK}"
