"""
orphan_gtc_reconciler.py — v19.34.66 (2026-02-09)

Long-missing audit pass on the BOT's order management surface.

Background — every prior reconciler in the codebase
(`position_reconciler.py`, `unmatched_short_close_service.py`, the
zombie-sweep, the drift-guard) starts from the bot's view of the world.
None of them ever asked "what does IB still have that the bot has
forgotten about?". That blind spot let the 2026-05-04 GTC bracket
sell-legs (NXPI, VALE×2, NCLH, ELV — 10 orders total, ~7,800 protective
shares) sit naked at IB for 5 days after the user manually flattened
the underlying longs. If any one of those stops had triggered, IB would
have shorted the user that many shares with no protection.

This service queries IB's authoritative open-orders list, joins to
`bot_trades` (bot's tracked-trade memory) and IB positions, and
classifies every working order at IB into one of:

    tracked              — order matches a bot trade with a real IB position behind it (OK)
    naked_no_position    — bot/IB has no position; order would short on trigger
    orphan_no_trade      — bot has no `bot_trades` row referencing this order_id
    mismatched_size      — order qty exceeds the IB position size (over-protected)

A separate verdict, `awaiting_data`, is returned when the data sources
necessary for full classification are temporarily unavailable (IB
disconnected, pusher stale) — never silently treated as `tracked`.

Design constraints:
  • Pure classifier function — `classify_open_orders(...)` is testable
    with no IB / Mongo dependencies. Uses ONLY the data the caller
    feeds in.
  • Non-mutating by default. The orchestrator entry-points return the
    verdict table; cancellation is gated behind a separate function
    that requires the caller to confirm the verdict ≠ tracked.
  • Three deployment surfaces use the same classifier:
      1. Boot tripwire — startup ERROR per orphan found.
      2. Periodic background reconciler — every 90s while running.
      3. Operator dashboard — `GET /api/safety/orphan-gtc-orders`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── verdict enum-equivalent (string for JSON-friendliness) ─────────────────

VERDICT_TRACKED = "tracked"
VERDICT_NAKED_NO_POSITION = "naked_no_position"
VERDICT_ORPHAN_NO_TRADE = "orphan_no_trade"
VERDICT_MISMATCHED_SIZE = "mismatched_size"
VERDICT_AWAITING_DATA = "awaiting_data"

# Verdicts that are SAFE to auto-cancel. `mismatched_size` is intentionally
# excluded — could be a partial scale-out the bot legitimately reduced. The
# operator must review before cancelling those.
SAFE_TO_AUTO_CANCEL = frozenset({VERDICT_NAKED_NO_POSITION, VERDICT_ORPHAN_NO_TRADE})


# v19.34.151 — distinct verdict for pending intraday entry orders
# cancelled by the EOD sweep. Separate from `orphan_no_trade` so the
# operator can tell the two cleanup paths apart in audit logs. Also
# part of SAFE_TO_AUTO_CANCEL.
VERDICT_EOD_INTRADAY_ENTRY = "eod_intraday_entry"
SAFE_TO_AUTO_CANCEL = frozenset({
    VERDICT_NAKED_NO_POSITION,
    VERDICT_ORPHAN_NO_TRADE,
    VERDICT_EOD_INTRADAY_ENTRY,
})


# Order statuses that count as "working" at IB (will fire on price trigger).
WORKING_ORDER_STATUSES = frozenset({
    "submitted", "presubmitted", "pendingsubmit",
    "preliminary_submitted", "pending_submit",
})


@dataclass
class OrderVerdict:
    """One IB open order classified against bot/position state."""
    ib_order_id: int
    perm_id: Optional[int]
    symbol: str
    action: str           # "BUY" | "SELL"
    quantity: int
    order_type: str       # "STP" | "LMT" | "STP_LMT" | …
    limit_price: Optional[float]
    stop_price: Optional[float]
    time_in_force: str    # "DAY" | "GTC" | …
    status: str
    verdict: str          # one of the VERDICT_* constants
    reasons: List[str] = field(default_factory=list)
    bot_trade_id: Optional[str] = None
    ib_position_size: Optional[float] = None  # signed (long > 0, short < 0)
    submitted_at: Optional[str] = None        # iso8601 (best-effort)


# ─── pure classifier ────────────────────────────────────────────────────────


def _normalise_status(s: Optional[str]) -> str:
    return (s or "").strip().lower().replace("-", "").replace(" ", "")


def _normalise_action(a: Optional[str]) -> str:
    return (a or "").strip().upper()


def _is_gtc_protective_close(order: Dict[str, Any]) -> bool:
    """Filter: is this a GTC SELL-side protective leg we should audit?

    Out of scope (= return False) for v19.34.66:
      • DAY orders (will auto-expire at session end anyway)
      • OPENING entries (BUY-side limit at-or-below market)
    In scope (= return True):
      • GTC + (STP / STP_LMT / LMT-with-limit-above-market) — the
        protective sell legs that survive bot restarts.
      • Inverse for shorts: GTC BUY protective legs.
    """
    tif = (order.get("time_in_force") or order.get("tif") or "").upper()
    if tif and tif != "GTC":
        return False
    return True


def classify_open_orders(
    *,
    ib_open_orders: List[Dict[str, Any]],
    ib_positions: List[Dict[str, Any]],
    bot_trades: List[Dict[str, Any]],
    only_gtc: bool = True,
) -> List[OrderVerdict]:
    """Pure classifier. No IB calls, no Mongo, no globals.

    Args:
      ib_open_orders: list of dicts with at minimum:
          {ib_order_id|order_id|orderId, symbol, action, quantity,
           order_type, limit_price, stop_price, time_in_force, status,
           perm_id|permId (optional), submitted_at (optional)}
      ib_positions: list of dicts with at minimum:
          {symbol, position}  (signed; long > 0, short < 0)
      bot_trades: list of dicts (rows from `bot_trades` collection)
          with at minimum: {id, symbol, status, remaining_shares,
          stop_order_id, target_order_id} — anything that ties a
          bot trade to an IB order_id.
      only_gtc: if True (default), DAY orders are excluded — they
          self-cancel at session end.

    Returns:
      List[OrderVerdict] with one entry per audited order.
    """
    # Index positions by symbol (uppercased).
    pos_by_sym: Dict[str, float] = {}
    for p in ib_positions or []:
        sym = (p.get("symbol") or "").upper()
        if not sym:
            continue
        try:
            pos_by_sym[sym] = float(p.get("position") or 0)
        except (TypeError, ValueError):
            pos_by_sym[sym] = 0.0

    # Index bot trades by every order_id they claim (stop, target,
    # entry — all are candidates for a join).
    trade_by_order_id: Dict[int, Dict[str, Any]] = {}
    for t in bot_trades or []:
        for key in ("stop_order_id", "target_order_id", "entry_order_id",
                    "ib_order_id"):
            v = t.get(key)
            if v is None:
                continue
            try:
                trade_by_order_id[int(v)] = t
            except (TypeError, ValueError):
                pass
        # Also accept lists like target_order_ids
        for key in ("target_order_ids",):
            for v in (t.get(key) or []):
                try:
                    trade_by_order_id[int(v)] = t
                except (TypeError, ValueError):
                    pass

    out: List[OrderVerdict] = []

    for o in ib_open_orders or []:
        # Skip non-working orders defensively (e.g. cancelled showing in
        # a stale snapshot).
        status_norm = _normalise_status(o.get("status"))
        if status_norm and status_norm not in WORKING_ORDER_STATUSES:
            continue

        if only_gtc and not _is_gtc_protective_close(o):
            continue

        sym = (o.get("symbol") or "").upper()
        action = _normalise_action(o.get("action"))
        try:
            qty = int(abs(float(o.get("quantity") or 0)))
        except (TypeError, ValueError):
            qty = 0

        # Pull the IB order_id from any of the common shapes.
        ib_order_id = (
            o.get("ib_order_id") or o.get("order_id") or o.get("orderId")
        )
        try:
            ib_order_id_int = int(ib_order_id) if ib_order_id is not None else 0
        except (TypeError, ValueError):
            ib_order_id_int = 0

        perm_id = o.get("perm_id") or o.get("permId")
        try:
            perm_id_int = int(perm_id) if perm_id is not None else None
        except (TypeError, ValueError):
            perm_id_int = None

        verdict_obj = OrderVerdict(
            ib_order_id=ib_order_id_int,
            perm_id=perm_id_int,
            symbol=sym,
            action=action,
            quantity=qty,
            order_type=(o.get("order_type") or o.get("orderType") or "").upper(),
            limit_price=_safe_float(o.get("limit_price") or o.get("lmtPrice")),
            stop_price=_safe_float(o.get("stop_price") or o.get("auxPrice")),
            time_in_force=(o.get("time_in_force") or o.get("tif") or "").upper(),
            status=o.get("status") or "",
            verdict=VERDICT_TRACKED,  # reset below
            submitted_at=o.get("submitted_at"),
        )

        # 1) Position lookup (signed).
        ib_pos = pos_by_sym.get(sym, 0.0)
        verdict_obj.ib_position_size = ib_pos
        ib_pos_abs = abs(ib_pos)

        # 2) Bot trade lookup by ib_order_id.
        matched_trade = trade_by_order_id.get(ib_order_id_int)
        if matched_trade is None and perm_id_int is not None:
            matched_trade = trade_by_order_id.get(perm_id_int)
        verdict_obj.bot_trade_id = (
            matched_trade.get("id") or matched_trade.get("trade_id")
        ) if matched_trade else None

        # 3) Classify.
        # Naked = no position behind the protective order at all. This is
        # the most dangerous case — the order would create a NEW short
        # (or long for buy-side) when triggered.
        if ib_pos_abs < 1.0:
            verdict_obj.verdict = VERDICT_NAKED_NO_POSITION
            verdict_obj.reasons.append(
                f"IB position for {sym} is {ib_pos:+.0f} — "
                f"order would short on trigger" if action == "SELL"
                else f"IB position for {sym} is {ib_pos:+.0f} — "
                     f"order would over-buy on trigger"
            )
        # Orphan = position exists but the bot lost track of the order.
        elif matched_trade is None:
            verdict_obj.verdict = VERDICT_ORPHAN_NO_TRADE
            verdict_obj.reasons.append(
                f"no bot_trade row references ib_order_id={ib_order_id_int} "
                f"or perm_id={perm_id_int}"
            )
        # Mismatched size = bot tracks order but qty > current IB position.
        elif qty > ib_pos_abs + 0.5:  # 0.5 tolerance for float rounding
            verdict_obj.verdict = VERDICT_MISMATCHED_SIZE
            verdict_obj.reasons.append(
                f"order qty {qty} > |IB position| {ib_pos_abs:.0f} — "
                f"would over-execute on trigger"
            )
        else:
            verdict_obj.verdict = VERDICT_TRACKED
            verdict_obj.reasons.append(
                f"matched bot_trade {verdict_obj.bot_trade_id}, "
                f"qty {qty} ≤ |IB position| {ib_pos_abs:.0f}"
            )

        out.append(verdict_obj)

    return out


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_intraday_entries_for_eod_sweep(
    *,
    ib_open_orders: List[Dict[str, Any]],
    bot_trades: List[Dict[str, Any]],
) -> List[OrderVerdict]:
    """v19.34.151 — find pending DAY entry orders for intraday trades
    that should be cancelled at EOD.

    Distinct from `classify_open_orders` because:
      • Targets DAY orders (auto-cancelled by exchange overnight, but
        we want to cancel them BEFORE 4:00 PM so they don't trigger in
        the last 5 minutes of session).
      • Joins each order to the bot_trade that placed it (via
        `entry_order_id`); only flags orders where the bot_trade's
        `close_at_eod` is True. SWING / POSITION orders (close_at_eod
        False) are intentionally left alive — they're meant to fill
        overnight or next-session.
      • Ignores stop / target legs — those are covered by
        `_cancel_ib_bracket_orders` inside `close_trade` itself when
        the parent position closes, and by the existing
        `classify_open_orders` path for orphan GTC sweeps.

    Returns OrderVerdict instances with verdict=VERDICT_EOD_INTRADAY_ENTRY
    so the existing `cancel_orphan_gtc_orders` pipeline can process
    them via the SAFE_TO_AUTO_CANCEL set.
    """
    # Index bot trades by entry_order_id ONLY — we don't want to match
    # on stop/target IDs here (those are separate sweep targets).
    trade_by_entry_oid: Dict[int, Dict[str, Any]] = {}
    for t in bot_trades or []:
        v = t.get("entry_order_id")
        if v in (None, ""):
            continue
        try:
            trade_by_entry_oid[int(v)] = t
        except (TypeError, ValueError):
            continue

    out: List[OrderVerdict] = []
    for o in ib_open_orders or []:
        # Skip non-working orders defensively.
        status_norm = _normalise_status(o.get("status"))
        if status_norm and status_norm not in WORKING_ORDER_STATUSES:
            continue

        order_type = (o.get("order_type") or o.get("orderType") or "").upper()
        tif = (o.get("time_in_force") or o.get("tif") or "").upper()

        # Scope: pending LMT / STP / STP_LMT entries that haven't yet
        # filled. MKT orders aren't normally pending (they fill on
        # submission), but include them defensively. GTC orders are
        # the orphan-bracket case — out of scope.
        if tif and tif != "DAY":
            continue
        if order_type not in ("LMT", "STP", "STP_LMT", "MKT"):
            continue

        try:
            oid = int(
                o.get("ib_order_id") or o.get("order_id")
                or o.get("orderId") or 0
            )
        except (TypeError, ValueError):
            oid = 0
        if oid == 0:
            continue

        matched = trade_by_entry_oid.get(oid)
        if matched is None:
            # Unmatched DAY entry. We intentionally don't auto-cancel
            # these — could be a manual TWS order the operator placed.
            # Operator can use the postmortem to spot them.
            continue

        # Skip if the matched trade is NOT flagged for EOD close
        # (swing / position trades stay alive overnight).
        # v19.34.261 — resolve eligibility from the trade-style POLICY
        # (single source of truth), NOT the per-trade `close_at_eod`
        # attribute, which can be stale vs policy (79 stored-vs-policy
        # mismatches found 2026-06-03). is_eod_sweep_eligible(False) ⇒
        # swing/position/investment — leave its pending orders alive.
        from services.order_policy_registry import is_eod_sweep_eligible
        if not is_eod_sweep_eligible(matched):
            continue

        # Also skip if the matched trade has already filled (status
        # OPEN means the parent entry succeeded — what's still
        # pending must be a stop or target leg, handled elsewhere).
        status = (matched.get("status") or "").lower()
        if status in ("open", "partial", "closed", "cancelled"):
            continue

        try:
            qty = int(abs(float(o.get("quantity") or 0)))
        except (TypeError, ValueError):
            qty = 0

        out.append(OrderVerdict(
            ib_order_id=oid,
            perm_id=(int(o.get("perm_id") or o.get("permId") or 0) or None),
            symbol=(o.get("symbol") or "").upper(),
            action=_normalise_action(o.get("action")),
            quantity=qty,
            order_type=order_type,
            limit_price=_safe_float(o.get("limit_price") or o.get("lmtPrice")),
            stop_price=_safe_float(o.get("stop_price") or o.get("auxPrice")),
            time_in_force=tif or "DAY",
            status=o.get("status") or "",
            verdict=VERDICT_EOD_INTRADAY_ENTRY,
            reasons=[
                f"EOD sweep: pending {order_type} entry for intraday "
                f"trade {matched.get('id')} (setup={matched.get('setup_type')}, "
                f"close_at_eod=True). Cancelled to prevent late-session fill."
            ],
            bot_trade_id=matched.get("id") or matched.get("trade_id"),
            submitted_at=o.get("submitted_at"),
        ))

    return out


# ─── orchestrator: pulls data and runs the classifier ───────────────────────


async def audit_orphan_gtc_orders(
    *,
    bot=None,
    only_gtc: bool = True,
) -> Dict[str, Any]:
    """Pull live IB open orders + positions + bot_trades, then classify.

    Returns a JSON-friendly dict the API endpoint can return as-is:
      {
        "success": bool,
        "checked_at": iso,
        "data_sources": {ib_orders: ..., ib_positions: ..., bot_trades: ...},
        "verdicts": [...],
        "summary": {tracked: N, naked_no_position: N, ...},
      }

    Failure modes return success=False with `reason` populated and
    `verdicts=[]`. NEVER raises — boot tripwire / periodic loop must
    not crash on data-source hiccups.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    data_sources: Dict[str, Any] = {}

    # 1) Open orders — try IB-direct first (authoritative), fall back to
    # the pusher relay's `_ib_service.get_open_orders()` (slightly stale
    # but covers when direct is offline).
    ib_orders, src_orders = await _fetch_ib_open_orders()
    data_sources["ib_orders"] = src_orders

    if ib_orders is None:
        return {
            "success": False,
            "reason": "ib_orders_unavailable",
            "data_sources": data_sources,
            "verdicts": [],
            "summary": _empty_summary(),
            "checked_at": started_at,
        }

    # 2) IB positions — pusher snapshot is the canonical source for
    # positions across the codebase. v19.34.28 L2b-hotfix1: use the
    # ASYNC helper here (we're inside `async def audit_orphan_gtc_orders`)
    # to avoid the sync→async deadlock that wedged boot on 2026-05-15.
    ib_positions, src_positions = await _fetch_ib_positions_async()
    data_sources["ib_positions"] = src_positions

    # 3) bot_trades — Mongo, via the bot's `_db` handle if available.
    bot_trades, src_bt = _fetch_bot_trades(bot)
    data_sources["bot_trades"] = src_bt

    verdicts = classify_open_orders(
        ib_open_orders=ib_orders,
        ib_positions=ib_positions,
        bot_trades=bot_trades,
        only_gtc=only_gtc,
    )

    # Build summary counts.
    summary = _empty_summary()
    for v in verdicts:
        summary[v.verdict] = summary.get(v.verdict, 0) + 1

    return {
        "success": True,
        "data_sources": data_sources,
        "verdicts": [v.__dict__ for v in verdicts],
        "summary": summary,
        "checked_at": started_at,
    }


