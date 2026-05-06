"""
Safety guardrails — pre-flight checks every entry must pass before the bot
places a trade, plus an emergency flatten-all handler.

Five independent checks (any ONE fails → trade rejected):
    1. Daily loss kill-switch     — realized+unrealized P&L for today ≥ limit
    2. Stale-quote gate           — most recent quote older than N seconds
    3. Max concurrent positions   — total open positions ≥ cap
    4. Per-symbol exposure cap    — new + existing USD exposure in same symbol
    5. Total exposure cap         — account-relative total exposure ceiling

All limits are env-driven and hot-patchable via `PUT /api/safety/config`.

v19.34.25 (2026-02-XX) — Kill-switch state is now PERSISTED to the
`safety_state` Mongo collection on every trip/reset and restored on boot.
Pre-fix the latch was in-memory only; restarting the backend silently
re-armed the bot. Operator-discovered 2026-02-XX after kill-switch was
manually tripped at 12:28 PM ET, then a backend restart at ~1:20 PM ET
silently cleared it; the bot opened 6 phantom trades during the next
~5 minutes (saved only by IB Gateway being offline at the time, which
prevented actual fills). Persistence prevents this exact recurrence.

The daily-loss check still reads live P&L on every call so there's no
need to persist the daily counter. Only the kill-switch latch persists.

Call site: `trading_bot_service._scan_for_opportunities` wraps every
candidate in `check_can_enter(symbol, side, notional_usd)` and skips the
candidate on `allowed=False`.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional, Tuple

import logging

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


# v19.34.25 — Sync Mongo handle for kill-switch persistence. Lazy + cached
# so module import doesn't pay the connect cost. Returns None if Mongo
# isn't reachable; callers must handle that gracefully (defense in depth —
# in-memory state remains authoritative even if persistence is offline).
_SAFETY_DB_HANDLE = None
_SAFETY_DB_HANDLE_FAILED = False  # set True if connect fails so we don't retry every trip


def _get_sync_safety_db():
    """Lazy-connect a sync pymongo client for kill-switch persistence.

    Sync (not motor) on purpose: trip/restore are infrequent and must
    complete synchronously with the latch state change so a process
    crash immediately after `trip_kill_switch()` can't lose the latch.
    """
    global _SAFETY_DB_HANDLE, _SAFETY_DB_HANDLE_FAILED
    if _SAFETY_DB_HANDLE is not None:
        return _SAFETY_DB_HANDLE
    if _SAFETY_DB_HANDLE_FAILED:
        return None
    try:
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME", "tradecommand")
        if not mongo_url:
            _SAFETY_DB_HANDLE_FAILED = True
            return None
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=2000)
        # Surface connection failures fast on boot rather than silently.
        client.admin.command("ping")
        _SAFETY_DB_HANDLE = client[db_name]
        return _SAFETY_DB_HANDLE
    except Exception as e:
        logger.error("[SAFETY] could not connect to Mongo for persistence: %s", e)
        _SAFETY_DB_HANDLE_FAILED = True
        return None


@dataclass
class SafetyConfig:
    """Hot-patchable via PUT /api/safety/config. Defaults come from env."""
    max_daily_loss_usd: float = 500.0
    max_daily_loss_pct: float = 2.0   # of account equity; the stricter of usd/pct wins
    max_positions: int = 5
    max_symbol_exposure_usd: float = 15000.0
    max_total_exposure_pct: float = 60.0   # of account equity
    max_quote_age_seconds: float = 10.0
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "SafetyConfig":
        return cls(
            max_daily_loss_usd      = _env_float("SAFETY_MAX_DAILY_LOSS_USD", 500.0),
            max_daily_loss_pct      = _env_float("SAFETY_MAX_DAILY_LOSS_PCT", 2.0),
            max_positions           = _env_int  ("SAFETY_MAX_POSITIONS", 5),
            max_symbol_exposure_usd = _env_float("SAFETY_MAX_SYMBOL_EXPOSURE_USD", 15000.0),
            max_total_exposure_pct  = _env_float("SAFETY_MAX_TOTAL_EXPOSURE_PCT", 60.0),
            max_quote_age_seconds   = _env_float("SAFETY_MAX_QUOTE_AGE_SEC", 10.0),
            enabled                 = os.environ.get("SAFETY_ENABLED", "true").lower() != "false",
        )


@dataclass
class SafetyState:
    """Mutable runtime state — kill-switch latch + last-check telemetry."""
    kill_switch_active: bool = False
    kill_switch_tripped_at: Optional[float] = None
    kill_switch_reason: Optional[str] = None
    # v19.34.26 — Scanner power toggle (soft brake). When paused, the bot's
    # `_scan_for_opportunities` loop refuses to pull NEW alerts into the
    # eval pipeline. In-flight evals + open-position management continue
    # normally (this is the "turn off the water pump" semantic).
    scanner_paused: bool = False
    scanner_paused_at: Optional[float] = None
    scanner_paused_reason: Optional[str] = None
    last_checks: List[Dict[str, Any]] = field(default_factory=list)   # ring buffer, last 20


@dataclass
class CheckResult:
    allowed: bool
    reason: str
    check: str                         # which check gated (or "ok")
    details: Dict[str, Any] = field(default_factory=dict)


class SafetyGuardrails:
    """Singleton-style — a single instance is bound to trading_bot_service."""

    def __init__(self, config: Optional[SafetyConfig] = None):
        self.config = config or SafetyConfig.from_env()
        self.state = SafetyState()

    # ── public checks ──────────────────────────────────────────────────────

    def check_can_enter(
        self,
        symbol: str,
        side: str,                     # "long" | "short"
        notional_usd: float,
        *,
        account_equity: float,
        daily_realized_pnl: float,
        daily_unrealized_pnl: float,
        open_positions: List[Dict[str, Any]],   # each: {symbol, side, notional_usd}
        last_quote_age_seconds: Optional[float] = None,
    ) -> CheckResult:
        """Run every guardrail. Return the first failure or the OK result."""
        if not self.config.enabled:
            return self._record(CheckResult(True, "safety disabled", "disabled"))

        # 1. Kill-switch latch (must be reset manually)
        if self.state.kill_switch_active:
            return self._record(CheckResult(
                False, f"kill-switch tripped: {self.state.kill_switch_reason}",
                "kill_switch",
                details={"tripped_at": self.state.kill_switch_tripped_at},
            ))

        # 2. Daily loss — use the stricter of usd/pct limits
        pnl_today = (daily_realized_pnl or 0.0) + (daily_unrealized_pnl or 0.0)
        pct_limit_usd = account_equity * (self.config.max_daily_loss_pct / 100.0)
        effective_limit = -min(self.config.max_daily_loss_usd, pct_limit_usd)
        if pnl_today <= effective_limit:
            self.trip_kill_switch(
                reason=f"daily loss ${pnl_today:.2f} breached limit ${effective_limit:.2f}",
            )
            return self._record(CheckResult(
                False, f"daily loss hit (${pnl_today:.2f} ≤ ${effective_limit:.2f})",
                "daily_loss",
                details={"pnl_today": pnl_today, "limit_usd": effective_limit},
            ))

        # 3. Stale quote
        if last_quote_age_seconds is not None and last_quote_age_seconds > self.config.max_quote_age_seconds:
            return self._record(CheckResult(
                False, f"quote stale ({last_quote_age_seconds:.1f}s > {self.config.max_quote_age_seconds:.0f}s)",
                "stale_quote",
                details={"age_seconds": last_quote_age_seconds},
            ))

        # 4. Max concurrent positions
        open_count = len(open_positions)
        if open_count >= self.config.max_positions:
            return self._record(CheckResult(
                False, f"already {open_count} positions open (cap {self.config.max_positions})",
                "max_positions",
                details={"open_count": open_count},
            ))

        # 5. Per-symbol exposure
        sym = (symbol or "").upper()
        existing_symbol_exposure = sum(
            float(p.get("notional_usd", 0)) for p in open_positions
            if (p.get("symbol") or "").upper() == sym
        )
        if existing_symbol_exposure + notional_usd > self.config.max_symbol_exposure_usd:
            return self._record(CheckResult(
                False, f"{sym} exposure ${existing_symbol_exposure + notional_usd:,.0f} exceeds cap ${self.config.max_symbol_exposure_usd:,.0f}",
                "symbol_exposure",
                details={
                    "symbol": sym,
                    "existing": existing_symbol_exposure,
                    "new_notional": notional_usd,
                },
            ))

        # 6. Total exposure vs account equity
        total_open = sum(float(p.get("notional_usd", 0)) for p in open_positions)
        total_exposure_pct = (total_open + notional_usd) / max(1.0, account_equity) * 100.0
        if total_exposure_pct > self.config.max_total_exposure_pct:
            return self._record(CheckResult(
                False, f"total exposure {total_exposure_pct:.1f}% exceeds cap {self.config.max_total_exposure_pct:.0f}%",
                "total_exposure",
                details={
                    "pct": total_exposure_pct,
                    "total_usd": total_open + notional_usd,
                    "account_equity": account_equity,
                },
            ))

        return self._record(CheckResult(
            True, "all guards passed", "ok",
            details={
                "open_count": open_count,
                "total_exposure_pct": total_exposure_pct,
                "pnl_today": pnl_today,
            },
        ))

    # ── kill-switch primitives ─────────────────────────────────────────────

    def trip_kill_switch(self, reason: str) -> None:
        """Latch the kill-switch. Idempotent — won't log repeatedly.

        v19.34.25 — Persists the latch to Mongo `safety_state` so a
        subsequent backend restart restores the tripped state instead
        of silently re-arming the bot (operator-discovered 2026-02-XX).
        """
        if self.state.kill_switch_active:
            return
        self.state.kill_switch_active = True
        self.state.kill_switch_tripped_at = time.time()
        self.state.kill_switch_reason = reason
        logger.error("[SAFETY] KILL-SWITCH TRIPPED — %s", reason)
        self._persist_kill_switch()

    def reset_kill_switch(self) -> None:
        """Manual unlock after the operator acknowledges the situation.

        v19.34.25 — Clears the persisted latch in Mongo too; without
        this, the bot would re-trip immediately on next boot from the
        stale Mongo record.
        """
        was_active = self.state.kill_switch_active
        self.state.kill_switch_active = False
        self.state.kill_switch_tripped_at = None
        self.state.kill_switch_reason = None
        if was_active:
            logger.warning("[SAFETY] Kill-switch MANUALLY RESET")
        self._persist_kill_switch()

    # ── persistence (v19.34.25) ───────────────────────────────────────────

    def _kill_switch_active_unsafe(self) -> bool:
        """v19.34.26 — Read-only access to the latch state for executor-
        layer guards. Used by `trade_executor_service` to refuse orders
        BEFORE they leave the bot, even when an upstream code path skipped
        the standard `check_can_enter` gate (today's bypass scenario).

        Returns the in-memory latch directly without locking — kill-switch
        state changes are infrequent, single-writer (operator API call) and
        the worst-case race is a single order squeezing through during the
        microsecond between trip and the next executor call. Acceptable
        relative to the cost of locking on every single order.
        """
        return bool(self.state.kill_switch_active)

    # ── scanner power toggle (v19.34.26) ──────────────────────────────────
    #
    # Soft-brake complement to the kill-switch. Pauses NEW alert intake so
    # no fresh trade ideas enter the eval pipeline, but lets in-flight
    # evaluations finish AND lets `position_manager` continue managing
    # already-open positions (stop trail-up, scale-out, close-on-stop).
    #
    # Persistence model mirrors the kill-switch: writes to the same
    # `safety_state` Mongo collection (different `_id`) so the toggle
    # survives backend restarts. Pre-fix today: no soft-brake existed,
    # operator had to choose between "let bot rip" or "hard-kill backend".

    def is_scanner_paused(self) -> bool:
        return bool(getattr(self.state, "scanner_paused", False))

    def pause_scanner(self, reason: str) -> None:
        if self.is_scanner_paused():
            return
        self.state.scanner_paused = True
        self.state.scanner_paused_at = time.time()
        self.state.scanner_paused_reason = reason
        logger.warning("[SAFETY] v19.34.26 — SCANNER PAUSED: %s", reason)
        self._persist_scanner_state()

    def resume_scanner(self) -> None:
        was_paused = self.is_scanner_paused()
        self.state.scanner_paused = False
        self.state.scanner_paused_at = None
        self.state.scanner_paused_reason = None
        if was_paused:
            logger.warning("[SAFETY] v19.34.26 — Scanner RESUMED by operator")
        self._persist_scanner_state()

    def _persist_scanner_state(self) -> None:
        try:
            db = _get_sync_safety_db()
            if db is None:
                return
            db.safety_state.update_one(
                {"_id": "scanner_toggle"},
                {"$set": {
                    "paused":     self.is_scanner_paused(),
                    "paused_at":  getattr(self.state, "scanner_paused_at", None),
                    "reason":     getattr(self.state, "scanner_paused_reason", None),
                    "updated_at": time.time(),
                }},
                upsert=True,
            )
        except Exception as e:
            logger.error("[SAFETY] scanner-toggle persistence FAILED: %s", e)

    def restore_scanner_state_from_db(self) -> bool:
        """Restore the scanner-paused latch on boot. Same contract as
        `restore_kill_switch_from_db` — returns True if a paused state
        was restored so the boot logger can warn loudly.
        """
        try:
            db = _get_sync_safety_db()
            if db is None:
                return False
            doc = db.safety_state.find_one({"_id": "scanner_toggle"})
            if not doc or not doc.get("paused"):
                return False
            self.state.scanner_paused = True
            self.state.scanner_paused_at = doc.get("paused_at")
            self.state.scanner_paused_reason = (
                doc.get("reason") or "restored_from_db (no reason recorded)"
            )
            logger.warning(
                "[SAFETY] v19.34.26 — SCANNER PAUSE RESTORED FROM DB on boot. "
                "Reason: %s | Bot will NOT pull new alerts into the eval "
                "pipeline until operator resumes via /api/safety/scanner/resume.",
                self.state.scanner_paused_reason,
            )
            return True
        except Exception as e:
            logger.error("[SAFETY] scanner-state restore FAILED: %s", e)
            return False

    def _persist_kill_switch(self) -> None:
        """Write the current kill-switch latch to Mongo `safety_state`.

        Sync pymongo on purpose: operations are infrequent (1-2/day at
        peak) and we want trip → write to be synchronous so a process
        crash *immediately after* trip can't lose the latch. The trip is
        also called from sync code paths in some safety checks, which
        precludes a clean async write.

        Failure to write is logged but does NOT raise — the in-memory
        state is the immediate authority; persistence is defense in
        depth. Better to have the latch active in-memory only than to
        propagate a Mongo error up into the trade-eval critical path.
        """
        try:
            db = _get_sync_safety_db()
            if db is None:
                return
            db.safety_state.update_one(
                {"_id": "kill_switch"},
                {"$set": {
                    "active":     self.state.kill_switch_active,
                    "tripped_at": self.state.kill_switch_tripped_at,
                    "reason":     self.state.kill_switch_reason,
                    "updated_at": time.time(),
                }},
                upsert=True,
            )
        except Exception as e:
            logger.error("[SAFETY] kill-switch persistence FAILED: %s", e)

    def restore_kill_switch_from_db(self) -> bool:
        """Restore the kill-switch latch from Mongo on backend boot.

        Called from server.py startup, BEFORE any trading code can run.
        Returns True if a tripped latch was restored (so the boot logger
        can emit a loud warning), False otherwise.

        Operator-discovered failure mode this prevents (2026-02-XX):
            12:28 PM — operator clicks Flatten All, kill-switch trips
            ~1:20 PM — backend restarted to deploy v19.34.24b
            ~1:20 PM — kill-switch silently disarmed (in-memory state
                       gone), bot opens 6 phantom entries before the
                       operator notices and re-trips manually.

        With this restore, the same restart sequence preserves the
        latch and the bot stays disarmed until manually acknowledged.
        """
        try:
            db = _get_sync_safety_db()
            if db is None:
                return False
            doc = db.safety_state.find_one({"_id": "kill_switch"})
            if not doc or not doc.get("active"):
                return False
            self.state.kill_switch_active = True
            self.state.kill_switch_tripped_at = doc.get("tripped_at")
            self.state.kill_switch_reason = (
                doc.get("reason") or "restored_from_db (no reason recorded)"
            )
            logger.error(
                "[SAFETY] v19.34.25 — KILL-SWITCH RESTORED FROM DB on boot. "
                "Reason: %s | Tripped at: %s | Bot will NOT place new trades "
                "until operator manually resets via /api/safety/reset-kill-switch.",
                self.state.kill_switch_reason,
                self.state.kill_switch_tripped_at,
            )
            return True
        except Exception as e:
            logger.error("[SAFETY] kill-switch restore FAILED: %s", e)
            return False

    # ── introspection ──────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "config": asdict(self.config),
            "state": {
                "kill_switch_active": self.state.kill_switch_active,
                "kill_switch_tripped_at": self.state.kill_switch_tripped_at,
                "kill_switch_reason": self.state.kill_switch_reason,
                # v19.34.26 — scanner power toggle in the same payload so
                # the V5 UI / curl can render both brakes side-by-side.
                "scanner_paused": self.is_scanner_paused(),
                "scanner_paused_at": getattr(self.state, "scanner_paused_at", None),
                "scanner_paused_reason": getattr(self.state, "scanner_paused_reason", None),
                "recent_checks": list(self.state.last_checks[-20:]),
            },
        }

    def update_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a partial config patch. Ignores unknown keys defensively."""
        for k, v in (patch or {}).items():
            if hasattr(self.config, k):
                setattr(self.config, k, type(getattr(self.config, k))(v))
        return asdict(self.config)

    # ── internal ───────────────────────────────────────────────────────────

    def _record(self, result: CheckResult) -> CheckResult:
        self.state.last_checks.append({
            "t": time.time(),
            "allowed": result.allowed,
            "check": result.check,
            "reason": result.reason,
            "details": result.details,
        })
        # Ring-buffer: keep last 20 decisions
        if len(self.state.last_checks) > 20:
            self.state.last_checks = self.state.last_checks[-20:]
        return result


# Module-level singleton (mirrors the pattern used by trading_bot_service).
_singleton: Optional[SafetyGuardrails] = None


def get_safety_guardrails() -> SafetyGuardrails:
    global _singleton
    if _singleton is None:
        _singleton = SafetyGuardrails()
    return _singleton


def reset_for_tests():
    """Test helper — reset the singleton so state/config are clean."""
    global _singleton
    _singleton = None
