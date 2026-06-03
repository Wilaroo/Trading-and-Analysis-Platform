"""
v19.34.236 (Part A) — pending fill attribution.

The bot-vs-IB drift's true source: `_execute_trade` pre-writes a `bot_trades`
row as PENDING, then submits the bracket. When `place_bracket_order`
raises/times-out AFTER the parent leg is already live at IB, `_execute_trade`
leaves the row PENDING with `entry_order_id=None`; IB fills the parent; the
stale-pending reaper then falsely rejects it and the position becomes an
orphan the reconciler adopts as a SYNTHETIC `reconciled_excess` slice —
losing the real setup/intent and (pre-v235) re-arming an oversized bracket.

This module re-attributes that orphaned IB fill back to its ORIGINAL pending
trade: we MATCH a live IB position (that the bot isn't tracking as open) to
the best-fitting recent PENDING row and PROMOTE it to OPEN, preserving
`entered_by="bot_fired"`, setup_type, TQS and AI context.

Everything here is pure / side-effect free and fully unit-testable. The
promoter that consumes it (in trading_bot_service) submits NO orders — it
leaves the now-open trade for the existing (v235-clamped) naked-sweep to
protect.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional


def _norm_dir(value) -> str:
    s = (getattr(value, "value", None) or str(value or "")).lower()
    if s in ("long", "buy", "bot", "b"):
        return "long"
    if s in ("short", "sell", "sld", "s"):
        return "short"
    return s


def _age_seconds(pre_submit_at, now: datetime) -> Optional[float]:
    if not pre_submit_at:
        return None
    try:
        s = str(pre_submit_at).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds()
    except Exception:
        return None


def match_pending_to_orphan(
    orphan_symbol: str,
    orphan_signed_qty: float,
    pending_rows: List[Dict],
    now: datetime,
    *,
    min_age_s: int = 30,
    max_age_s: int = 3600,
    overfill_tolerance: float = 1.5,
) -> Optional[str]:
    """Return the `id` of the PENDING row that best matches an unattributed
    live IB position, or None.

    A candidate must share the symbol + direction (sign), have been
    pre-submitted between `min_age_s` (old enough that a normal fill would
    already have confirmed — avoids racing in-flight entries) and `max_age_s`
    ago, and have an order size that could plausibly produce the fill
    (`|orphan| <= shares * overfill_tolerance`). Among candidates, prefer the
    closest share count, then the oldest pre-submit.
    """
    sym = (orphan_symbol or "").upper()
    oqty = abs(int(round(orphan_signed_qty or 0)))
    if oqty < 1 or not sym:
        return None
    odir = "long" if orphan_signed_qty > 0 else "short"

    candidates = []  # (share_distance, -age, id)
    for p in pending_rows:
        if (p.get("symbol") or "").upper() != sym:
            continue
        if _norm_dir(p.get("direction")) != odir:
            continue
        age = _age_seconds(p.get("pre_submit_at"), now)
        if age is None or age < min_age_s or age > max_age_s:
            continue
        shares = int(p.get("shares") or 0)
        if shares < 1:
            continue
        if oqty > shares * overfill_tolerance:
            continue
        pid = p.get("id")
        if not pid:
            continue
        candidates.append((abs(shares - oqty), -age, pid))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    return candidates[0][2]


def build_promotion_update(qty_abs: int, fill_price: float, now_iso: str) -> Dict:
    """Field updates that flip a matched PENDING trade into a clean OPEN one.
    `entered_by` is intentionally NOT touched (stays "bot_fired")."""
    q = abs(int(qty_abs or 0))
    return {
        "status": "open",
        "fill_price": float(fill_price or 0.0),
        "executed_at": now_iso,
        "remaining_shares": q,
        "original_shares": q,
        "shares": q,
        "close_reason": None,
        "reaped_at": None,
    }
