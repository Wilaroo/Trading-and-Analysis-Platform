"""v19.34.41 — Proactive Coach Service.

Runs every 60s in the background. For each open trade, evaluates a small
set of coachable conditions and emits ready-to-fire suggestions the
frontend (or chat AI) can surface to the operator with a one-tap accept.

Suggestion types
────────────────
  • move_stop_to_breakeven  — long ≥ +1R from entry AND stop still below
                              entry; suggest moving stop to entry price.
                              Mirrors for shorts (≥ +1R AND stop above
                              entry → move stop to entry).
  • tighten_stop_runner     — position ≥ +2R; suggest trailing stop to
                              `current ± 0.5R` so half the runner gain
                              is locked in.
  • take_partial_winner     — current price within 0.5% of first target
                              AND remaining shares ≥ 2; suggest partial
                              close for half (operator-tunable later).
  • stop_proximity_warning  — current within 0.5% of stop. Info only —
                              no action attached. Lets the operator
                              decide whether to widen, tighten, or exit.

Each suggestion has:
  - id: f"{trade_id}::{suggestion_type}"  (idempotent key)
  - severity: info | suggest | warn
  - headline: short UI string
  - rationale: longer explanation
  - proposed_action: dict ready for POST /api/trading-bot/adjust-trade
                     (None for info-only)

The service is purely computational + a tiny in-memory cache. No DB
writes — suggestions expire after `SUGGESTION_TTL_S` so a stale "move
stop to BE" doesn't linger after the operator already moved it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# How often the background loop scans open trades.
SCAN_INTERVAL_S = 60
# How long a suggestion lingers in the in-memory cache before re-eval.
SUGGESTION_TTL_S = 600
# Tolerance windows.
TARGET_PROXIMITY_PCT = 0.005   # 0.5%
STOP_PROXIMITY_PCT = 0.005     # 0.5%


@dataclass
class CoachSuggestion:
    id: str
    trade_id: str
    symbol: str
    suggestion_type: str
    severity: str           # "info" | "suggest" | "warn"
    headline: str
    rationale: str
    proposed_action: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)


def _direction(trade) -> str:
    """Normalize BotTrade.direction to 'long' or 'short'."""
    d = trade.direction
    return d.value.lower() if hasattr(d, "value") else str(d).lower()


def _r_progress(trade) -> Optional[float]:
    """Current P&L expressed in R-multiples. None if math doesn't work."""
    entry = float(getattr(trade, "fill_price", None) or getattr(trade, "entry_price", 0))
    stop = float(getattr(trade, "stop_price", 0) or 0)
    current = float(getattr(trade, "current_price", 0) or 0)
    if entry <= 0 or stop <= 0 or current <= 0 or stop == entry:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    direction = _direction(trade)
    if direction == "long":
        return (current - entry) / risk
    return (entry - current) / risk


