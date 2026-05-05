"""
rejection_cooldown_service.py — v19.34.8 (2026-05-05 PM)

Operator-driven safety after the XLU/UPS forensic dump showed
**135 brackets / 0 bot_trades for XLU**:
  - 13:30-13:51: ~12 fills + a few cancels
  - 13:58-15:09 (71 min): **110 brackets, ALL rejected, ALL distinct trade_ids**

Root-cause double-stack:
  (a) `starting_capital=$100k` mock value → bot computed $1k daily-loss
      cap → tripped early → guard rails started rejecting everything.
  (b) NO rejection cooldown — the bot re-evaluated XLU's setup every
      ~30-60s, generated a fresh trade_id with size-pumped-by-current-
      equity (so intent-dedup couldn't catch it via qty/price match),
      and re-fired. Loop ran for 71 minutes accumulating 110 rejections.

Fix (a): operator's manual `POST /api/trading-bot/refresh-account` call
+ future v19.34.8 boot-time auto-refresh.

Fix (b) — THIS MODULE: per-`(symbol, setup_type)` cooldown after a
hard rejection (capital-blocked, max-positions-hit, kill-switch-tripped,
etc.). Re-evaluations during the cooldown window are silently dropped
with a clear log breadcrumb. Cooldown auto-expires after the configured
duration.

Existing `OrderIntentDedup` (services/order_intent_dedup.py) is
COMPLEMENTARY:
  - `OrderIntentDedup` catches ORDER-level spam (same qty±5%, price±0.5%
    within 90s). Useless when qty fluctuates wildly with equity (today's
    XLU pattern: 1845→922→923→463→277).
  - `RejectionCooldown` catches SETUP-level spam (same symbol+setup_type
    after a structural rejection). Designed for today's pattern.

Integration points:
  1. `trade_execution.execute_trade` — at the TOP (before guardrails),
     `is_in_cooldown(symbol, setup_type)` → if yes, abort with VETOED.
  2. `trade_execution.execute_trade` — at the broker-rejection branch
     (line ~580), call `mark_rejection(symbol, setup_type, reason)` if
     the rejection reason is in `STRUCTURAL_REJECTION_REASONS`.

Operator endpoints (added in routers/trading_bot.py):
  GET  /api/trading-bot/rejection-cooldowns
  POST /api/trading-bot/clear-rejection-cooldown
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── v19.34.12 — Rejection event log ────────────────────────────────
# Persistent record of every structural rejection that triggers / extends
# a cooldown. Backs the V5 Diagnostics → "Rejections" sub-tab heatmap
# (Symbol × Setup grid colored by rejection_count, broken down by reason).
#
# Schema-light: persistence failure NEVER blocks the cooldown logic.
# TTL: 7 days (operator-tunable via `bot_state.rejection_events_ttl_days`).

def _persist_rejection_event(
    *,
    symbol: str,
    setup_type: str,
    reason: str,
    rejection_count: int,
    extended: bool,
) -> None:
    """Best-effort sync write of one rejection event to Mongo.

    Called from inside `mark_rejection` (which holds a threading.Lock,
    so we must not await here). Writes are fire-and-forget; a Mongo
    blip is logged at DEBUG and silently dropped — the cooldown still
    works either way.

    The frontend reads from `rejection_events` collection via the
    `/api/trading-bot/rejection-events` aggregation endpoint.
    """
    try:
        from database import get_database
        db = get_database()
        if db is None:
            return
        # Lazy index ensure — idempotent + once-per-process.
        global _rejection_events_indexes_ready
        if not _rejection_events_indexes_ready:
            try:
                db["rejection_events"].create_index(
                    "created_at", expireAfterSeconds=7 * 24 * 60 * 60,
                )
                db["rejection_events"].create_index(
                    [("symbol", 1), ("setup_type", 1), ("created_at", -1)],
                )
                _rejection_events_indexes_ready = True
            except Exception:
                pass  # writes still work without the index
        doc = {
            "symbol": (symbol or "").upper(),
            "setup_type": (setup_type or "").lower(),
            "reason": str(reason),
            "rejection_count": int(rejection_count),
            "extended": bool(extended),
            "created_at": datetime.now(timezone.utc),
        }
        db["rejection_events"].insert_one(doc)
    except Exception as e:
        logger.debug("[v19.34.12 REJECTION-LOG] persist failed: %s", e)


_rejection_events_indexes_ready: bool = False



# Default cooldown window in seconds (configurable per env).
# 5 min is the operator's pick — long enough to cover most "transient"
# rejection-loop windows, short enough that a legit setup recovery
# (e.g., kill-switch reset, account refresh) doesn't permanently shut
# the bot off.
DEFAULT_COOLDOWN_SECONDS = int(os.environ.get("REJECTION_COOLDOWN_SECONDS", "300"))


# Rejection reasons that SHOULD trigger a cooldown. These are
# "structural" — meaning a re-attempt within minutes will almost
# certainly fail the same way.
#
# Match is case-insensitive substring against the rejection reason
# string. Order matters only for logging — first match wins.
STRUCTURAL_REJECTION_REASONS: Tuple[str, ...] = (
    "max_daily_loss",       # bot or safety hit daily loss cap
    "daily loss",           # IB raw / human-readable wording
    "daily_dd_circuit",     # dynamic risk circuit broke
    "max_open_positions",   # at the position-count cap
    "max_positions_hit",
    "max_position_pct",     # single-position size cap
    "max_total_exposure",   # gross book size cap
    "max_symbol_exposure",  # per-symbol concentration cap
    "kill_switch",          # operator-tripped or auto-tripped
    "buying_power",         # IB rejected for insufficient bp
    "insufficient_bp",
    "buying power",         # IB raw error wording
    "account_disabled",
    "kill_switch_tripped",
    "exposure_cap_exceeded",
    "capital_insufficient",
)


# Rejection reasons that should NOT trigger a cooldown — these are
# transient and a retry on the next tick is reasonable.
TRANSIENT_REJECTION_REASONS: Tuple[str, ...] = (
    "stale_quote",
    "no_position_data",
    "execution_exception",  # non-deterministic — let manage-loop retry
    "veto_strategy_phase",
    "intent_already_pending",
    "duplicate_intent",
    "guardrail_veto",       # already gated by execution_guardrails
)


def is_structural_rejection(reason: Optional[str]) -> bool:
    """Classify a broker / guard rejection reason. Substring match,
    case-insensitive. Empty / None → False."""
    if not reason:
        return False
    r = str(reason).lower()
    # Transient wins over structural — if both match, treat as transient
    # to avoid spurious cooldowns on edge cases.
    for token in TRANSIENT_REJECTION_REASONS:
        if token in r:
            return False
    for token in STRUCTURAL_REJECTION_REASONS:
        if token in r:
            return True
    return False


@dataclass
class CooldownEntry:
    symbol: str
    setup_type: str
    reason: str
    started_at: datetime
    expires_at: datetime
    rejection_count: int = 1   # how many rejections this cooldown has seen

    def remaining_seconds(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        return max(0.0, (self.expires_at - now).total_seconds())

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "setup_type": self.setup_type,
            "reason": self.reason,
            "started_at": self.started_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "remaining_seconds": round(self.remaining_seconds(), 1),
            "rejection_count": self.rejection_count,
        }


class RejectionCooldown:
    """Process-wide registry of `(symbol, setup_type)` rejection cooldowns.

    Thread-safe — guarded by a single lock. All public methods are
    O(N) in the cooldown count where N is small (operator-driven, no
    more than a few dozen entries at any time during normal operation).
    """

    def __init__(self, default_cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS):
        self._cooldowns: Dict[str, CooldownEntry] = {}  # key: composite
        self._lock = threading.Lock()
        self._default_cooldown_seconds = int(default_cooldown_seconds)

    # ── helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _key(symbol: str, setup_type: str) -> str:
        return f"{(symbol or '').upper()}|{(setup_type or '').lower()}"

    def _expire_stale(self) -> None:
        """Remove cooldowns whose `expires_at` has passed. Caller holds lock."""
        now = datetime.now(timezone.utc)
        for k in list(self._cooldowns.keys()):
            if self._cooldowns[k].expires_at <= now:
                self._cooldowns.pop(k, None)

    # ── public API ─────────────────────────────────────────────────────
    def is_in_cooldown(
        self, symbol: str, setup_type: str,
    ) -> Optional[CooldownEntry]:
        """Return the active cooldown entry for `(symbol, setup_type)`,
        or None if not in cooldown."""
        if not symbol or not setup_type:
            return None
        with self._lock:
            self._expire_stale()
            return self._cooldowns.get(self._key(symbol, setup_type))

    def mark_rejection(
        self,
        symbol: str,
        setup_type: str,
        reason: str,
        cooldown_seconds: Optional[int] = None,
    ) -> Optional[CooldownEntry]:
        """Record a rejection and start (or extend) the cooldown for
        `(symbol, setup_type)`.

        Returns the active CooldownEntry if a cooldown was set,
        None if `reason` was classified as TRANSIENT (no cooldown).

        If a cooldown is already active for the key, the new rejection
        EXTENDS the cooldown to `now + cooldown_seconds` (whichever is
        later) and increments `rejection_count`. This rate-limits the
        loop further the more it spirals.
        """
        if not symbol or not setup_type:
            return None
        if not is_structural_rejection(reason):
            return None
        # Honor explicit 0 / negative as "no cooldown" without falling
        # through `0 or default` truthiness gotcha.
        if cooldown_seconds is None:
            seconds = int(self._default_cooldown_seconds)
        else:
            seconds = int(cooldown_seconds)
        if seconds <= 0:
            return None

        now = datetime.now(timezone.utc)
        new_expiry = now + timedelta(seconds=seconds)
        key = self._key(symbol, setup_type)

        with self._lock:
            existing = self._cooldowns.get(key)
            if existing is not None and existing.expires_at > now:
                # Extend (use whichever expiry is later) + bump count
                existing.expires_at = max(existing.expires_at, new_expiry)
                existing.reason = str(reason)
                existing.rejection_count += 1
                logger.warning(
                    "[v19.34.8 REJECTION-COOLDOWN] %s/%s extended — "
                    "rejection #%d, reason=%s, total_window=%ds",
                    symbol, setup_type,
                    existing.rejection_count, reason,
                    int((existing.expires_at - existing.started_at).total_seconds()),
                )
                _persist_rejection_event(
                    symbol=symbol, setup_type=setup_type, reason=str(reason),
                    rejection_count=existing.rejection_count, extended=True,
                )
                return existing
            entry = CooldownEntry(
                symbol=symbol.upper(),
                setup_type=setup_type.lower(),
                reason=str(reason),
                started_at=now,
                expires_at=new_expiry,
                rejection_count=1,
            )
            self._cooldowns[key] = entry
            logger.warning(
                "[v19.34.8 REJECTION-COOLDOWN] %s/%s STARTED — "
                "reason=%s, %ds (until %s)",
                symbol, setup_type, reason, seconds,
                new_expiry.isoformat(),
            )
            _persist_rejection_event(
                symbol=symbol, setup_type=setup_type, reason=str(reason),
                rejection_count=1, extended=False,
            )
            return entry

    def clear_cooldown(self, symbol: str, setup_type: str) -> bool:
        """Operator-driven manual clear. Returns True if an entry was
        cleared, False if the key wasn't in cooldown."""
        if not symbol or not setup_type:
            return False
        with self._lock:
            return self._cooldowns.pop(self._key(symbol, setup_type), None) is not None

    def clear_all(self) -> int:
        """Clear every cooldown. Returns the number cleared. Operator
        nuke option for end-of-debugging."""
        with self._lock:
            n = len(self._cooldowns)
            self._cooldowns.clear()
            return n

    def list_active(self) -> List[Dict]:
        """Snapshot of all active (non-expired) cooldowns."""
        with self._lock:
            self._expire_stale()
            return [e.to_dict() for e in self._cooldowns.values()]

    def stats(self) -> Dict:
        with self._lock:
            self._expire_stale()
            return {
                "active_cooldowns": len(self._cooldowns),
                "default_cooldown_seconds": self._default_cooldown_seconds,
                "total_rejection_count": sum(
                    e.rejection_count for e in self._cooldowns.values()
                ),
            }


# ── module-level singleton ────────────────────────────────────────────
_singleton: Optional[RejectionCooldown] = None


def get_rejection_cooldown() -> RejectionCooldown:
    global _singleton
    if _singleton is None:
        _singleton = RejectionCooldown()
    return _singleton


def reset_rejection_cooldown_for_tests() -> None:
    """ONLY for unit tests. Resets the module singleton so each test
    gets a fresh instance."""
    global _singleton
    _singleton = None
