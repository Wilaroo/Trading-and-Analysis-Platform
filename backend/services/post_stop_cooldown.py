"""post_stop_cooldown.py — v19.34.88

Per-(symbol, setup_base) post-stop cooldown registry. Prevents the
ETHU/CHWY/AJG/BALL re-entry loop pattern surfaced by setup_retro
v87 (21 stops in 25min for -17.68R on 2026-05-14).

Write: services/pnl_compute.py at every stop_loss close.
Read:  services/opportunity_evaluator.py before open-exposure cap.

Env: POST_STOP_COOLDOWN_ENABLED=true, POST_STOP_COOLDOWN_MINUTES=30."""
from __future__ import annotations
import logging, os, threading, time
from typing import Optional

logger = logging.getLogger(__name__)
_SUFFIXES = ("_long", "_short", "_l", "_s")


def _base(setup_type: Optional[str]) -> str:
    if not setup_type: return ""
    s = str(setup_type).lower().strip()
    for suf in _SUFFIXES:
        if s.endswith(suf): return s[:-len(suf)]
    return s


def _cooldown_seconds() -> float:
    raw = os.environ.get("POST_STOP_COOLDOWN_MINUTES", "30")
    try: return max(0.0, float(raw) * 60.0)
    except (TypeError, ValueError): return 1800.0


def _enabled() -> bool:
    return os.environ.get("POST_STOP_COOLDOWN_ENABLED", "true").lower() \
        not in ("false", "0", "no", "off")


class PostStopCooldownRegistry:
    def __init__(self) -> None:
        self._stops: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def record_stop(self, symbol, setup_type, stop_ts=None) -> None:
        if not symbol: return
        base = _base(setup_type) or "__unknown__"
        ts = float(stop_ts) if stop_ts is not None else time.time()
        key = (str(symbol).upper().strip(), base)
        with self._lock:
            self._stops[key] = ts
            self._evict_stale_locked(ts)
        logger.info(
            "[v19.34.88 post-stop-cooldown] stamped %s/%s at %s "
            "(cooldown %.0fs)", key[0], key[1], ts, _cooldown_seconds(),
        )

    def seconds_remaining(self, symbol, setup_type, now_ts=None):
        if not _enabled() or not symbol: return None
        base = _base(setup_type) or "__unknown__"
        key = (str(symbol).upper().strip(), base)
        now = float(now_ts) if now_ts is not None else time.time()
        window = _cooldown_seconds()
        if window <= 0: return None
        with self._lock:
            ts = self._stops.get(key)
        if ts is None: return None
        remaining = window - (now - ts)
        return remaining if remaining > 0 else None

    def is_in_cooldown(self, symbol, setup_type, now_ts=None) -> bool:
        return self.seconds_remaining(symbol, setup_type, now_ts) is not None

    def _evict_stale_locked(self, now_ts: float) -> None:
        cutoff = now_ts - (2.0 * _cooldown_seconds())
        stale = [k for k, t in self._stops.items() if t < cutoff]
        for k in stale: self._stops.pop(k, None)

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time(); window = _cooldown_seconds()
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
        with self._lock: self._stops.clear()


_REGISTRY: Optional[PostStopCooldownRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> PostStopCooldownRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = PostStopCooldownRegistry()
    return _REGISTRY
