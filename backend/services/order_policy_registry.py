"""
order_policy_registry.py  ·  v19.34.100
─────────────────────────────────────────────────────────────────────────────
Central truth for per-trade-style order management policies.

Every long-horizon style addition we shipped in v19.34.95 (swing /
investment / position) needs distinct order-management rules vs the
scalp/intraday execution code path we hardened in v19.34.85-94:

  • Time-in-force        — DAY for intraday, GTC for multi-day+
  • Outside-RTH          — false for short-horizon, true for long-horizon
  • Bracket structure    — single TP for scalp, ladder for longer holds
  • Stop trail anchor    — ATR vs EMA vs SMA vs weekly SMA
  • EOD sweep behavior   — close-at-EOD vs hold-overnight
  • Cancellation policy  — sweep-eligible vs protected

Every executor / EOD sweep / stop-manager that needs to make a
style-aware decision goes through this module rather than duplicating
the rules. Single source of truth → no policy drift.

Mirrors:
  - SETUP_REGISTRY (smb_integration.py) for style → setup mapping
  - portfolio_exposure_guard.{POSITION_STYLES, LONG_HORIZON_STYLES}
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass
class TpLadderRung:
    """One rung of a profit-taking ladder.

    pct_of_position : 0.0-1.0 fraction of position to close
    r_multiple      : reward-to-risk threshold (target = entry + r * stop_distance)
    """
    pct_of_position: float
    r_multiple: float


@dataclass(frozen=True)
class OrderPolicy:
    """Per-trade-style order management policy."""
    style: str

    # ───── Time-in-force ────────────────────────────────────────────
    # DAY orders auto-expire at session close (clean intraday).
    # GTC orders persist until filled / cancelled (multi-session holds).
    time_in_force: str = "DAY"
    outside_rth: bool = False

    # ───── Bracket structure ────────────────────────────────────────
    # Profit-taking ladder. Single-rung lists give one TP; multi-rung
    # lists scale-out across multiple R-multiples. Sum of pct must = 1.0.
    tp_ladder: List[TpLadderRung] = field(default_factory=lambda: [TpLadderRung(1.0, 2.0)])

    # ───── Stop management ──────────────────────────────────────────
    # Where the trailing stop anchors as the trade runs in our favor.
    # Values: "atr", "ema_9", "ema_20", "sma_50", "sma_150", "sma_200",
    #         "structure" (last swing low/high), "fixed" (no trail)
    stop_trail_anchor: str = "atr"
    stop_atr_multiple: float = 1.5         # used when anchor == "atr"
    stop_breakeven_at_r: Optional[float] = None  # move to BE after N×R; None=never

    # ───── EOD sweep behavior ───────────────────────────────────────
    # True  → force-close before bell, sweep orphan brackets at EOD.
    # False → hold overnight, keep brackets, exempt from EOD sweep.
    close_at_eod: bool = True
    eod_sweep_eligible: bool = True       # operator-initiated cancel-all can still cancel manually

    # ───── Operator-facing description ──────────────────────────────
    horizon_label: str = "Same session"
    notes: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["tp_ladder"] = [asdict(r) for r in self.tp_ladder]
        return d


# ─────────────────────────────────────────────────────────────────────
# The registry — five entries + a sane default for unknown styles.
# ─────────────────────────────────────────────────────────────────────
ORDER_POLICIES: Dict[str, OrderPolicy] = {
    "scalp": OrderPolicy(
        style="scalp",
        time_in_force="DAY",
        outside_rth=False,
        tp_ladder=[TpLadderRung(1.0, 1.0)],                # single 1R target
        stop_trail_anchor="atr",
        stop_atr_multiple=0.5,
        stop_breakeven_at_r=0.5,                           # to BE at +0.5R
        close_at_eod=True,
        eod_sweep_eligible=True,
        horizon_label="Minutes – 1 hour",
        notes="Quick in-out. Tight ATR stop, target 1R. Hard close at EOD.",
    ),

    "intraday": OrderPolicy(
        style="intraday",
        time_in_force="DAY",
        outside_rth=False,
        tp_ladder=[                                        # 2-rung ladder
            TpLadderRung(0.5, 2.0),                        # 50% off at +2R
            TpLadderRung(0.5, 5.0),                        # 50% runs to +5R
        ],
        stop_trail_anchor="atr",
        stop_atr_multiple=1.5,
        stop_breakeven_at_r=1.0,
        close_at_eod=True,
        eod_sweep_eligible=True,
        horizon_label="1 – 6 hours",
        notes="Bellafiore intraday swing. Scale out at +2R, runner to +5R. Hard close at EOD.",
    ),

    "multi_day": OrderPolicy(
        style="multi_day",
        time_in_force="GTC",                               # hold overnight
        outside_rth=True,                                  # allow pre/post fills on runners
        tp_ladder=[                                        # 3-rung ladder
            TpLadderRung(0.33, 2.0),
            TpLadderRung(0.33, 5.0),
            TpLadderRung(0.34, 10.0),                      # A+ runner to 10R
        ],
        stop_trail_anchor="ema_20",
        stop_atr_multiple=2.0,                             # initial only
        stop_breakeven_at_r=1.5,
        close_at_eod=False,                                # hold overnight
        eod_sweep_eligible=False,                          # EOD sweep MUST skip
        horizon_label="1 – 5 days",
        notes="Bellafiore A+ conviction hold. Trail on 20-EMA. EOD sweep MUST skip.",
    ),

    "swing": OrderPolicy(
        style="swing",
        time_in_force="GTC",
        outside_rth=True,
        tp_ladder=[                                        # 2-rung ladder
            TpLadderRung(0.5, 2.0),
            TpLadderRung(0.5, 5.0),
        ],
        stop_trail_anchor="ema_20",
        stop_atr_multiple=2.0,
        stop_breakeven_at_r=2.0,
        close_at_eod=False,
        eod_sweep_eligible=False,
        horizon_label="1 – 3 weeks",
        notes="Daily-bar swing. Trail on 20-EMA. Hold through overnight gaps. EOD sweep MUST skip.",
    ),

    "investment": OrderPolicy(
        style="investment",
        time_in_force="GTC",
        outside_rth=True,
        tp_ladder=[                                        # 3-rung ladder
            TpLadderRung(0.3, 3.0),
            TpLadderRung(0.3, 6.0),
            TpLadderRung(0.4, 12.0),                       # 40% runner
        ],
        stop_trail_anchor="sma_50",
        stop_atr_multiple=3.0,
        stop_breakeven_at_r=2.5,
        close_at_eod=False,
        eod_sweep_eligible=False,
        horizon_label="3 weeks – 3 months",
        notes="Investment-tier base/weekly trade. Trail on 50-SMA. Wide stops. EOD sweep MUST skip.",
    ),

    "position": OrderPolicy(
        style="position",
        time_in_force="GTC",
        outside_rth=True,
        tp_ladder=[                                        # 3-rung ladder
            TpLadderRung(0.25, 4.0),
            TpLadderRung(0.25, 8.0),
            TpLadderRung(0.50, 15.0),                      # 50% runner
        ],
        stop_trail_anchor="sma_150",                       # 30-week SMA on daily
        stop_atr_multiple=4.0,
        stop_breakeven_at_r=3.0,
        close_at_eod=False,
        eod_sweep_eligible=False,                          # NEVER sweep
        horizon_label="3+ months",
        notes="Weinstein stage / 200-DMA / golden-cross position. Trail on 30-week SMA. Multi-month conviction. NEVER auto-close.",
    ),
}


# Default policy for unknown / missing styles. Conservative: behaves as
# intraday (DAY orders, close at EOD) so an unmapped style doesn't
# accidentally orphan an overnight bracket.
DEFAULT_POLICY = ORDER_POLICIES["intraday"]


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────
def get_policy(trade_style: Optional[str]) -> OrderPolicy:
    """Look up the order-management policy for a trade style.

    Falls back to DEFAULT_POLICY (intraday) when the style is unknown
    or empty. Case-insensitive; trims whitespace.
    """
    if not trade_style:
        return DEFAULT_POLICY
    key = str(trade_style).strip().lower()
    return ORDER_POLICIES.get(key, DEFAULT_POLICY)


def get_policy_for_trade(trade) -> OrderPolicy:
    """Resolve policy from a BotTrade-shaped object.

    Order of precedence:
      1. `trade.trade_style` if explicitly set
      2. Derived from `trade.setup_type` via SETUP_REGISTRY
      3. DEFAULT_POLICY (intraday) if neither is available
    """
    if trade is None:
        return DEFAULT_POLICY

    def _attr(obj, name, default=None):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    style = _attr(trade, "trade_style")
    if style:
        return get_policy(style)

    setup_type = _attr(trade, "setup_type")
    if setup_type:
        try:
            from services.smb_integration import SETUP_REGISTRY
            cfg = SETUP_REGISTRY.get(str(setup_type).strip().lower())
            if cfg is not None and getattr(cfg, "default_style", None) is not None:
                return get_policy(cfg.default_style.value)
        except Exception:
            pass

    return DEFAULT_POLICY


def is_eod_sweep_eligible(trade) -> bool:
    """True if the bot's EOD orphan-sweep is allowed to cancel this trade's
    pending orders. False for long-horizon styles which need their GTC
    brackets to persist overnight."""
    return get_policy_for_trade(trade).eod_sweep_eligible


def time_in_force_for(trade) -> str:
    """Return the IB time-in-force string ("DAY" or "GTC") for a trade."""
    return get_policy_for_trade(trade).time_in_force


def stop_trail_anchor_for(trade) -> str:
    """Return the indicator the stop should trail on for this trade style."""
    return get_policy_for_trade(trade).stop_trail_anchor


def all_policies_summary() -> Dict[str, Dict]:
    """Return all 6 policies as a dict (for API exposure / debugging)."""
    return {k: v.to_dict() for k, v in ORDER_POLICIES.items()}
