"""
portfolio_exposure_guard.py  ·  v19.34.96
─────────────────────────────────────────────────────────────────────────────
Portfolio-level exposure cap for long-horizon trade styles.

Rationale: scalp / intraday positions auto-recycle within the trading day, so
exposure naturally bounds itself. Position-style trades (Weinstein Stage 2,
golden cross, 200DMA reclaim, etc.) hold for weeks to months — without a
portfolio-level cap a single bullish month could pile 6-8 simultaneous
multi-month bets at 10% account each, leaving zero buying power for scalp /
intraday opportunities and concentrating risk into one regime call.

This service computes how much capital is CURRENTLY tied up in open
position-style trades and what remains available before the cap is breached.

Default cap: 30% of account value across all open POSITION-style trades.
Override per environment via PORTFOLIO_POSITION_EXPOSURE_CAP_PCT.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# Default cap — 30% of account across all simultaneously-open
# position-style trades. Configurable via env var.
DEFAULT_POSITION_EXPOSURE_CAP_PCT: float = float(
    os.environ.get("PORTFOLIO_POSITION_EXPOSURE_CAP_PCT", "30.0")
)

# Trade styles that count toward the "position" exposure bucket.
# v19.34.95 added SWING/INVESTMENT/POSITION enum members; only POSITION
# is rate-limited by default (longest hold horizon). Operators can
# include INVESTMENT by passing a custom `styles` set to compute().
POSITION_STYLES: frozenset = frozenset({"position"})


@dataclass
class ExposureSnapshot:
    """Snapshot of current portfolio exposure to a trade-style bucket."""
    account_value: float
    cap_pct: float                       # e.g., 30.0
    cap_value: float                     # account_value * cap_pct / 100
    current_value: float                 # sum of open style-exposure
    current_pct: float                   # current_value / account_value * 100
    remaining_value: float               # max(0, cap_value - current_value)
    remaining_pct: float                 # max(0, cap_pct - current_pct)
    open_trades_count: int               # number of trades counted
    cap_breached: bool                   # current_value >= cap_value
    breakdown: List[Dict[str, Any]]      # per-trade detail
    styles_counted: List[str]            # which styles were included

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_value": round(self.account_value, 2),
            "cap_pct": self.cap_pct,
            "cap_value": round(self.cap_value, 2),
            "current_value": round(self.current_value, 2),
            "current_pct": round(self.current_pct, 2),
            "remaining_value": round(self.remaining_value, 2),
            "remaining_pct": round(self.remaining_pct, 2),
            "open_trades_count": self.open_trades_count,
            "cap_breached": self.cap_breached,
            "breakdown": self.breakdown,
            "styles_counted": self.styles_counted,
        }


def _get(obj: Any, attr: str, default: Any = None) -> Any:
    """Support both dataclass-like and dict-like trade objects."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _trade_style_of(trade: Any) -> str:
    """Extract a normalized trade_style string from a trade.

    Falls back gracefully if the field is missing. Empty string → ignored.
    """
    style = _get(trade, "trade_style", "") or ""
    return str(style).strip().lower()


def _open_value_of(trade: Any) -> float:
    """Current dollar exposure of a single open trade.

    Prefers `remaining_shares * current_price`. Falls back to entry_price
    or shares if needed.
    """
    remaining = _get(trade, "remaining_shares", None)
    if remaining is None or remaining == 0:
        remaining = _get(trade, "shares", 0) or 0
    try:
        remaining = int(remaining)
    except (TypeError, ValueError):
        return 0.0
    if remaining <= 0:
        return 0.0
    px = (
        _get(trade, "current_price", None)
        or _get(trade, "last_price", None)
        or _get(trade, "entry_price", None)
        or 0.0
    )
    try:
        px = float(px)
    except (TypeError, ValueError):
        return 0.0
    if px <= 0:
        return 0.0
    return remaining * px


def compute_exposure(
    open_trades: Iterable[Any],
    account_value: float,
    cap_pct: Optional[float] = None,
    styles: Optional[Iterable[str]] = None,
) -> ExposureSnapshot:
    """Compute current exposure to position-style trades vs the cap.

    Args:
        open_trades : iterable of trade objects (BotTrade or dicts). Each
            should have `trade_style`, `remaining_shares`, and a price field
            (`current_price` preferred, `entry_price` fallback).
        account_value : current portfolio value (cash + securities).
        cap_pct : override the default 30% cap. Pass e.g. 25.0 to tighten.
        styles : override which styles count. Default: POSITION_STYLES.

    Returns:
        ExposureSnapshot with cap state + per-trade breakdown.
    """
    cap_pct = float(cap_pct if cap_pct is not None else DEFAULT_POSITION_EXPOSURE_CAP_PCT)
    style_set = {s.lower() for s in (styles or POSITION_STYLES)}
    if account_value <= 0:
        return ExposureSnapshot(
            account_value=account_value, cap_pct=cap_pct, cap_value=0.0,
            current_value=0.0, current_pct=0.0,
            remaining_value=0.0, remaining_pct=0.0,
            open_trades_count=0, cap_breached=False,
            breakdown=[], styles_counted=sorted(style_set),
        )

    breakdown: List[Dict[str, Any]] = []
    total_value = 0.0
    counted = 0
    for trade in open_trades or []:
        style = _trade_style_of(trade)
        if style not in style_set:
            continue
        value = _open_value_of(trade)
        if value <= 0:
            continue
        breakdown.append({
            "symbol": _get(trade, "symbol", ""),
            "setup_type": _get(trade, "setup_type", ""),
            "trade_style": style,
            "remaining_shares": _get(trade, "remaining_shares", _get(trade, "shares", 0)),
            "value": round(value, 2),
            "pct_of_account": round(value / account_value * 100, 2),
        })
        total_value += value
        counted += 1

    cap_value = account_value * cap_pct / 100.0
    current_pct = total_value / account_value * 100.0
    remaining_value = max(0.0, cap_value - total_value)
    remaining_pct = max(0.0, cap_pct - current_pct)

    return ExposureSnapshot(
        account_value=account_value,
        cap_pct=cap_pct,
        cap_value=cap_value,
        current_value=total_value,
        current_pct=current_pct,
        remaining_value=remaining_value,
        remaining_pct=remaining_pct,
        open_trades_count=counted,
        cap_breached=total_value >= cap_value,
        breakdown=breakdown,
        styles_counted=sorted(style_set),
    )


def max_additional_shares(
    snapshot: ExposureSnapshot,
    entry_price: float,
) -> int:
    """Given an exposure snapshot and a planned entry, return the maximum
    number of additional shares that can be bought without breaching the cap.

    Returns 0 if cap already breached or entry_price invalid.
    """
    if entry_price <= 0:
        return 0
    if snapshot.cap_breached or snapshot.remaining_value <= 0:
        return 0
    return int(snapshot.remaining_value // entry_price)
