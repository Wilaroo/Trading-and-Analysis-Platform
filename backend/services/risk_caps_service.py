"""
Risk Caps Service — single source of TRUTH about the effective risk
caps that actually bind live trades.

Background
----------
Risk parameters are scattered across 6 places in the codebase
(bot_state.risk_params, SafetyGuardrails, PositionSizer,
DynamicRiskEngine, gameplan_service, debate_agents). They've drifted
out of sync over time — for example, on 2026-04-28 the operator's
config showed:

    bot.max_open_positions   = 7    # Mongo bot_state
    safety.max_positions     = 5    # env-driven kill switch
    bot.max_daily_loss_pct   = 1.0  # Mongo bot_state
    safety.max_daily_loss_pct= 2.0  # env-driven kill switch
    safety.max_daily_loss_usd= 500  # env-driven kill switch
    bot.max_daily_loss       = 0    # unset
    bot.max_position_pct     = 50.0 # Mongo bot_state — aggressive
    sizer.max_position_pct   = 10.0 # in-code default

The freshness inspector flagged this with a WARN. The full
"single-source-of-truth" refactor (Option A) is a multi-file change
parked for a later session.

This service ships Option B: a thin helper that resolves all the
overlapping caps to their *effective* (most-restrictive) value. The
goal is twofold:

  1. Make the actual binding cap visible to the operator (UI + API).
  2. Give downstream subsystems a single function to call when they
     need an answer to "what's the actual cap?" — no more duplicated
     min() math sprinkled across files.

Public API
----------
    compute_effective_risk_caps(db) -> dict

    Returns a structured payload with three sub-objects:

    {
      "sources": {
        "bot": {...},        # bot_state.risk_params (Mongo)
        "safety": {...},     # SafetyGuardrailConfig (env)
        "sizer": {...},      # PositionSizer config (in-code)
      },
      "effective": {
        "max_open_positions": 5,         # min(bot=7, safety=5)
        "max_daily_loss_usd": 500.0,     # min(bot.computed=1000, safety=500)
        "max_position_pct": 10.0,        # min(bot=50, sizer=10)
        "min_risk_reward": 2.5,          # bot is the only source
      },
      "conflicts": [                     # human-readable diagnostics
        "max_open_positions: bot=7 vs safety=5 → 5 wins (kill switch stricter)",
        ...
      ],
      "checked_at": "2026-04-29T..."
    }
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.safety_guardrails import SafetyConfig

# In-code defaults that mirror PositionSizer / DynamicRiskEngine —
# kept here as constants so this service has a stable reference even
# if the underlying defaults shift. If you change a default in those
# files, update the matching constant here too.
_POSITION_SIZER_MAX_POSITION_PCT_DEFAULT = 10.0
_DYNAMIC_RISK_DAILY_LOSS_PCT_DEFAULT = 3.0


def _read_bot_risk_params(db) -> Dict[str, Any]:
    """Pull the current `risk_params` from `bot_state`. Returns
    `{}` cleanly when the doc is missing — the resolver handles
    None values explicitly so the operator sees "unset" instead of
    a mystery cap of 0."""
    if db is None:
        return {}
    try:
        # 2026-05-05 v19.34.9 — explicit `_id="bot_state"` filter to
        # guard against stale alternative docs (e.g. legacy `_id="main"`)
        # that may have been written by older bot versions and then
        # become the first match for `find_one({})` when sorted by Mongo
        # natural order. Operator surfaced this as the root cause of
        # `refresh-account` reporting success but `effective-limits`
        # showing stale $100k starting_capital.
        state = db["bot_state"].find_one(
            {"_id": "bot_state"}, {"_id": 0, "risk_params": 1},
        )
        if not state:
            # Fallback: any doc — covers legacy schemas
            state = db["bot_state"].find_one({}, {"_id": 0, "risk_params": 1})
        return (state or {}).get("risk_params") or {}
    except Exception:
        return {}


def _bot_daily_loss_usd(bot: Dict[str, Any]) -> Optional[float]:
    """Bot config can express daily-loss as either an absolute USD or a
    pct of starting capital. Return whichever resolves to a real
    number, or None if neither is set."""
    abs_loss = bot.get("max_daily_loss")
    if abs_loss is not None and abs_loss > 0:
        return float(abs_loss)
    pct = bot.get("max_daily_loss_pct") or 0
    cap = bot.get("starting_capital") or 0
    if pct > 0 and cap > 0:
        return float(pct) * float(cap) / 100.0
    return None


def _min_ignoring_none(*values) -> Optional[float]:
    """Return min() of the truthy non-None values, or None if all are
    missing. Treating 0 as "unset" — risk caps of 0 don't bind anything
    and are almost certainly a config error."""
    pruned = [v for v in values if v is not None and v > 0]
    return min(pruned) if pruned else None


def compute_effective_risk_caps(db) -> Dict[str, Any]:
    """Resolve overlapping risk caps to their effective (most
    restrictive) values across all known sources. See module docstring
    for the full schema.

    This is a *read-only* operation — never mutates any source. Safe
    to call on every request without concern."""
    bot = _read_bot_risk_params(db)
    safety = SafetyConfig.from_env()

    sources = {
        "bot": {
            "max_open_positions": bot.get("max_open_positions"),
            "max_position_pct":   bot.get("max_position_pct"),
            "max_daily_loss":     bot.get("max_daily_loss"),
            "max_daily_loss_pct": bot.get("max_daily_loss_pct"),
            "max_risk_per_trade": bot.get("max_risk_per_trade"),
            "min_risk_reward":    bot.get("min_risk_reward"),
            "starting_capital":   bot.get("starting_capital"),
        },
        "safety": {
            "max_positions":             safety.max_positions,
            "max_daily_loss_usd":        safety.max_daily_loss_usd,
            "max_daily_loss_pct":        safety.max_daily_loss_pct,
            "max_symbol_exposure_usd":   safety.max_symbol_exposure_usd,
            "max_total_exposure_pct":    safety.max_total_exposure_pct,
            "enabled":                   safety.enabled,
        },
        "sizer": {
            "max_position_pct": _POSITION_SIZER_MAX_POSITION_PCT_DEFAULT,
        },
        "dynamic_risk": {
            "max_daily_loss_pct": _DYNAMIC_RISK_DAILY_LOSS_PCT_DEFAULT,
        },
    }

    bot_loss_usd = _bot_daily_loss_usd(bot)

    effective = {
        # Position count: bot vs kill switch — strictest wins.
        "max_open_positions": _min_ignoring_none(
            bot.get("max_open_positions"),
            safety.max_positions,
        ),
        # Position concentration: bot vs sizer — strictest wins.
        "max_position_pct": _min_ignoring_none(
            bot.get("max_position_pct"),
            _POSITION_SIZER_MAX_POSITION_PCT_DEFAULT,
        ),
        # Daily loss in USD — bot can supply absolute OR % of capital;
        # whichever resolves to the smaller number is the operator's
        # intent. Then min against safety's USD cap.
        "max_daily_loss_usd": _min_ignoring_none(
            bot_loss_usd,
            safety.max_daily_loss_usd,
        ),
        # Daily loss in % — bot config + safety + dynamic risk all
        # express it. Stricter = lower percentage.
        "max_daily_loss_pct": _min_ignoring_none(
            bot.get("max_daily_loss_pct"),
            safety.max_daily_loss_pct,
            _DYNAMIC_RISK_DAILY_LOSS_PCT_DEFAULT,
        ),
        # These have a single canonical source today — pass through.
        "min_risk_reward":          bot.get("min_risk_reward"),
        "max_risk_per_trade":       bot.get("max_risk_per_trade"),
        "max_symbol_exposure_usd":  safety.max_symbol_exposure_usd,
        "max_total_exposure_pct":   safety.max_total_exposure_pct,
        # Where each effective cap came from — useful for debugging
        # in the UI ("why is my cap 5 when I set 7?").
        "kill_switch_enabled":      safety.enabled,
    }

    conflicts = _build_conflict_diagnostics(sources, effective, bot_loss_usd)

    return {
        "sources":     sources,
        "effective":   effective,
        "conflicts":   conflicts,
        "checked_at":  datetime.now(timezone.utc).isoformat(),
    }


def _build_conflict_diagnostics(
    sources: Dict[str, Any],
    effective: Dict[str, Any],
    bot_loss_usd: Optional[float],
) -> List[str]:
    """Build human-readable strings explaining each conflict — what
    the UI shows next to the WARN icon. Strings reference the
    underlying source by name so the operator knows where to edit."""
    out: List[str] = []

    bot_pos = sources["bot"]["max_open_positions"]
    safety_pos = sources["safety"]["max_positions"]
    if bot_pos and safety_pos and bot_pos != safety_pos:
        winner = min(bot_pos, safety_pos)
        out.append(
            f"max_open_positions: bot={bot_pos} vs safety={safety_pos} → "
            f"{winner} wins (kill switch stricter)"
        )

    bot_pct = sources["bot"]["max_position_pct"]
    sizer_pct = sources["sizer"]["max_position_pct"]
    if bot_pct and bot_pct > sizer_pct:
        out.append(
            f"max_position_pct: bot={bot_pct}% vs position_sizer={sizer_pct}% → "
            f"{sizer_pct}% wins where sizer enforces"
        )

    if bot_loss_usd is None:
        out.append(
            "max_daily_loss is UNSET in bot config — kill switch's "
            f"${sources['safety']['max_daily_loss_usd']:.0f} is the only "
            f"daily-loss guard"
        )
    elif (
        bot_loss_usd
        and sources["safety"]["max_daily_loss_usd"]
        and bot_loss_usd != sources["safety"]["max_daily_loss_usd"]
    ):
        winner = min(bot_loss_usd, sources["safety"]["max_daily_loss_usd"])
        out.append(
            f"max_daily_loss_usd: bot computed=${bot_loss_usd:.0f} vs "
            f"safety=${sources['safety']['max_daily_loss_usd']:.0f} → "
            f"${winner:.0f} wins (stricter)"
        )

    pct_sources = [
        ("bot",          sources["bot"]["max_daily_loss_pct"]),
        ("safety",       sources["safety"]["max_daily_loss_pct"]),
        ("dynamic_risk", sources["dynamic_risk"]["max_daily_loss_pct"]),
    ]
    pct_values = [(name, pct) for name, pct in pct_sources if pct]
    if len({pct for _, pct in pct_values}) > 1:
        winning_pct = effective["max_daily_loss_pct"]
        winner_name = next((n for n, p in pct_values if p == winning_pct), "?")
        rendered = ", ".join(f"{n}={p}%" for n, p in pct_values)
        out.append(
            f"max_daily_loss_pct: {rendered} → {winning_pct}% wins ({winner_name} stricter)"
        )

    if not sources["safety"]["enabled"]:
        out.append(
            "⚠️ kill switch is DISABLED — only bot-side caps apply (no failsafe)"
        )

    return out
