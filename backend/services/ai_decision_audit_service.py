"""
AI Decision Audit Service

Extracts per-trade audit data from `bot_trades.entry_context.ai_modules`
for the V5 dashboard's AIDecisionAuditCard.

The card needs to answer one operator question at a glance:
  *"For each closed trade, what did each AI module say, and was that
   module's signal aligned with the actual P&L outcome?"*

We normalize each module's raw verdict into a small enum
(`bullish` | `bearish` | `neutral` | `abstain`) and compare against
the binary trade outcome (win/loss) to compute an alignment flag.
Aggregated across N trades, this gives a clean per-module
"conviction quality" score that complements the shadow-tracker
accuracy metric (which measures recommendation correctness, not
P&L outcome alignment).

Schema returned per trade:
{
  "trade_id": "t_abc123",
  "symbol": "AAPL",
  "setup_type": "BREAKOUT",
  "direction": "long",
  "opened_at": "2026-04-29T13:30:00+00:00",
  "closed_at": "2026-04-29T15:45:00+00:00",
  "pnl_pct": 1.42,
  "win": True,
  "close_reason": "target_2",
  "modules": {
    "debate":         {"verdict": "bullish", "raw": "PROCEED",  "aligned": True},
    "risk_manager":   {"verdict": "bullish", "raw": "APPROVE",  "aligned": True},
    "institutional":  {"verdict": "bullish", "raw": "BULLISH",  "aligned": True},
    "time_series":    {"verdict": "bearish", "raw": "DOWN",     "aligned": False},
  },
  "consulted_count": 4,
  "aligned_count":   3,
}

Plus a top-level summary:
{
  "trades": [...],
  "summary": {
    "total_trades": 42,
    "win_rate": 0.71,
    "per_module": {
      "debate":   {"trades": 41, "aligned": 30, "alignment_rate": 0.73},
      ...
    }
  }
}
"""

from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


# Verdict normalisation — best-effort mapping of the rich strings
# the consultation pipeline emits to a small directional enum.
_BULLISH_KEYWORDS = (
    "proceed", "approve", "execute", "buy", "long", "bull", "trade_yes",
    "go_long", "favor_long", "up", "bullish",
)
_BEARISH_KEYWORDS = (
    "pass", "skip", "reject", "block", "avoid", "no_trade", "short",
    "bear", "down", "bearish", "trade_no",
)
_NEUTRAL_KEYWORDS = (
    "neutral", "hold", "mixed", "unclear", "low_confidence", "abstain",
)


def _normalise_verdict(raw: str) -> str:
    """Map a free-form verdict string into {bullish, bearish, neutral, abstain}."""
    if not raw:
        return "abstain"
    s = str(raw).lower()
    # Bearish takes precedence over bullish to handle "no_trade" / "no_go"
    # which contain bullish-like substrings (`trade`, `go`).
    if any(k in s for k in _BEARISH_KEYWORDS):
        return "bearish"
    if any(k in s for k in _BULLISH_KEYWORDS):
        return "bullish"
    if any(k in s for k in _NEUTRAL_KEYWORDS):
        return "neutral"
    return "abstain"


def _extract_module_verdict(module_data: Any) -> str:
    """Find the most-meaningful verdict string in a module sub-dict.

    Each module stores its result with a slightly different key —
    debate uses `final_recommendation` / `winner`, risk uses
    `recommendation`, institutional uses `flow_direction` /
    `recommendation`, timeseries uses `direction` (inside `forecast`
    or at the top). Walk the priority order, return the first match.
    """
    if not isinstance(module_data, dict):
        return ""
    # Walk known field names in priority order.
    for key in (
        "final_recommendation",
        "recommendation",
        "verdict",
        "signal",
        "winner",
        "flow_direction",
        "direction",
        "trend",
    ):
        v = module_data.get(key)
        if v:
            return str(v)
    # Time-series sometimes nests forecast.direction one level deeper.
    forecast = module_data.get("forecast")
    if isinstance(forecast, dict):
        v = forecast.get("direction")
        if v:
            return str(v)
    return ""


def _compute_alignment(verdict: str, win: bool) -> bool:
    """A module's verdict is "aligned" with the outcome when:
      - bullish verdict + winning trade  → aligned
      - bearish verdict + losing trade   → aligned (dissenter was right)
      - neutral / abstain                → not aligned (no opinion)
    """
    if verdict == "bullish":
        return bool(win)
    if verdict == "bearish":
        return not bool(win)
    return False


