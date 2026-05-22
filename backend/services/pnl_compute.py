"""
pnl_compute.py — v19.34.123 (Feb 2026)
─────────────────────────────────────────────────────────────────────────────
Shared close-PnL writer for every close path that doesn't go through
`position_manager.close_trade`.

WHY THIS EXISTS:
  Pre-v123 only `position_manager.close_trade()` computed `realized_pnl`
  on close. Every other close path — `operator_external_flatten`,
  `zombie_cleanup_v19_34_19`, `shrunk_to_zero_v19_34_20b`,
  `wrong_direction_phantom_swept_v19_29`, `_phantom_recovery_v19_34_27`,
  the OCA-ext detection path — set `status=CLOSED` and `exit_price` but
  left `realized_pnl` and `net_pnl` at their initial 0/None values.

  Result: `_daily_stats.net_pnl` aggregator saw ~$0 across most closes
  even when the broker showed −$25k. The kill-switch (which reads
  `_daily_stats.net_pnl`) couldn't fire. Setup grading was blind. The
  Closed Today panel showed dozens of "$0.00" rows that were actually
  realized losses.

  Surfaced during the Feb 2026 −$25k incident; mongoshell aggregate over
  `bot_trades` confirmed ~90% of closed rows had `net_pnl: 0 / null`.

CONTRACT:
  This module computes `realized_pnl` and `net_pnl` for a trade-shaped
  object at close time. It is INTENTIONALLY tolerant of partial data
  (best-effort fallback chain on exit_price) because the silent close
  paths are exactly the ones where IB doesn't hand us a fill — operator
  closed in TWS, OCA fired externally, zombie cleanup ran post-fact.

USAGE:
  Every silent close path replaces this pattern:
      trade.status = TradeStatus.CLOSED
      trade.closed_at = now_iso
      trade.close_reason = "<reason>"
      trade.unrealized_pnl = 0
  with:
      apply_close_pnl(trade, reason="<reason>")
      trade.status = TradeStatus.CLOSED
      # closed_at / close_reason / unrealized_pnl set by apply_close_pnl

  Returns the dict used (for logging / tests):
      {realized_pnl, net_pnl, exit_price, exit_price_source, commission}
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── v19.34.124 — alert_outcomes writer (best-effort, fire-and-forget) ──
# Synchronous pymongo client cached on first call. Falls back to a no-op
# silently if MONGO_URL is missing (preview pod, tests, etc.).

_AO_CLIENT = None  # cached MongoClient
_AO_DB = None


def _get_outcomes_collection():
    """Lazy-init the alert_outcomes collection handle. Returns None
    when MongoDB is unreachable / not configured so callers can skip
    cleanly."""
    global _AO_CLIENT, _AO_DB
    if _AO_DB is not None:
        return _AO_DB["alert_outcomes"]
    import os
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        return None
    try:
        from pymongo import MongoClient
        _AO_CLIENT = MongoClient(mongo_url, serverSelectionTimeoutMS=1500)
        _AO_DB = _AO_CLIENT[os.environ.get("DB_NAME", "tradecommand")]
        return _AO_DB["alert_outcomes"]
    except Exception as e:
        logger.debug("[pnl_compute] alert_outcomes mongo init failed: %s", e)
        return None


def _record_alert_outcome_bestEffort(
    trade: Any, reason: str, pnl: Dict[str, float],
    exit_price: float, exit_source: str,
) -> None:
    """Write one row to `alert_outcomes` from the trade's data. This is
    intentionally schema-COMPATIBLE with `enhanced_scanner.record_alert_outcome`
    so consumers (setup-grading, learning loop, /diagnostic/setup-winrate-
    breakdown) can read both without branching."""
    coll = _get_outcomes_collection()
    if coll is None:
        return
    realized = pnl.get("realized_pnl", 0.0)
    # Outcome derived from realized PnL (single source of truth post-v123).
    if realized > 0:
        outcome = "won"
    elif realized < 0:
        outcome = "lost"
    else:
        outcome = "scratch"

    # Best-effort R-multiple: (exit - entry) / (entry - stop)
    r_multiple = 0.0
    try:
        entry = float(getattr(trade, "fill_price", 0) or 0)
        stop = float(getattr(trade, "stop_price", 0) or getattr(trade, "stop_loss", 0) or 0)
        if entry > 0 and stop > 0:
            risk_per_share = abs(entry - stop)
            if risk_per_share > 0:
                d_obj = getattr(trade, "direction", None)
                dv = getattr(d_obj, "value", str(d_obj) if d_obj else "long").lower()
                if dv == "long":
                    pps = exit_price - entry
                else:
                    pps = entry - exit_price
                r_multiple = round(pps / risk_per_share, 3)
    except Exception:
        pass

    doc = {
        # Use trade.id as the de-duplication / join key. Schema is a
        # SUPERSET of scanner's writer — extra fields are additive.
        "alert_id": getattr(trade, "id", None) or getattr(trade, "alert_id", None),
        "trade_id": getattr(trade, "id", None),
        "symbol": getattr(trade, "symbol", None),
        "setup_type": getattr(trade, "setup_type", None),
        "direction": (lambda d: getattr(d, "value", str(d) if d else None))(
            getattr(trade, "direction", None)
        ),
        "outcome": outcome,
        "pnl": realized,
        "net_pnl": pnl.get("net_pnl", 0.0),
        "r_multiple": r_multiple,
        "trade_grade": getattr(trade, "trade_grade", None),
        "entry_price": getattr(trade, "fill_price", None),
        "exit_price": exit_price,
        "exit_price_source": exit_source,
        "stop_loss": getattr(trade, "stop_price", None) or getattr(trade, "stop_loss", None),
        "target": getattr(trade, "tp_price", None) or getattr(trade, "target", None),
        "shares": pnl.get("shares") or getattr(trade, "shares", None),
        "close_reason": reason,
        "closed_at": getattr(trade, "closed_at", datetime.now(timezone.utc).isoformat()),
        "recorded_by": "pnl_compute_v19_34_124",
    }
    try:
        # Upsert keyed on trade_id so retry-on-failure paths don't
        # create duplicate outcome rows.
        coll.update_one(
            {"trade_id": doc["trade_id"]},
            {"$set": doc},
            upsert=True,
        )
    except Exception as e:
        logger.debug("[pnl_compute] alert_outcomes upsert failed: %s", e)

    # v19.34.88 — Post-stop cooldown stamp. On any close whose reason
    # starts with "stop" (stop_loss, stop_loss_phantom_recovery,
    # stop_loss_trailing, etc.), record the (symbol, setup_base) pair
    # into the in-memory cooldown registry so opportunity_evaluator
    # can refuse same-symbol+setup re-entries for the next
    # POST_STOP_COOLDOWN_MINUTES window.
    try:
        if str(reason or "").lower().startswith("stop"):
            from services.post_stop_cooldown import get_registry
            get_registry().record_stop(
                symbol=getattr(trade, "symbol", None),
                setup_type=getattr(trade, "setup_type", None),
            )
    except Exception as _cd_err:
        logger.debug(
            "[v19.34.88 post-stop-cooldown] stamp failed (non-fatal): %s",
            _cd_err,
        )


def compute_close_pnl(
    *,
    direction: str,
    fill_price: float,
    exit_price: float,
    shares: int,
    commission: float = 0.0,
) -> Dict[str, float]:
    """Pure-math PnL computation. Direction: 'long' or 'short'.
    Long PnL  = (exit - fill) × shares − commission
    Short PnL = (fill - exit) × shares − commission
    """
    d = (direction or "long").strip().lower()
    sh = abs(int(shares or 0))
    fp = float(fill_price or 0.0)
    xp = float(exit_price or 0.0)
    if d == "short":
        gross = (fp - xp) * sh
    else:
        gross = (xp - fp) * sh
    net = gross - float(commission or 0.0)
    return {
        "realized_pnl": round(gross, 2),
        "net_pnl":      round(net, 2),
        "commission":   round(float(commission or 0.0), 2),
    }


def _resolve_exit_price(trade: Any, explicit: Optional[float]) -> tuple[float, str]:
    """Best-effort exit price + audit source label.

    Priority:
      1. Explicit (caller passed in a known fill_price from IB execution)
      2. trade.exit_price (already set by an earlier close attempt)
      3. trade.current_price (last quote from pusher)
      4. trade.fill_price (PnL=0 marker — last resort)
    """
    if explicit is not None:
        try:
            v = float(explicit)
            if v > 0:
                return v, "explicit"
        except (TypeError, ValueError):
            pass
    for attr, label in (
        ("exit_price",    "existing_exit_price"),
        ("current_price", "current_price"),
        ("fill_price",    "fill_price_fallback"),
    ):
        try:
            v = float(getattr(trade, attr, 0) or 0)
            if v > 0:
                return v, label
        except (TypeError, ValueError):
            continue
    return 0.0, "no_price_available"


def apply_close_pnl(
    trade: Any,
    *,
    reason: str,
    exit_price: Optional[float] = None,
    commission: Optional[float] = None,
    now_iso: Optional[str] = None,
    record_outcome: bool = True,
) -> Dict[str, Any]:
    """Compute and write realized_pnl + net_pnl onto `trade` in-place.
    ALSO writes: exit_price, close_reason, closed_at, unrealized_pnl=0,
    remaining_shares=0, exit_price_source (audit breadcrumb).

    v19.34.124: When `record_outcome=True` (default), ALSO writes an
    `alert_outcomes` row to MongoDB so the setup-grading + learning
    loop have data. Best-effort fire-and-forget — failures here never
    block the close.

    Returns the computed dict for logging / tests. NEVER raises — silent
    failures are logged and the function returns a best-effort dict.
    """
    out: Dict[str, Any] = {"reason": reason}
    try:
        # Shares at close = original shares filled (NOT remaining, which
        # may already be 0 from a peel). For partial-peel close paths,
        # the caller adjusts via the explicit `shares_override` semantics
        # below (passed via attribute) if needed.
        shares = int(abs(getattr(trade, "shares", 0) or 0))
        if hasattr(trade, "_close_shares_override"):
            try:
                shares = int(abs(getattr(trade, "_close_shares_override", 0) or 0))
            except Exception:
                pass

        direction = str(getattr(trade, "direction", "long"))
        # Handle TradeDirection enum
        if hasattr(getattr(trade, "direction", None), "value"):
            direction = str(trade.direction.value)
        direction = direction.strip().lower()

        fill_price = float(getattr(trade, "fill_price", 0) or 0)
        resolved_exit, source = _resolve_exit_price(trade, exit_price)

        # Commission: caller-supplied OR existing total_commissions OR 0
        if commission is None:
            commission = float(getattr(trade, "total_commissions", 0) or 0)

        pnl = compute_close_pnl(
            direction=direction,
            fill_price=fill_price,
            exit_price=resolved_exit,
            shares=shares,
            commission=commission,
        )

        # Write back onto trade
        trade.exit_price = resolved_exit
        trade.realized_pnl = pnl["realized_pnl"]
        trade.net_pnl = pnl["net_pnl"]
        trade.unrealized_pnl = 0.0
        trade.remaining_shares = 0
        trade.close_reason = reason
        trade.closed_at = now_iso or datetime.now(timezone.utc).isoformat()
        # Audit breadcrumb so downstream readers know how exit_price was
        # resolved — operators reviewing tape see "approximated from
        # current_price" vs an authoritative IB fill.
        try:
            trade._exit_price_source = source
        except Exception:
            pass

        out.update(pnl)
        out["exit_price"] = resolved_exit
        out["exit_price_source"] = source
        out["shares"] = shares
        out["direction"] = direction

        # v19.34.124 — Feed alert_outcomes for grading + learning loop.
        # Pre-v124 only `enhanced_scanner.record_alert_outcome` wrote to
        # this collection AND it required alert_id ∈ scanner._live_alerts
        # (which excluded reconciler/operator close paths). Result:
        # `alert_outcomes` collection was empty / stale, EOD grading and
        # learning loop had no signal. Direct write here covers EVERY
        # close path that uses apply_close_pnl.
        if record_outcome:
            try:
                _record_alert_outcome_bestEffort(trade, reason, pnl, resolved_exit, source)
            except Exception as _ao_err:
                logger.debug(
                    "[pnl_compute] alert_outcomes write skipped: %s", _ao_err,
                )

        return out
    except Exception as exc:
        logger.error(
            "[pnl_compute] apply_close_pnl FAILED for %s (reason=%s): %s",
            getattr(trade, "id", "?"), reason, exc, exc_info=True,
        )
        # Last-resort: at minimum stamp the close metadata so subsequent
        # readers still see status/closed_at correctly.
        try:
            trade.closed_at = now_iso or datetime.now(timezone.utc).isoformat()
            trade.close_reason = reason
            trade.unrealized_pnl = 0.0
            trade.remaining_shares = 0
        except Exception:
            pass
        out["error"] = str(exc)[:200]
        return out
