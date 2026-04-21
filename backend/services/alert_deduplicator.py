"""Scanner-alert de-duplication service (2026-04-21).

Problem
-------
Audit showed PRCT fired 8 identical `vwap_fade_short` trades at entry 26.67,
stop 26.71 within a short window — each bled -8.9R. The scanner kept re-firing
while the first bleeding position was still open, and the bot kept taking it.

Fix
---
Before taking any new trade, check two dedup keys:
  - Is there already an open trade for `(symbol, setup_type, direction)`?
  - Have we fired this combo within `cooldown_seconds`?

If either: SKIP. This is a hard veto — runs before the confidence gate.

Design
------
Pure state store (no Mongo dependency — open trades come from the bot's
in-memory dict, recent fires live in a bounded TTL dict). Thread-safe.

Usage
-----
    dedup = AlertDeduplicator(cooldown_s=300)
    if dedup.should_skip(symbol, setup_type, direction, open_trades):
        return
    dedup.mark_fired(symbol, setup_type, direction)
    # ... continue with gate evaluation
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple


# ── Pure helpers (unit-tested) ────────────────────────────────────────────

def _key(symbol: str, setup_type: str, direction: str) -> Tuple[str, str, str]:
    """Normalize a dedup key — lowercase symbol/setup, lower direction."""
    return (
        (symbol or "").upper().strip(),
        (setup_type or "").lower().strip(),
        (direction or "").lower().strip(),
    )


def is_open_for_key(
    key: Tuple[str, str, str],
    open_trades: Iterable[Any],
) -> bool:
    """Check if any open trade matches this (symbol, setup, direction)."""
    sym, setup, direction = key
    for t in open_trades:
        t_sym = getattr(t, "symbol", None) or (t.get("symbol") if isinstance(t, dict) else None)
        t_setup = getattr(t, "setup_type", None) or (t.get("setup_type") if isinstance(t, dict) else None)
        t_dir = getattr(t, "direction", None) or (t.get("direction") if isinstance(t, dict) else None)
        if (
            (t_sym or "").upper() == sym
            and (t_setup or "").lower() == setup
            and (t_dir or "").lower() == direction
        ):
            return True
    return False


# ── Service class ─────────────────────────────────────────────────────────

@dataclass
class DedupResult:
    skip: bool
    reason: str  # "" when skip=False


class AlertDeduplicator:
    """Drops duplicate scanner fires for the same (symbol, setup, direction)."""

    def __init__(self, cooldown_s: int = 300):
        self._cooldown_s = cooldown_s
        self._recent: Dict[Tuple[str, str, str], float] = {}
        self._lock = threading.Lock()

    def should_skip(
        self,
        symbol: str,
        setup_type: str,
        direction: str,
        open_trades: Optional[Iterable[Any]] = None,
        now: Optional[float] = None,
    ) -> DedupResult:
        """Return (skip, reason).  Honors both the open-position rule AND the cooldown rule."""
        k = _key(symbol, setup_type, direction)

        if open_trades is not None and is_open_for_key(k, open_trades):
            return DedupResult(True, f"duplicate_open_position:{k[0]}/{k[1]}/{k[2]}")

        now = now if now is not None else time.monotonic()
        with self._lock:
            last = self._recent.get(k)
            if last is not None and (now - last) < self._cooldown_s:
                age = int(now - last)
                return DedupResult(
                    True,
                    f"cooldown_active:{k[0]}/{k[1]}/{k[2]} ({age}s ago < {self._cooldown_s}s)",
                )
        return DedupResult(False, "")

    def mark_fired(
        self,
        symbol: str,
        setup_type: str,
        direction: str,
        now: Optional[float] = None,
    ) -> None:
        k = _key(symbol, setup_type, direction)
        now = now if now is not None else time.monotonic()
        with self._lock:
            self._recent[k] = now
            # Prune old entries if the dict gets large (lazy GC)
            if len(self._recent) > 1000:
                cutoff = now - self._cooldown_s
                self._recent = {
                    key: ts for key, ts in self._recent.items() if ts >= cutoff
                }

    def clear(self) -> int:
        with self._lock:
            n = len(self._recent)
            self._recent.clear()
        return n


# Module-level singleton — single source of truth for the trading bot
_GLOBAL_DEDUP = AlertDeduplicator(cooldown_s=300)


def get_deduplicator() -> AlertDeduplicator:
    return _GLOBAL_DEDUP
