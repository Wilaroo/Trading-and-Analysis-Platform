"""
order_intent_dedup.py — v19.29 (2026-05-01)

Operator caught 300+ duplicate cancelled orders today (2:17pm-3:55pm).
The bot fired the same `(symbol, side, qty±5%, price±0.5%)` limit
order on every scanner cycle while a previous one was still pending
in IB, all cancelling at end-of-day because the limits never filled.

Pre-v19.29 dedup is symbol-cooldown-only ("rejection dedup cooldown
on SOFI Gap Fade"). It doesn't catch *order-level* spam where the
same intent re-fires from the entry pipeline.

This module provides intent-level dedup:
  - `mark_pending(symbol, side, qty, price)` when we submit
  - `is_already_pending(symbol, side, qty, price)` BEFORE submitting
  - `clear_filled(symbol, side, qty)` when the broker reports fill/cancel
  - Auto-expiry: any intent older than `INTENT_TTL_SECONDS` (default 90s)
    is considered stale and gets cleared so the bot can retry

Integration: called from `services/trade_execution.execute_trade`
right before `place_bracket_order`.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Tunable tolerances for "is this the same intent?"
PRICE_TOLERANCE_PCT = 0.5   # within ±0.5% counts as same
QTY_TOLERANCE_PCT = 5.0     # within ±5% counts as same
INTENT_TTL_SECONDS = 90     # stale intents auto-expire (covers IB
                            # day-order auto-cancel + retry headroom)

# v19.34.65 (2026-02-09) — Trade-log forensic on yesterday's session
# revealed two patterns the v19.29 dedup misses entirely:
#
#  • ADBE 18-buy ramp (9:32 → 12:57): same (symbol, side) entries with
#    sizes drifting 54→59→47→22→17→14→5… Each new entry has a slightly
#    different qty, so v19.29's ±5% qty-tolerance fingerprint sees them
#    as DIFFERENT intents and lets every single one through.
#  • DDOG/SQQQ wash cycles (10:23-10:53): bot SELLS X shares, then BUYS
#    X shares same minute, then sells again, etc. v19.29 keys by side,
#    so opposite-side sequences never match.
#
# The "broad cooldown" below is intentionally simpler and stricter than
# the v19.29 fingerprint: ANY entry attempt on a symbol within 60s of
# the previous SUBMITTED entry (regardless of side or qty) is blocked.
# Trims the ramp and the wash, but won't block legitimate scale-ups
# that happen >60s apart.
ENTRY_COOLDOWN_SECONDS = 60.0  # any (symbol) entry within this window is blocked


@dataclass
class _PendingIntent:
    symbol: str
    side: str       # "buy" | "sell"
    qty: int
    price: float
    submitted_at: datetime
    trade_id: Optional[str] = None


@dataclass
class _RecentSubmission:
    """v19.34.65 — last submitted entry for a given symbol.

    Used by `should_throttle_entry` to enforce the broad 60s symbol-level
    cooldown that catches the ramp + wash patterns the v19.29 fingerprint
    can't see. Recorded REGARDLESS of fill outcome so the throttle
    survives broker-side rejections (which would otherwise unblock the
    ramp on every reject).
    """
    symbol: str
    side: str          # "buy" | "sell"
    qty: int
    price: float
    submitted_at: datetime
    trade_id: Optional[str] = None


class OrderIntentDedup:
    """Process-wide registry of pending IB order intents."""

    def __init__(self):
        self._pending: Dict[str, _PendingIntent] = {}  # key: composite
        # v19.34.65 — separate registry for the broad symbol-level
        # cooldown. Keyed by symbol (uppercased) so opposite-side
        # entries collide too (catches the wash-cycle case).
        self._recent_submissions: Dict[str, _RecentSubmission] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(symbol: str, side: str, qty: int, price: float) -> str:
        # Bucket the price so similar prices collapse to the same key.
        # Round to 2 decimals; cluster within tolerance is checked at
        # match time (not key time).
        return f"{(symbol or '').upper()}|{(side or '').lower()}|{int(round(price, 2) * 100)}"

    def _expire_stale(self) -> None:
        """Remove entries older than `INTENT_TTL_SECONDS`. Caller holds lock."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=INTENT_TTL_SECONDS)
        for k in list(self._pending.keys()):
            if self._pending[k].submitted_at < cutoff:
                self._pending.pop(k, None)

    def is_already_pending(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
    ) -> Optional[_PendingIntent]:
        """Return the matching pending intent or None.

        "Match" = same symbol, same side, qty within ±5%, price within ±0.5%.
        """
        if not symbol or not side or qty <= 0 or price <= 0:
            return None
        with self._lock:
            self._expire_stale()
            sym_u = symbol.upper()
            side_l = side.lower()
            for entry in self._pending.values():
                if entry.symbol != sym_u or entry.side != side_l:
                    continue
                if entry.qty <= 0 or entry.price <= 0:
                    continue
                qty_diff_pct = abs(entry.qty - qty) / max(entry.qty, qty) * 100
                price_diff_pct = abs(entry.price - price) / max(entry.price, price) * 100
                if qty_diff_pct <= QTY_TOLERANCE_PCT and price_diff_pct <= PRICE_TOLERANCE_PCT:
                    return entry
            return None

    def mark_pending(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        trade_id: Optional[str] = None,
    ) -> None:
        """Stamp a freshly-submitted order intent. Idempotent."""
        if not symbol or not side or qty <= 0 or price <= 0:
            return
        intent = _PendingIntent(
            symbol=symbol.upper(),
            side=side.lower(),
            qty=int(qty),
            price=float(price),
            submitted_at=datetime.now(timezone.utc),
            trade_id=trade_id,
        )
        with self._lock:
            self._pending[self._key(intent.symbol, intent.side, qty, price)] = intent

    def clear_filled(
        self,
        symbol: str,
        side: str,
        qty: Optional[int] = None,
        price: Optional[float] = None,
    ) -> int:
        """Clear matching pending intents on fill/cancel. Returns count cleared.

        If qty/price provided, match precisely; otherwise clear ALL pending
        intents for the symbol+side (used on order cancellation broadcasts
        where price detail isn't always available).
        """
        if not symbol or not side:
            return 0
        sym_u = symbol.upper()
        side_l = side.lower()
        cleared = 0
        with self._lock:
            for k in list(self._pending.keys()):
                e = self._pending[k]
                if e.symbol != sym_u or e.side != side_l:
                    continue
                if qty is not None and price is not None:
                    qty_diff = abs(e.qty - qty) / max(e.qty, qty) * 100
                    price_diff = abs(e.price - price) / max(e.price, price) * 100
                    if qty_diff > QTY_TOLERANCE_PCT or price_diff > PRICE_TOLERANCE_PCT:
                        continue
                self._pending.pop(k, None)
                cleared += 1
        return cleared

    def stats(self) -> Dict[str, int]:
        with self._lock:
            self._expire_stale()
            return {
                "pending_count": len(self._pending),
                "ttl_seconds": INTENT_TTL_SECONDS,
                # v19.34.65 — surface cooldown registry size for HUD/diagnostics
                "recent_submissions_count": len(self._recent_submissions),
                "entry_cooldown_seconds": ENTRY_COOLDOWN_SECONDS,
            }

    # ── v19.34.65 broad symbol-level entry cooldown ───────────────────
    def should_throttle_entry(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        cooldown_seconds: float = ENTRY_COOLDOWN_SECONDS,
    ) -> Optional[_RecentSubmission]:
        """Return the prior submission blocking this entry, or None if OK.

        The check is intentionally broader than `is_already_pending`:
        any prior entry on the same SYMBOL within `cooldown_seconds`
        blocks the new attempt regardless of side, qty, or price. This
        catches:
          • Ramp entries (ADBE 18-buy: same side, drifting size)
          • Wash cycles (DDOG/SQQQ: opposite side, immediate reversal)
          • Re-entry into a recently-closed position
        """
        if not symbol or not side or qty <= 0 or price <= 0:
            return None
        sym_u = symbol.upper()
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)
        with self._lock:
            entry = self._recent_submissions.get(sym_u)
            if entry is None:
                return None
            if entry.submitted_at < cutoff:
                # Stale → drop it so the throttle slides forward cleanly.
                self._recent_submissions.pop(sym_u, None)
                return None
            return entry

    def record_entry_submitted(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        trade_id: Optional[str] = None,
    ) -> None:
        """v19.34.65 — stamp the broad cooldown the moment we hand an
        entry to the broker. Recorded BEFORE the broker call so a fast
        retry-after-rejection pattern can't slip past the cooldown.
        """
        if not symbol or not side or qty <= 0 or price <= 0:
            return
        rec = _RecentSubmission(
            symbol=symbol.upper(),
            side=side.lower(),
            qty=int(qty),
            price=float(price),
            submitted_at=datetime.now(timezone.utc),
            trade_id=trade_id,
        )
        with self._lock:
            self._recent_submissions[rec.symbol] = rec

    def clear_symbol_cooldown(self, symbol: str) -> int:
        """v19.34.65 — operator/test escape hatch. Returns 1 if cleared."""
        if not symbol:
            return 0
        sym_u = symbol.upper()
        with self._lock:
            return 1 if self._recent_submissions.pop(sym_u, None) is not None else 0


# ── module-level singleton ──────────────────────────────────────────────
_singleton: Optional[OrderIntentDedup] = None


def get_order_intent_dedup() -> OrderIntentDedup:
    global _singleton
    if _singleton is None:
        _singleton = OrderIntentDedup()
    return _singleton