def evaluate_trade(trade) -> List[CoachSuggestion]:
    """Pure-function evaluator. Caller passes a BotTrade-shaped object;
    returns 0+ suggestions.
    """
    out: List[CoachSuggestion] = []
    if (getattr(trade, "shares", 0) or 0) <= 0:
        return out

    direction = _direction(trade)
    entry = float(getattr(trade, "fill_price", None) or getattr(trade, "entry_price", 0))
    stop = float(getattr(trade, "stop_price", 0) or 0)
    current = float(getattr(trade, "current_price", 0) or 0)
    targets = list(getattr(trade, "target_prices", None) or [])
    r_progress = _r_progress(trade)

    # ── 1. move stop to breakeven ────────────────────────────────────────
    if r_progress is not None and r_progress >= 1.0:
        stop_below_be = direction == "long" and stop < entry
        stop_above_be = direction == "short" and stop > entry
        if stop_below_be or stop_above_be:
            out.append(CoachSuggestion(
                id=f"{trade.id}::move_stop_to_breakeven",
                trade_id=trade.id,
                symbol=trade.symbol,
                suggestion_type="move_stop_to_breakeven",
                severity="suggest",
                headline=f"{trade.symbol} up {r_progress:.1f}R — move stop to breakeven?",
                rationale=(
                    f"Position is {r_progress:.1f}R in profit. "
                    f"Moving stop from ${stop:.2f} to entry (${entry:.2f}) "
                    f"locks in a free trade — worst case is now scratch, not loss."
                ),
                proposed_action={
                    "endpoint": "/api/trading-bot/adjust-trade",
                    "payload": {
                        "trade_id": trade.id,
                        "new_stop": round(entry, 2),
                        "reason": f"coach_breakeven_{r_progress:.1f}R",
                    },
                },
            ))

    # ── 2. tighten runner past 2R ────────────────────────────────────────
    if r_progress is not None and r_progress >= 2.0 and stop > 0:
        risk = abs(entry - stop)
        # Trail to "current ± 0.5R" — locks half the gain past 2R.
        if direction == "long":
            new_stop = round(current - (risk * 0.5), 2)
            still_room = new_stop > stop and new_stop < current
        else:
            new_stop = round(current + (risk * 0.5), 2)
            still_room = new_stop < stop and new_stop > current
        if still_room:
            out.append(CoachSuggestion(
                id=f"{trade.id}::tighten_stop_runner",
                trade_id=trade.id,
                symbol=trade.symbol,
                suggestion_type="tighten_stop_runner",
                severity="suggest",
                headline=(
                    f"{trade.symbol} up {r_progress:.1f}R — trail stop to "
                    f"${new_stop:.2f}? (locks ~half the runner)"
                ),
                rationale=(
                    f"Past 2R, tightening to ½R behind current locks in "
                    f"~{(r_progress - 0.5):.1f}R of profit while still "
                    f"giving the position room for the next leg."
                ),
                proposed_action={
                    "endpoint": "/api/trading-bot/adjust-trade",
                    "payload": {
                        "trade_id": trade.id,
                        "new_stop": new_stop,
                        "reason": f"coach_runner_{r_progress:.1f}R",
                    },
                },
            ))

    # ── 3. partial profit at first target ────────────────────────────────
    if targets and current > 0 and (trade.shares or 0) >= 2:
        first_target = float(targets[0])
        proximity = abs(current - first_target) / first_target
        approaching = proximity <= TARGET_PROXIMITY_PCT and (
            (direction == "long" and current >= first_target * (1 - TARGET_PROXIMITY_PCT))
            or (direction == "short" and current <= first_target * (1 + TARGET_PROXIMITY_PCT))
        )
        if approaching:
            half = max(1, int(trade.shares) // 2)
            out.append(CoachSuggestion(
                id=f"{trade.id}::take_partial_winner",
                trade_id=trade.id,
                symbol=trade.symbol,
                suggestion_type="take_partial_winner",
                severity="suggest",
                headline=f"{trade.symbol} approaching first target ${first_target:.2f} — take {half} shares off?",
                rationale=(
                    f"Within {TARGET_PROXIMITY_PCT * 100:.1f}% of first target. "
                    f"Locking in {half} of {trade.shares} shares de-risks the "
                    f"position and lets the rest run on a free trade."
                ),
                proposed_action={
                    "endpoint": "/api/trading-bot/adjust-trade",
                    "payload": {
                        "trade_id": trade.id,
                        "partial_close_shares": half,
                        "reason": "coach_partial_at_target",
                    },
                },
            ))

    # ── 4. stop proximity warning (no action — operator decides) ─────────
    if stop > 0 and current > 0:
        proximity = abs(current - stop) / current
        approaching_stop = proximity <= STOP_PROXIMITY_PCT and (
            (direction == "long" and current <= stop * (1 + STOP_PROXIMITY_PCT))
            or (direction == "short" and current >= stop * (1 - STOP_PROXIMITY_PCT))
        )
        if approaching_stop:
            out.append(CoachSuggestion(
                id=f"{trade.id}::stop_proximity_warning",
                trade_id=trade.id,
                symbol=trade.symbol,
                suggestion_type="stop_proximity_warning",
                severity="warn",
                headline=f"{trade.symbol} within {STOP_PROXIMITY_PCT * 100:.1f}% of stop ${stop:.2f}",
                rationale=(
                    f"Current ${current:.2f} is hugging the stop. "
                    f"Decide now: widen if your thesis is intact, tighten "
                    f"if momentum is fading, or take the loss cleanly."
                ),
                proposed_action=None,
            ))

    return out


# ─────────────────────────── runtime loop ───────────────────────────


class ProactiveCoachService:
    """Singleton holding the latest snapshot of suggestions per trade.

    Suggestions live in `self._suggestions` keyed by the suggestion `id`.
    Stale entries (no longer applicable on the next scan, or older than
    SUGGESTION_TTL_S) are dropped. Each scan rebuilds from open trades.
    """

    _instance: Optional["ProactiveCoachService"] = None

    @classmethod
    def get(cls) -> "ProactiveCoachService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._suggestions: Dict[str, CoachSuggestion] = {}
        self._task: Optional[asyncio.Task] = None
        self._last_scan_at: Optional[float] = None

    def all(self) -> List[Dict[str, Any]]:
        """Snapshot for the REST endpoint. Returns plain dicts."""
        now = time.time()
        return [
            asdict(s) for s in self._suggestions.values()
            if now - s.created_at <= SUGGESTION_TTL_S
        ]

    def scan_once(self, bot) -> int:
        """Single scan over open trades. Returns suggestion count."""
        if bot is None:
            return 0
        trades = list((getattr(bot, "_open_trades", None) or {}).values())
        fresh: Dict[str, CoachSuggestion] = {}
        for t in trades:
            try:
                for s in evaluate_trade(t):
                    fresh[s.id] = s
            except Exception:
                logger.warning(
                    "Proactive coach: evaluate_trade failed for %s",
                    getattr(t, "id", "?"), exc_info=True,
                )
        self._suggestions = fresh
        self._last_scan_at = time.time()
        return len(fresh)

    async def run_loop(self, bot_provider):
        """Background loop. `bot_provider` is a callable returning the
        TradingBotService singleton (or None during boot)."""
        logger.info("Proactive coach loop starting (every %ds)", SCAN_INTERVAL_S)
        while True:
            try:
                bot = bot_provider() if callable(bot_provider) else bot_provider
                if bot is not None:
                    n = self.scan_once(bot)
                    logger.debug("Proactive coach: %d suggestions live", n)
            except Exception:
                logger.warning("Proactive coach loop iteration failed", exc_info=True)
            await asyncio.sleep(SCAN_INTERVAL_S)

    def start(self, bot_provider):
        if self._task and not self._task.done():
            return
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self.run_loop(bot_provider))


def get_proactive_coach() -> ProactiveCoachService:
    return ProactiveCoachService.get()