def _empty_summary() -> Dict[str, int]:
    return {
        VERDICT_TRACKED: 0,
        VERDICT_NAKED_NO_POSITION: 0,
        VERDICT_ORPHAN_NO_TRADE: 0,
        VERDICT_MISMATCHED_SIZE: 0,
        VERDICT_EOD_INTRADAY_ENTRY: 0,
    }


async def _fetch_ib_open_orders() -> Tuple[Optional[List[Dict[str, Any]]], Dict[str, Any]]:
    """Try IB-direct → pusher-relay. Returns (orders or None, source-info)."""
    src: Dict[str, Any] = {"tier": None, "ok": False, "error": None}

    # Tier 1: ib_direct (clientId=11) — authoritative.
    try:
        from services.ib_direct_service import get_ib_direct_service
        ib_direct = get_ib_direct_service()
        if ib_direct is not None and hasattr(ib_direct, "_ib") and ib_direct.is_connected():
            try:
                trades = ib_direct._ib.trades()
                normalized: List[Dict[str, Any]] = []
                for t in trades or []:
                    status = getattr(t.orderStatus, "status", "") if t.orderStatus else ""
                    if _normalise_status(status) not in WORKING_ORDER_STATUSES:
                        continue
                    contract = t.contract
                    order = t.order
                    normalized.append({
                        "ib_order_id": int(getattr(order, "orderId", 0) or 0),
                        "perm_id": int(getattr(order, "permId", 0) or 0) or None,
                        "symbol": (getattr(contract, "symbol", "") or "").upper(),
                        "action": (getattr(order, "action", "") or "").upper(),
                        "quantity": int(abs(float(getattr(order, "totalQuantity", 0) or 0))),
                        "order_type": (getattr(order, "orderType", "") or "").upper(),
                        "limit_price": _safe_float(getattr(order, "lmtPrice", None)),
                        "stop_price": _safe_float(getattr(order, "auxPrice", None)),
                        "time_in_force": (getattr(order, "tif", "") or "").upper(),
                        "status": status,
                    })
                src["tier"] = "ib_direct"
                src["ok"] = True
                src["count"] = len(normalized)
                return normalized, src
            except Exception as e:  # pragma: no cover
                src["tier_attempted"] = "ib_direct"
                src["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:  # pragma: no cover
        src["tier_attempted"] = "ib_direct"
        src["error"] = f"{type(e).__name__}: {e}"

    # Tier 2: pusher-relay via existing `_ib_service.get_open_orders()`.
    try:
        from routers.ib import _ib_service
        if _ib_service is not None:
            orders = await _ib_service.get_open_orders()
            src["tier"] = "ib_service_relay"
            src["ok"] = True
            src["count"] = len(orders or [])
            return list(orders or []), src
    except Exception as e:
        src["tier_attempted"] = "ib_service_relay"
        src["error"] = f"{type(e).__name__}: {e}"

    # Tier 3 (v19.34.89): direct read of `_pushed_ib_data["orders"]`.
    # On native DGX deployments tiers 1 and 2 both rely on a live cloud
    # ↔ IB connection that doesn't exist (pusher-only). The pusher
    # (v19.34.85+) publishes its `openTrades()` snapshot here on every
    # push — that's the authoritative source for this deployment shape.
    try:
        from routers.ib import _pushed_ib_data
        raw_orders = _pushed_ib_data.get("orders") or []
        if isinstance(raw_orders, dict):
            raw_orders = raw_orders.get("orders", [])
        normalized: List[Dict[str, Any]] = []
        for o in raw_orders:
            try:
                status = (o.get("status") or "")
                if _normalise_status(status) not in WORKING_ORDER_STATUSES:
                    continue
                oid_raw = o.get("order_id") or o.get("orderId")
                if oid_raw is None:
                    continue
                normalized.append({
                    "ib_order_id": int(oid_raw),
                    "perm_id": int(o.get("perm_id") or 0) or None,
                    "symbol": (o.get("symbol") or "").upper(),
                    "action": (o.get("action") or "").upper(),
                    "quantity": int(abs(float(o.get("quantity") or o.get("remaining") or 0))),
                    "order_type": (o.get("order_type") or "").upper(),
                    "limit_price": _safe_float(o.get("limit_price")),
                    "stop_price": _safe_float(o.get("stop_price") or o.get("aux_price")),
                    "time_in_force": (o.get("tif") or "").upper(),
                    "status": status,
                })
            except Exception:
                continue
        src["tier"] = "pusher_orders_snapshot"
        src["ok"] = True
        src["count"] = len(normalized)
        return normalized, src
    except Exception as e:
        src["tier_attempted"] = "pusher_orders_snapshot"
        src["error"] = f"{type(e).__name__}: {e}"

    return None, src


def _fetch_ib_positions() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    src: Dict[str, Any] = {"tier": None, "ok": False}

    # ── v19.34.28 Patch L2b-hotfix1 — ib_direct fresh-positions fast path ──
    # NOTE: This helper is SYNCHRONOUS. The earlier L2b attempt tried to
    # bridge sync→async via a ThreadPoolExecutor when called from inside
    # a running event loop, but that deadlocks because ib_async's
    # event loop is owned by the main thread and the child thread can't
    # await on it. Real-world impact: backend wedged for 162s on
    # _startup_orphan_gtc_audit on 2026-05-15.
    #
    # Correct behaviour: when called from sync code OUTSIDE a running
    # loop (e.g. boot audit before the main loop starts, or pytest),
    # we can briefly spin up an event loop to await ib_direct. When
    # called from sync code INSIDE a running loop, we MUST NOT block —
    # fall through to the pusher snapshot. The async callers
    # (audit_orphan_gtc_orders, naked_position_sweep, position
    # reconcilers) reach ib_direct through the async helper
    # `position_reconciler._l2b_fetch_ib_positions` instead.
    order_path = (os.environ.get("BOT_ORDER_PATH", "pusher") or "pusher").strip().lower()
    if order_path == "direct" and not _is_running_loop():
        try:
            from services.ib_direct_service import get_ib_direct_service
            ib_direct = get_ib_direct_service()
            if ib_direct is not None and ib_direct.is_connected():
                fresh = asyncio.run(ib_direct.get_positions_fresh())
                if fresh:
                    src["tier"] = "ib_direct_fresh"
                    src["ok"] = True
                    src["count"] = len(fresh)
                    return fresh, src
        except Exception as e:
            # Fall through to pusher snapshot — don't fail callers.
            src["ib_direct_error"] = f"{type(e).__name__}: {str(e)[:120]}"

    try:
        from routers.ib import get_pushed_positions, is_pusher_connected
        positions = get_pushed_positions() or []
        src["tier"] = src.get("tier") or "pusher_snapshot"
        src["ok"] = True
        src["pusher_connected"] = bool(is_pusher_connected())
        src["count"] = len(positions)
        return positions, src
    except Exception as e:
        src["error"] = f"{type(e).__name__}: {e}"
        return [], src


def _is_running_loop() -> bool:
    """True if we're inside an event loop (e.g. called from async code)."""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


async def _fetch_ib_positions_async() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """v19.34.28 L2b-hotfix1 — async sibling of `_fetch_ib_positions`.

    Async callers (audit_orphan_gtc_orders, etc.) should use THIS helper
    so the ib-direct fresh path can be awaited natively without the
    sync→async deadlock that wedged the boot audit on 2026-05-15.
    """
    src: Dict[str, Any] = {"tier": None, "ok": False}
    order_path = (os.environ.get("BOT_ORDER_PATH", "pusher") or "pusher").strip().lower()
    if order_path == "direct":
        try:
            from services.ib_direct_service import get_ib_direct_service
            ib_direct = get_ib_direct_service()
            if ib_direct is not None and ib_direct.is_connected():
                fresh = await asyncio.wait_for(
                    ib_direct.get_positions_fresh(), timeout=5.0,
                )
                if fresh:
                    src["tier"] = "ib_direct_fresh"
                    src["ok"] = True
                    src["count"] = len(fresh)
                    return fresh, src
        except Exception as e:
            src["ib_direct_error"] = f"{type(e).__name__}: {str(e)[:120]}"

    try:
        from routers.ib import get_pushed_positions, is_pusher_connected
        positions = get_pushed_positions() or []
        src["tier"] = src.get("tier") or "pusher_snapshot"
        src["ok"] = True
        src["pusher_connected"] = bool(is_pusher_connected())
        src["count"] = len(positions)
        return positions, src
    except Exception as e:
        src["error"] = f"{type(e).__name__}: {e}"
        return [], src


def _fetch_bot_trades(bot) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Pull every bot_trade row that COULD reference an open order.

    Includes status in {open, partial} (active) AND closed/zombie rows
    (so we still see when an old row references an order_id that's
    still alive at IB — which is exactly the orphan case).
    """
    src: Dict[str, Any] = {"tier": None, "ok": False, "count": 0}
    try:
        db = getattr(bot, "_db", None) if bot is not None else None
        if db is None:
            try:
                from database import get_database
                db = get_database()
            except Exception:
                db = None
        if db is None:
            src["error"] = "no_db"
            return [], src

        # Project only the fields the classifier needs — keeps Mongo I/O
        # cheap even on bots with thousands of historical trades.
        proj = {
            "_id": 0, "id": 1, "trade_id": 1, "symbol": 1, "status": 1,
            "shares": 1, "remaining_shares": 1, "stop_order_id": 1,
            "target_order_id": 1, "target_order_ids": 1, "entry_order_id": 1,
            "ib_order_id": 1, "executed_at": 1, "close_reason": 1,
        }
        # Pull anything from the last 30d — older orphans are fringe and
        # would need the operator's audit trail anyway. The 30d window
        # covers any bot-restart-then-forget scenario in normal use.
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        cursor = db["bot_trades"].find(
            {"$or": [
                {"executed_at": {"$gte": cutoff}},
                {"executed_at": {"$exists": False}},
            ]},
            proj,
        ).limit(2000)  # generous; protects against runaway scans
        rows = list(cursor)
        src["tier"] = "mongo_bot_trades"
        src["ok"] = True
        src["count"] = len(rows)
        return rows, src
    except Exception as e:
        src["error"] = f"{type(e).__name__}: {e}"
        return [], src


# ─── cancellation helper ────────────────────────────────────────────────────


async def cancel_orphan_gtc_orders(
    *,
    verdicts_to_cancel: List[OrderVerdict],
) -> Dict[str, Any]:
    """Cancel a list of pre-classified orders. Caller MUST pass only
    `OrderVerdict` instances whose `verdict` is in `SAFE_TO_AUTO_CANCEL`.

    Refuses anything else — fail-closed. The endpoint layer enforces
    this with a verdict re-check before calling.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    summary: Dict[str, Any] = {
        "started_at": started_at,
        "requested": len(verdicts_to_cancel),
        "cancelled": [],
        "errors": [],
        "refused_unsafe": [],
    }

    safe = [v for v in verdicts_to_cancel if v.verdict in SAFE_TO_AUTO_CANCEL]
    summary["refused_unsafe"] = [
        {"ib_order_id": v.ib_order_id, "verdict": v.verdict}
        for v in verdicts_to_cancel if v.verdict not in SAFE_TO_AUTO_CANCEL
    ]
    if not safe:
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()
        return summary

    # Use ib_direct's cancel_order primitive — it's the only path that
    # acks back synchronously. Pusher-relayed cancels would be racy.
    # v19.34.89: When ib_direct is unavailable (pusher-only DGX deploy),
    # fall through to the cancel queue. Per-leg outcomes return
    # "queued" rather than "cancelled" — caller can poll
    # `/api/ib/cancellations/status/{ib_order_id}` to confirm.
    use_queue = False
    try:
        from services.ib_direct_service import get_ib_direct_service
        ib_direct = get_ib_direct_service()
    except Exception:
        ib_direct = None
    if ib_direct is None:
        use_queue = True
    else:
        try:
            if not await ib_direct.ensure_connected():
                use_queue = True
        except Exception:
            use_queue = True

    if use_queue:
        try:
            from routers.ib import queue_cancellation
        except Exception as e:
            summary["errors"].append({
                "stage": "queue_import_failed",
                "err": f"{type(e).__name__}: {e}",
            })
            summary["completed_at"] = datetime.now(timezone.utc).isoformat()
            return summary
        for v in safe:
            try:
                entry = queue_cancellation(
                    ib_order_id=int(v.ib_order_id),
                    reason=f"orphan-gtc auto-sweep ({v.verdict})",
                    requested_by="orphan_gtc_reconciler",
                )
                summary["cancelled"].append({
                    "ib_order_id": v.ib_order_id,
                    "symbol": v.symbol,
                    "verdict": v.verdict,
                    "via": "cancel_queue",
                    "queue_status": entry.get("status"),
                })
            except Exception as e:
                summary["errors"].append({
                    "ib_order_id": v.ib_order_id,
                    "symbol": v.symbol,
                    "err": f"{type(e).__name__}: {e}",
                })
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()
        return summary

    for v in safe:
        try:
            rep = await ib_direct.cancel_order(v.ib_order_id)
            if rep.get("success"):
                summary["cancelled"].append({
                    "ib_order_id": v.ib_order_id,
                    "symbol": v.symbol,
                    "verdict": v.verdict,
                    "via": "ib_direct",
                })
            else:
                summary["errors"].append({
                    "ib_order_id": v.ib_order_id,
                    "symbol": v.symbol,
                    "err": rep.get("error", "unknown"),
                })
        except Exception as e:  # pragma: no cover
            summary["errors"].append({
                "ib_order_id": v.ib_order_id,
                "symbol": v.symbol,
                "err": f"{type(e).__name__}: {e}",
            })

    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    return summary
