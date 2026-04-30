"""
CPU Relief Manager — opt-in throttle for non-critical RPC paths.

Operator concern (2026-05-01): "IB Gateway is at 80% of my CPU + normal
processes max my Windows PC at 100%". Live tick subscriptions are the
real CPU consumer and the operator wants those LEFT ALONE — they're the
freshest data we have. The relief toggle defers everything else:

  • Smart-backfill bursts (concurrency cut)
  • Historical-bar pulls during EVAL (skip if cached bar < 60s old)
  • Daily collect cycles (sequential instead of parallel)
  • Periodic backfill loops (skip cycles)

Activation is explicit and ephemeral:
  • POST /api/ib/cpu-relief?enable=true       → on indefinitely
  • POST /api/ib/cpu-relief?enable=true&until=15:30 → auto-off at 3:30 PM ET
  • POST /api/ib/cpu-relief?enable=false      → off

Visibility:
  • GET /api/ib/cpu-relief returns live state + recent deferred-call counter.
  • UI badge listens to the same endpoint and shows "RELIEF ON" when active.

Design notes:
  • Pure in-memory, no Mongo persistence — relief is a transient operator
    decision, not a saved config. Backend restart resets to OFF.
  • Threadsafe: a single mutex guards all writes; reads are atomic.
  • `is_active()` is the hot-path check (called inside RPC dispatchers);
    keep it cheap (no I/O, no logging).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, time as dtime, timezone
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


class CpuReliefManager:
    """Single source of truth for the CPU relief toggle."""

    def __init__(self) -> None:
        self._active: bool = False
        self._enabled_at: Optional[datetime] = None
        self._until: Optional[datetime] = None
        self._reason: Optional[str] = None
        self._deferred_count: int = 0
        self._deferred_by_path: Dict[str, int] = {}
        self._lock = threading.Lock()

    # ---- public mutators ----------------------------------------------------
    def enable(
        self,
        *,
        until_hhmm_et: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Turn relief ON. If `until_hhmm_et` is given (e.g. '15:30') relief
        auto-disables at that ET time today; otherwise it persists until
        manually flipped or backend restart."""
        with self._lock:
            self._active = True
            self._enabled_at = datetime.now(timezone.utc)
            self._reason = reason
            if until_hhmm_et:
                self._until = self._parse_until(until_hhmm_et)
            else:
                self._until = None
            self._deferred_count = 0
            self._deferred_by_path = {}
        logger.info(
            "CPU relief ENABLED until=%s reason=%s",
            self._until.isoformat() if self._until else "indefinite",
            reason,
        )
        return self.status()

    def disable(self) -> Dict[str, Any]:
        with self._lock:
            self._active = False
            self._until = None
            self._reason = None
        logger.info("CPU relief DISABLED")
        return self.status()

    # ---- public reads (hot path — keep cheap) -------------------------------
    def is_active(self) -> bool:
        """Hot-path check. Auto-flips OFF if `until` has passed.

        Called inside RPC dispatchers / smart-backfill / etc., so this
        intentionally does NOT log or take the lock unless an auto-disable
        is needed.
        """
        if not self._active:
            return False
        until = self._until
        if until is None:
            return True
        if datetime.now(timezone.utc) >= until:
            # Auto-disable exited window. Take the lock just for this transition.
            with self._lock:
                if self._active and self._until and datetime.now(timezone.utc) >= self._until:
                    self._active = False
                    self._until = None
                    self._reason = "auto-disable: until window passed"
                    logger.info("CPU relief AUTO-DISABLED (window passed)")
            return False
        return True

    def status(self) -> Dict[str, Any]:
        return {
            "active": bool(self._active),
            "enabled_at": self._enabled_at.isoformat() if self._enabled_at else None,
            "until":      self._until.isoformat() if self._until else None,
            "reason":     self._reason,
            "deferred_count": self._deferred_count,
            "deferred_by_path": dict(self._deferred_by_path),
        }

    # ---- caller-side helper -------------------------------------------------
    def record_deferred(self, path: str) -> None:
        """Counter bumped each time a caller actually deferred work due
        to relief being on. Used for the UI badge tooltip."""
        with self._lock:
            self._deferred_count += 1
            self._deferred_by_path[path] = self._deferred_by_path.get(path, 0) + 1

    # ---- internals ----------------------------------------------------------
    @staticmethod
    def _parse_until(hhmm_et: str) -> Optional[datetime]:
        """Resolve 'HH:MM' (Eastern) into a UTC datetime for today.
        Tolerates 'h:mm' and trailing whitespace. Returns None on parse fail."""
        try:
            cleaned = hhmm_et.strip()
            hh, mm = cleaned.split(":")
            hh, mm = int(hh), int(mm)
            now_et = datetime.now(_ET)
            target_et = datetime.combine(
                now_et.date(), dtime(hh, mm), tzinfo=_ET,
            )
            # If the resolved time is already in the past today, pin to
            # the next-day equivalent so a 9 AM "until 15:30" call after
            # 4 PM doesn't immediately auto-disable.
            if target_et <= now_et:
                from datetime import timedelta
                target_et += timedelta(days=1)
            return target_et.astimezone(timezone.utc)
        except (ValueError, AttributeError):
            return None


# ---- singleton accessor ----------------------------------------------------
_singleton: Optional[CpuReliefManager] = None


def get_cpu_relief_manager() -> CpuReliefManager:
    global _singleton
    if _singleton is None:
        _singleton = CpuReliefManager()
    return _singleton
