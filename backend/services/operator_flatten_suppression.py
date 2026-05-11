"""
operator_flatten_suppression.py — v19.34.72 (Feb 2026)
=========================================================

Operator-flatten detector + per-session re-entry suppression.

Why
---
The position reconciler's two-tick external-close gate (v19.34.71)
confirms when an IB position has truly dropped to zero. But "confirmed
zero at IB" can mean two things:

  A. Bot's stop/target bracket leg fired at IB — expected, the bot
     planned this exit. The bot's normal flow handles the lifecycle.
  B. The operator manually flattened in TWS, OR some external action
     (margin call, broker auto-liquidation, etc.) closed the position
     without the bot having a stake in it.

Case (B) is the dangerous one. If the operator manually flattened
because they saw something the bot couldn't (news, hostile tape,
discretionary risk-off), the bot continuing to evaluate the SAME setup
moments later — and re-entering — actively fights the operator. The
bot should respect the operator's signal: treat the symbol as
"hands-off" for the rest of the session.

What this module does
---------------------
A process-singleton suppression set keyed by uppercased symbol. The
reconciler adds a symbol when `_close_drift_trades_zero` fires (which
by definition is an EXTERNAL close — the bot didn't initiate the
order). The trade-execution pre-flight check reads the set and vetoes
any new entry on a suppressed symbol.

The set auto-rolls at UTC midnight (per-session semantics, matching
the rest of the bot's daily counters). The operator can inspect via
`GET /api/safety/operator-flatten-suppression` and clear via
`POST /api/safety/clear-operator-flatten-suppression` if a suppression
was a false positive.

Heuristic decision
------------------
Every external_close routed through `_close_drift_trades_zero` is
classified as `operator_external_flatten` by default. Rationale: the
drift reconciler only fires this branch when bot's `_open_trades`
shows the position is OPEN but IB shows it's CLOSED. If the bot had
issued the close itself, it would have already moved the trade out
of `_open_trades`. So by construction, anything reaching this branch
is non-bot-initiated.

The one false-positive class: bot's stop/target bracket leg fires at
IB autonomously (the bracket lives at IB GTC, independent of bot
state). In that case, the bot eventually receives the fill event and
moves the trade out of `_open_trades` — but if the drift reconciler
scans BEFORE that fill event propagates, it sees the same fingerprint
as an operator flatten. Mitigation: the two-tick gate (v19.34.71)
already imposes a ≥30s delay before the suppression fires, by which
time bracket-leg fills have propagated to `_open_trades` for the
overwhelming majority of cases.

If the operator hits a false positive (bracket fill misclassified),
they clear via the API endpoint.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class OperatorFlattenSuppression:
    """In-process suppression set with daily UTC roll."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._suppressed: Dict[str, Dict[str, str]] = {}
        # "YYYY-MM-DD" — the UTC day this set was populated under.
        # When the date rolls, the set clears automatically.
        self._day: Optional[str] = None

    # ── internal ────────────────────────────────────────────────

    def _today_utc(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll_day_if_needed(self) -> None:
        today = self._today_utc()
        if self._day != today:
            if self._suppressed:
                logger.info(
                    "[v19.34.72 FLATTEN-SUPPRESSION] UTC day rolled "
                    "(%s → %s). Clearing %d suppressed symbol(s).",
                    self._day, today, len(self._suppressed),
                )
            self._day = today
            self._suppressed.clear()

    # ── public API ──────────────────────────────────────────────

    def add(self, symbol: str, reason: str = "operator_external_flatten",
            trade_ids: Optional[List[str]] = None) -> None:
        """Mark a symbol as suppressed for the remainder of the UTC day."""
        sym = (symbol or "").upper()
        if not sym:
            return
        with self._lock:
            self._roll_day_if_needed()
            self._suppressed[sym] = {
                "reason": reason,
                "added_at": datetime.now(timezone.utc).isoformat(),
                "trade_ids": list(trade_ids or []),
            }
        logger.warning(
            "[v19.34.72 FLATTEN-SUPPRESSION] %s added to suppression set "
            "(reason=%s, trade_ids=%s). Re-entries blocked until UTC midnight "
            "or operator clears via /api/safety/clear-operator-flatten-suppression.",
            sym, reason, list(trade_ids or []),
        )

    def is_suppressed(self, symbol: str) -> bool:
        sym = (symbol or "").upper()
        if not sym:
            return False
        with self._lock:
            self._roll_day_if_needed()
            return sym in self._suppressed

    def get_entry(self, symbol: str) -> Optional[Dict[str, str]]:
        """Return the suppression record (reason, added_at, trade_ids) or None."""
        sym = (symbol or "").upper()
        with self._lock:
            self._roll_day_if_needed()
            entry = self._suppressed.get(sym)
            return dict(entry) if entry else None

    def list_all(self) -> Dict[str, Dict[str, str]]:
        """Snapshot of the suppression set (deep-copied to be safe to mutate)."""
        with self._lock:
            self._roll_day_if_needed()
            return {sym: dict(entry) for sym, entry in self._suppressed.items()}

    def clear(self, symbol: Optional[str] = None) -> int:
        """Clear either one symbol or the entire set. Returns count removed."""
        with self._lock:
            self._roll_day_if_needed()
            if symbol is None:
                count = len(self._suppressed)
                self._suppressed.clear()
                logger.info(
                    "[v19.34.72 FLATTEN-SUPPRESSION] Operator cleared all "
                    "%d suppressed symbols.", count,
                )
                return count
            sym = symbol.upper()
            if sym in self._suppressed:
                self._suppressed.pop(sym, None)
                logger.info(
                    "[v19.34.72 FLATTEN-SUPPRESSION] Operator cleared "
                    "%s from suppression set.", sym,
                )
                return 1
            return 0


# Module-level singleton.
_singleton: Optional[OperatorFlattenSuppression] = None


def get_operator_flatten_suppression() -> OperatorFlattenSuppression:
    global _singleton
    if _singleton is None:
        _singleton = OperatorFlattenSuppression()
    return _singleton
