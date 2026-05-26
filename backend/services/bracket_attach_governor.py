"""bracket_attach_governor.py — v19.34.154

Per-symbol governor that decides whether the bot should attempt to
attach an OCA stop+target bracket to a position right now.

Why this exists
---------------
2026-05-XX session: the reconciler observed positions without
brackets, tried to attach, IB rejected with Error 201 (Reg-T 15-order
cap), and the bot retried 180×/min until session close. Each retry
generated another working order, which made the Reg-T cap *worse*,
not better.

This module enforces three guard-rails:

  1. **Hard 3:45 ET cutoff** — IBKR switches from intraday-margin to
     overnight-Reg-T at 3:50 ET. Per operator's IBKR research, the
     Soft Edge Margin grace period expires at 3:45 ET (15 min before
     the regular close). Any bracket attached after 3:45 ET risks
     triggering Reg-T 201 because IBKR is computing margin against
     overnight requirements. **No bracket attempts past 15:45 ET.**

  2. **Permanent block on Error 201 / 203 / 110** — these IB errors
     (Reg-T call, HTB restriction, price-band violation) will NOT
     clear without operator action. Block the symbol for the rest of
     the trading day; the caller is responsible for firing emergency
     MKT flatten on naked positions (operator choice 4a + 5b).

  3. **Generic attempt cap** — 5 attempts within a 300s rolling
     window per symbol. Defense-in-depth against unknown failure
     modes that don't surface a permanent IB error code.

Public API
----------
* `should_attempt_attach(symbol) -> (bool, reason)`
* `record_outcome(symbol, oca_result)` — call after every
  `place_oca_stop_target` / `attach_oca_stop_target` invocation
* `unblock(symbol)` — operator override
* `get_state()` — for the dry-run script + API endpoint

Thread-safety: the governor is a process-singleton, all state is in
in-memory dicts. The async manage-loop is single-threaded so we don't
need locks; the only mutation paths are the two methods above.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

logger = logging.getLogger(__name__)

# Tunables (env-overridable at top of `_load_config`).
_DEFAULT_HARD_CUTOFF_HOUR = 15
_DEFAULT_HARD_CUTOFF_MINUTE = 45
_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_ATTEMPT_WINDOW_S = 300

# IB error codes that are PERMANENT failures.
PERMANENT_IB_ERRORS = {
    201: "reg_t_or_15_order_cap",
    203: "security_not_available_to_short_or_trade",
    110: "price_does_not_conform_to_variable_tick",
    320: "server_error_processing_message",
    321: "server_error_validating_request",
    103: "duplicate_order_id",
}


class BracketAttachGovernor:
    """Process-singleton (see module-level `get_governor`)."""

    def __init__(self):
        # Per-symbol-per-day attempt log: {date_str: {symbol: [ts, ts, ...]}}
        self._attempts: Dict[str, Dict[str, List[float]]] = {}
        # Per-symbol-per-day permanent blocks: {date_str: {symbol: {reason, code, blocked_at}}}
        self._blocks: Dict[str, Dict[str, dict]] = {}
        # Per-symbol-per-day "blocked" log dedup so we don't spam the
        # backend logs every manage tick.
        self._block_logged: Dict[str, set] = {}
        self._config = self._load_config()

    @staticmethod
    def _load_config() -> dict:
        import os
        def _i(name, default):
            try:
                return int(os.environ.get(name, default))
            except (TypeError, ValueError):
                return default
        return {
            "hard_cutoff_hour": _i("BRACKET_GOV_CUTOFF_HOUR",
                                   _DEFAULT_HARD_CUTOFF_HOUR),
            "hard_cutoff_minute": _i("BRACKET_GOV_CUTOFF_MINUTE",
                                     _DEFAULT_HARD_CUTOFF_MINUTE),
            "max_attempts": _i("BRACKET_GOV_MAX_ATTEMPTS",
                               _DEFAULT_MAX_ATTEMPTS),
            "attempt_window_s": _i("BRACKET_GOV_ATTEMPT_WINDOW_S",
                                   _DEFAULT_ATTEMPT_WINDOW_S),
        }

    @staticmethod
    def _today_str() -> str:
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

    def _prune(self, today: str) -> None:
        """Drop yesterday's buckets so memory stays bounded."""
        for d in list(self._attempts.keys()):
            if d != today:
                self._attempts.pop(d, None)
        for d in list(self._blocks.keys()):
            if d != today:
                self._blocks.pop(d, None)
        for d in list(self._block_logged.keys()):
            if d != today:
                self._block_logged.pop(d, None)

    # ── public API ────────────────────────────────────────────────────

    def should_attempt_attach(
        self,
        symbol: str,
        *,
        now_et: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        """Returns `(should_attempt, reason)`.

        If `should_attempt` is False, the caller MUST NOT call
        `place_oca_stop_target` / `attach_oca_stop_target` for this
        symbol. `reason` is a short stable string suitable for logging
        and inclusion in alarm metadata.
        """
        if not symbol:
            return (False, "empty_symbol")
        sym = symbol.upper().strip()
        if now_et is None:
            now_et = datetime.now(ZoneInfo("America/New_York"))
        today = now_et.strftime("%Y-%m-%d")
        self._prune(today)

        # 1) Hard 3:45 ET cutoff (IBKR Reg-T Soft Edge expiry).
        cutoff_h = self._config["hard_cutoff_hour"]
        cutoff_m = self._config["hard_cutoff_minute"]
        if (now_et.weekday() < 5 and
                (now_et.hour > cutoff_h
                 or (now_et.hour == cutoff_h and now_et.minute >= cutoff_m))):
            return (False, "past_regt_soft_edge_cutoff")

        # 2) Permanent block from prior IB error.
        blocked = self._blocks.get(today, {}).get(sym)
        if blocked:
            return (False, f"permanent_block:{blocked.get('reason', 'unknown')}")

        # 3) Generic attempt cap.
        attempts = self._attempts.get(today, {}).get(sym, [])
        if attempts:
            cutoff = time.time() - self._config["attempt_window_s"]
            recent = [t for t in attempts if t >= cutoff]
            if len(recent) >= self._config["max_attempts"]:
                return (False, f"max_attempts_exceeded:{len(recent)}_in_{self._config['attempt_window_s']}s")

        return (True, "ok")

    def record_outcome(
        self,
        symbol: str,
        oca_result: Optional[dict],
        *,
        now_et: Optional[datetime] = None,
    ) -> dict:
        """Record an attach attempt outcome. Returns a summary dict
        the caller can include in its log / stream alarm:

          {
            "now_blocked": bool,
            "block_reason": Optional[str],
            "stop_terminal_reject": bool,   # caller MUST emergency-flatten
            "permanent_failure": bool,
            "attempt_count_today": int,
          }
        """
        if not symbol:
            return {"now_blocked": False, "block_reason": None,
                    "stop_terminal_reject": False,
                    "permanent_failure": False, "attempt_count_today": 0}
        sym = symbol.upper().strip()
        if now_et is None:
            now_et = datetime.now(ZoneInfo("America/New_York"))
        today = now_et.strftime("%Y-%m-%d")
        self._prune(today)

        # Record the attempt timestamp only on failure — the attempt-
        # cap is a storm-prevention mechanism, not a success-tracker.
        # Counting successful attaches would falsely block healthy
        # symbols that simply re-bracketed after a partial close.
        r = oca_result or {}
        success = bool(r.get("success"))
        d_att = self._attempts.setdefault(today, {})
        if not success:
            d_att.setdefault(sym, []).append(time.time())
        attempt_count = len(d_att.get(sym, []))

        permanent = bool(r.get("permanent_failure"))
        stp_term = bool(r.get("stop_terminal_reject"))
        stop_err = r.get("stop_error_code")
        tgt_err = r.get("target_error_code")

        block_reason: Optional[str] = None

        # If a permanent IB error fired on EITHER leg, permanent-block.
        for code in (stop_err, tgt_err):
            if isinstance(code, int) and code in PERMANENT_IB_ERRORS:
                block_reason = f"ib_error_{code}_{PERMANENT_IB_ERRORS[code]}"
                break

        # If overall failed and we've now exceeded the attempt cap,
        # block (this is the storm-prevention path even when IB didn't
        # surface a permanent error code).
        if not block_reason and not success:
            cutoff = time.time() - self._config["attempt_window_s"]
            recent = [t for t in d_att[sym] if t >= cutoff]
            if len(recent) >= self._config["max_attempts"]:
                block_reason = (
                    f"max_attempts_exceeded:{len(recent)}_in_"
                    f"{self._config['attempt_window_s']}s"
                )

        if block_reason:
            d_blk = self._blocks.setdefault(today, {})
            if sym not in d_blk:
                d_blk[sym] = {
                    "reason": block_reason,
                    "code": stop_err if (isinstance(stop_err, int)
                                          and stop_err in PERMANENT_IB_ERRORS) else tgt_err,
                    "blocked_at": time.time(),
                    "blocked_at_et": now_et.isoformat(),
                    "attempt_count": attempt_count,
                }
                logger.error(
                    "[v19.34.154 GOVERNOR] %s now PERMANENT-BLOCKED for the "
                    "rest of %s: reason=%s code=%s attempts=%d",
                    sym, today, block_reason, d_blk[sym].get("code"),
                    attempt_count,
                )

        return {
            "now_blocked": bool(block_reason),
            "block_reason": block_reason,
            "stop_terminal_reject": stp_term,
            "permanent_failure": permanent,
            "attempt_count_today": attempt_count,
        }

    def unblock(self, symbol: str, *, now_et: Optional[datetime] = None) -> dict:
        """Operator override — clears the permanent block for `symbol`
        on the current day. Does NOT clear the attempt history (so the
        attempt-cap can still kick in on rapid re-failures)."""
        if not symbol:
            return {"unblocked": False, "reason": "empty_symbol"}
        sym = symbol.upper().strip()
        if now_et is None:
            today = self._today_str()
        else:
            today = now_et.strftime("%Y-%m-%d")
        d_blk = self._blocks.get(today, {})
        if sym in d_blk:
            prev = d_blk.pop(sym)
            self._block_logged.get(today, set()).discard(sym)
            logger.warning(
                "[v19.34.154 GOVERNOR] %s manually UNBLOCKED. Prior reason: %s",
                sym, prev.get("reason"),
            )
            return {"unblocked": True, "prior_reason": prev.get("reason"),
                    "prior_code": prev.get("code")}
        return {"unblocked": False, "reason": "not_currently_blocked"}

    def mark_logged(self, symbol: str) -> bool:
        """Returns True the FIRST time it's called per (symbol, day);
        False on subsequent calls. Useful for once-per-day log dedup
        when the reconciler observes a blocked symbol on every tick.
        """
        if not symbol:
            return False
        sym = symbol.upper().strip()
        today = self._today_str()
        s = self._block_logged.setdefault(today, set())
        if sym in s:
            return False
        s.add(sym)
        return True

    def get_state(self, *, now_et: Optional[datetime] = None) -> dict:
        """Read-only snapshot for the dry-run + operator API."""
        if now_et is None:
            today = self._today_str()
        else:
            today = now_et.strftime("%Y-%m-%d")
        self._prune(today)
        cutoff = time.time() - self._config["attempt_window_s"]
        attempts_today = {
            sym: {
                "total_today": len(times),
                "in_window": len([t for t in times if t >= cutoff]),
            }
            for sym, times in self._attempts.get(today, {}).items()
        }
        return {
            "today_et": today,
            "config": dict(self._config),
            "blocks": dict(self._blocks.get(today, {})),
            "attempts": attempts_today,
        }


# ── module-level singleton ───────────────────────────────────────────
_governor: Optional[BracketAttachGovernor] = None


def get_governor() -> BracketAttachGovernor:
    """Process singleton."""
    global _governor
    if _governor is None:
        _governor = BracketAttachGovernor()
    return _governor


def reset_governor_for_tests() -> None:
    """Test-only: blow away the singleton so each test starts fresh."""
    global _governor
    _governor = None