def _is_winning_trade(trade: Dict[str, Any]) -> bool:
    """A trade is a "win" iff net P&L (after commissions) is positive."""
    net = trade.get("net_pnl")
    if net is not None:
        return net > 0
    pnl = trade.get("realized_pnl") or trade.get("pnl_pct") or 0
    return pnl > 0


def _extract_module_confidence(module_data: Any):
    """Find the module's self-reported confidence — top-level first,
    nested inside `forecast` for time-series."""
    if not isinstance(module_data, dict):
        return None
    conf = module_data.get("confidence")
    if conf is not None:
        return conf
    forecast = module_data.get("forecast")
    if isinstance(forecast, dict):
        return forecast.get("confidence")
    return None


def _build_audit_row(trade: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the per-trade audit row from a `bot_trades` document."""
    entry_ctx = trade.get("entry_context") or {}
    ai_modules = entry_ctx.get("ai_modules") or {}
    win = _is_winning_trade(trade)

    # Map source-key → display-key so the frontend doesn't need to
    # know the internal nesting.
    module_keymap = (
        ("debate",             "debate"),
        ("risk_manager",       "risk_manager"),
        ("institutional_flow", "institutional"),
        ("time_series",        "time_series"),
    )

    modules: Dict[str, Dict[str, Any]] = {}
    consulted_count = 0
    aligned_count = 0

    for src_key, out_key in module_keymap:
        mod = ai_modules.get(src_key)
        raw = _extract_module_verdict(mod)
        verdict = _normalise_verdict(raw)
        aligned = _compute_alignment(verdict, win)

        modules[out_key] = {
            "verdict":   verdict,
            "raw":       raw or "",
            "aligned":   aligned,
            # Confidence — surface the module's own self-reported
            # confidence when available. Time-series nests it inside
            # `forecast`; others put it at the top.
            "confidence": _extract_module_confidence(mod),
        }

        if mod:
            consulted_count += 1
        if aligned:
            aligned_count += 1

    return {
        "trade_id":         trade.get("id"),
        "symbol":           trade.get("symbol"),
        "setup_type":       trade.get("setup_type"),
        "direction":        trade.get("direction"),
        "opened_at":        trade.get("executed_at") or trade.get("created_at"),
        "closed_at":        trade.get("closed_at"),
        "pnl_pct":          trade.get("pnl_pct"),
        "net_pnl":          trade.get("net_pnl") or trade.get("realized_pnl") or 0,
        "win":              win,
        "close_reason":     trade.get("close_reason"),
        "modules":          modules,
        "consulted_count":  consulted_count,
        "aligned_count":    aligned_count,
    }


def compute_ai_decision_audit(
    db,
    limit: int = 30,
) -> Dict[str, Any]:
    """Build the audit dataset for the V5 AIDecisionAuditCard.

    Pulls the most recent `limit` closed trades from `bot_trades` and
    extracts per-module verdicts + outcome alignment. Returns both the
    per-trade rows AND a per-module summary so the frontend can render
    a header strip without re-aggregating.
    """
    if db is None:
        return {"trades": [], "summary": {"total_trades": 0, "win_rate": 0,
                                          "per_module": {}}}

    cursor = (
        db["bot_trades"]
        .find(
            {"status": "closed"},
            {"_id": 0},
        )
        .sort("closed_at", -1)
        .limit(int(limit))
    )

    rows: List[Dict[str, Any]] = []
    per_module_stats: Dict[str, Dict[str, int]] = {}
    win_count = 0

    for trade in cursor:
        try:
            row = _build_audit_row(trade)
        except Exception as e:
            logger.warning(f"Audit row extraction failed for trade {trade.get('id')}: {e}")
            continue

        rows.append(row)
        if row["win"]:
            win_count += 1

        for mod_name, mod_data in row["modules"].items():
            stats = per_module_stats.setdefault(
                mod_name, {"trades": 0, "aligned": 0, "consulted": 0}
            )
            stats["trades"] += 1
            if mod_data["raw"]:
                stats["consulted"] += 1
            if mod_data["aligned"]:
                stats["aligned"] += 1

    total = len(rows)
    summary = {
        "total_trades": total,
        "win_rate": (win_count / total) if total > 0 else 0.0,
        "per_module": {
            mod: {
                "trades":         s["trades"],
                "consulted":      s["consulted"],
                "aligned":        s["aligned"],
                "alignment_rate": (s["aligned"] / s["consulted"]) if s["consulted"] > 0 else 0.0,
            }
            for mod, s in per_module_stats.items()
        },
    }

    return {"trades": rows, "summary": summary}
