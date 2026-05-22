"""
post_stop_cooldown.py — v19.34.88

Per-(symbol, setup_base) post-stop cooldown registry.

Problem this solves
-------------------
On 2026-05-14 the setup_retro tool (v19.34.87) surfaced 21 stop_loss
closes in ~25 minutes across 4 symbols (ETHU/CHWY/AJG/BALL) for
-17.68R total. Each symbol stopped 5-6 consecutive times on the
same setup because the existing "Recent-rejection cooldown" gates
on `alert_id`, but every fresh scanner pulse mints a new alert_id
— so the cooldown was effectively per-pulse, not per-symbol.

This module adds the missing layer: once a (symbol, setup_base)
combo hits a stop_loss, lock it out for POST_STOP_COOLDOWN_MINUTES
(default 30) regardless of which alert_id the scanner generates
next.

Architecture
------------
- In-memory dict keyed on (symbol_upper, setup_base) → epoch_ts of
  most recent stop. The TTL is dynamic (= cooldown window).
- Setup name normalised via _base() so vwap_fade_long and
  vwap_fade_short share one cooldown bucket. Direction is NOT part
  of the key — if you got stopped going long, going short on the
  same level minutes later is the same bad idea.
- Thread-safe via threading.Lock; this runs on the bot's event-loop
  thread but the pnl_compute writer can fire from a background
  shutdown task, so we lock conservatively.
- Singleton accessor get_registry() so all writers/readers share
  state. No persistence — process-restart clears cooldown, which is
  the safe default (operator can size up after restart).

Write site: services/pnl_compute.py (_record_alert_outcome_bestEffort)
Read site:  services/opportunity_evaluator.py (evaluate_opportunity gate)

Env knobs
---------
POST_STOP_COOLDOWN_ENABLED   default "true"
POST_STOP_COOLDOWN_MINUTES   default "30"
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_SUFFIXES = ("_long", "_short", "_l", "_s")


def _base(setup_type: Optional[str]) -> str:
    """Normalise setup_type: strip directional suffix and lowercase.
    Mirrors routers/scanner.py _base() and setup_retro.py _base()."""
    if not setup_type:
        return ""
    s = str(setup_type).lower().strip()
    for suf in _SUFFIXES:
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def _cooldown_seconds() -> float:
    raw = os.environ.get("POST_STOP_COOLDOWN_MINUTES", "30")
    try:
        return max(0.0, float(raw) * 60.0)
    except (TypeError, ValueError):
        return 1800.0


def _enabled() -> bool:
    return os.environ.get("POST_STOP_COOLDOWN_ENABLED", "true").lower() \
        not in ("false", "0", "no", "off")


class PostStopCooldownRegistry:
    """Process-local registry of recent stop closes."""

    def __init__(self) -> None:
        self._stops: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    # ── writer side ────────────────────────────────────────────────

    def record_stop(self, symbol: Optional[str], setup_type: Optional[str],
                    stop_ts: Optional[float] = None) -> None:
        """Stamp a stop close into the registry. Called from
        pnl_compute._record_alert_outcome_bestEffort when reason
        starts with 'stop'."""
        if not symbol:
            return
        base = _base(setup_type)
        if not base:
            # Unknown setup → still register against symbol with empty
            # setup so a follow-up entry on ANY setup is caught.
            base = "__unknown__"
        ts = float(stop_ts) if stop_ts is not None else time.time()
        key = (str(symbol).upper().strip(), base)
        with self._lock:
            self._stops[key] = ts
            self._evict_stale_locked(ts)
        logger.info(
            "[v19.34.88 post-stop-cooldown] stamped %s/%s at %s "
            "(cooldown %.0fs)", key[0], key[1], ts, _cooldown_seconds(),
        )

    # ── reader side ────────────────────────────────────────────────

    def seconds_remaining(self, symbol: Optional[str],
                          setup_type: Optional[str],
                          now_ts: Optional[float] = None) -> Optional[float]:
        """Return remaining cooldown seconds for the (symbol, setup_base)
        pair, or None if no cooldown is active. Returns None if the
        feature is disabled via env."""
        if not _enabled() or not symbol:
            return None
        base = _base(setup_type) or "__unknown__"
        key = (str(symbol).upper().strip(), base)
        now = float(now_ts) if now_ts is not None else time.time()
        window = _cooldown_seconds()
        if window <= 0:
            return None
        with self._lock:
            ts = self._stops.get(key)
        if ts is None:
            return None
        remaining = window - (now - ts)
        if remaining <= 0:
            return None
        return remaining

    def is_in_cooldown(self, symbol: Optional[str],
                       setup_type: Optional[str],
                       now_ts: Optional[float] = None) -> bool:
        return self.seconds_remaining(symbol, setup_type, now_ts) is not None

    # ── housekeeping ───────────────────────────────────────────────

    def _evict_stale_locked(self, now_ts: float) -> None:
        """Called under self._lock. Drops entries older than 2× window."""
        cutoff = now_ts - (2.0 * _cooldown_seconds())
        stale = [k for k, t in self._stops.items() if t < cutoff]
        for k in stale:
            self._stops.pop(k, None)

    def snapshot(self) -> dict[str, dict]:
        """Diagnostic snapshot for tests / debug endpoints."""
        with self._lock:
            now = time.time()
            window = _cooldown_seconds()
            return {
                f"{sym}/{base}": {
                    "stopped_at": ts,
                    "age_seconds": round(now - ts, 1),
                    "remaining_seconds": round(max(0.0, window - (now - ts)), 1),
                    "in_cooldown": (now - ts) < window,
                }
                for (sym, base), ts in self._stops.items()
            }

    def clear(self) -> None:
        """Reset registry — used by tests, never by prod code."""
        with self._lock:
            self._stops.clear()


# ── module-level singleton ─────────────────────────────────────────

_REGISTRY: Optional[PostStopCooldownRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> PostStopCooldownRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = PostStopCooldownRegistry()
    return _REGISTRY
