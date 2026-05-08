"""
bracket_reissue_service.py — v19.34.7 (2026-05-05)

Operator-driven safety for the OCA bracket lifecycle. Whenever the
position size or thesis price levels change AFTER the bracket was
originally placed, the bracket's stop/target legs become STALE — the
stop is sized for the original quantity, the target is at the original
fill plan. If we don't cancel and re-issue, two failure modes appear:

  1. POSITION DRIFT: bot scales out 33sh of a 100sh position via a
     SEPARATE LMT (not via the original OCA target). The original OCA's
     stop is still 100sh. If the stop fires, IB sells 100sh and the
     position goes to -33 (an unintended SHORT). Forensic evidence in
     the 2026-05-04 IB fill audit showed this exact pattern on STX.

  2. DUPLICATE OCA STACK: bot scales in by firing a fresh bracket on the
     same setup. Now there are TWO live brackets on the same symbol with
     TWO stops and TWO targets, each at slightly different prices. If
     price hits one stop, IB cancels that OCA group's target — but the
     OTHER bracket's stop+target are untouched. Forensic evidence:
     2026-05-05 XLU fired 6 brackets in 4 minutes on the same symbol.

This service provides the unified `cancel-old + recompute + submit-new`
pipeline:

  reissue_bracket_for_trade(
      trade_id,
      reason="scale_in" | "scale_out" | "tif_promotion" | "manual",
      new_total_shares=None,    # pulled from trade.remaining_shares if None
      new_avg_entry=None,       # pulled from trade.entry_price if None
      preserve_target_levels=True,
      cancel_ack_timeout_s=2.0,
  ) -> dict

Decision tree from operator (2026-05-05 PM):
  - STOP recompute: weighted-avg-entry × RiskParameters.reconciled_default_stop_pct
  - TARGET recompute: keep PRICE LEVELS, recompute QUANTITIES from new total
    × original scale_out_pcts (honors thesis levels, scales size with size)
  - Cancel-then-submit: wait up to 2s for IB ack on cancel; abort + emit
    CRITICAL stream warning if cancel fails (never want both old and new live)
  - OCA pair: STP + LMT submitted as flat orders sharing oca_group string
    (pusher already supports `oca_group` field on flat orders)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.bracket_tif import bracket_tif

logger = logging.getLogger(__name__)


# ─── v19.34.11 — Bracket lifecycle event log ─────────────────────────────
# Every cancel-old + recompute + submit-new pipeline run is written to the
# Mongo `bracket_lifecycle_events` collection (TTL 7d). Powers the V5
# "📜 History" expandable panel inside `OpenPositionsV5.jsx` so the
# operator sees the full lifecycle of each trade's bracket: original
# bracket → scale-out trim → re-issue → exit, with `reason` chips per
# event and rich computed-plan / cancel-result / submit-result detail.
#
# Schema-light: persistence failure NEVER blocks the re-issue itself.

async def _persist_lifecycle_event(
    *,
    bot,
    event: Dict[str, Any],
) -> None:
    """Best-effort write of one bracket-lifecycle event to Mongo.

    Caller passes the entire `reissue_bracket_for_trade` return dict.
    We strip pure-debug fields, stamp `created_at`, and upsert into
    `bracket_lifecycle_events`. Failures swallow silently with a debug
    log so a Mongo blip never wedges the broker call path.
    """
    try:
        db = getattr(bot, "_db", None)
        if db is None:
            return
        # Lazy idempotent index ensure (once per process).
        global _lifecycle_indexes_ready
        if not _lifecycle_indexes_ready:
            try:
                await asyncio.to_thread(
                    db["bracket_lifecycle_events"].create_index,
                    "created_at", expireAfterSeconds=7 * 24 * 60 * 60,
                )
                await asyncio.to_thread(
                    db["bracket_lifecycle_events"].create_index,
                    [("trade_id", 1), ("created_at", -1)],
                )
                await asyncio.to_thread(
                    db["bracket_lifecycle_events"].create_index,
                    [("symbol", 1), ("created_at", -1)],
                )
                _lifecycle_indexes_ready = True
            except Exception:
                pass  # writes still work without the index
        # Shallow copy to avoid mutating the live event dict the caller
        # may still be using.
        doc = dict(event)
        doc["created_at"] = datetime.now(timezone.utc)
        # Keep the document compact — `plan` already contains the rich
        # computed parameters; don't double-store the trade object.
        await asyncio.to_thread(db["bracket_lifecycle_events"].insert_one, doc)
    except Exception as e:
        logger.debug("[v19.34.11 LIFECYCLE-LOG] persist failed: %s", e)


_lifecycle_indexes_ready: bool = False


# ─── v19.34.65 — Bracket re-issue throttle (per-symbol, 5-minute window) ──
# Yesterday's IB trade log showed ADBE took 18 BUY tickets between 9:32 AM
# and 12:57 PM, with sizes drifting 54→59→47→22→17→14→5… That's the
# bracket-reissue path firing fresh entries every time `remaining_shares`
# changes, with no cap on how many times per minute. EFA had similar
# behaviour around the 11:42 explosion. The fix: cap re-issues to ONE
# per (symbol, 5-minute window) and HARD-GUARD `remaining_shares > 0`
# at the orchestrator entry (compute_reissue_params already raises on
# remaining <= 0, but the throttle short-circuits BEFORE we touch IB).
import threading as _threading

REISSUE_THROTTLE_WINDOW_SECONDS = 300.0   # 5 minutes
REISSUE_THROTTLE_MAX_PER_WINDOW = 1       # one re-issue per window per symbol


@dataclass
class _ReissueRecord:
    symbol: str
    trade_id: str
    reason: str
    submitted_at: datetime


class _ReissueThrottle:
    """Process-wide throttle for bracket re-issue calls.

    Tracks recent SUCCESSFUL submissions per symbol so the throttle
    survives a transient compute/cancel failure (no point throttling on
    something that never reached IB). Failed submissions fall through
    so the operator can retry immediately.
    """

    def __init__(self) -> None:
        self._records: Dict[str, List[_ReissueRecord]] = {}  # key: symbol upper
        self._lock = _threading.Lock()

    def _expire(self, sym_u: str, now: datetime) -> None:
        cutoff = now - timedelta(seconds=REISSUE_THROTTLE_WINDOW_SECONDS)
        rs = self._records.get(sym_u, [])
        rs = [r for r in rs if r.submitted_at >= cutoff]
        if rs:
            self._records[sym_u] = rs
        else:
            self._records.pop(sym_u, None)

    def should_throttle(self, symbol: str) -> Optional[_ReissueRecord]:
        if not symbol:
            return None
        sym_u = symbol.upper()
        now = datetime.now(timezone.utc)
        with self._lock:
            self._expire(sym_u, now)
            rs = self._records.get(sym_u, [])
            if len(rs) >= REISSUE_THROTTLE_MAX_PER_WINDOW:
                # Most-recent record wins as the "blocking" reason.
                return rs[-1]
            return None

    def record_success(self, symbol: str, trade_id: str, reason: str) -> None:
        if not symbol:
            return
        sym_u = symbol.upper()
        rec = _ReissueRecord(
            symbol=sym_u,
            trade_id=trade_id,
            reason=reason,
            submitted_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._records.setdefault(sym_u, []).append(rec)

    def clear(self, symbol: str) -> int:
        """Operator/test escape hatch."""
        if not symbol:
            return 0
        with self._lock:
            return 1 if self._records.pop(symbol.upper(), None) is not None else 0

    def stats(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self._lock:
            for sym_u in list(self._records.keys()):
                self._expire(sym_u, now)
            return {
                "tracked_symbols": list(self._records.keys()),
                "window_seconds": REISSUE_THROTTLE_WINDOW_SECONDS,
                "max_per_window": REISSUE_THROTTLE_MAX_PER_WINDOW,
            }


_reissue_throttle_singleton: Optional[_ReissueThrottle] = None


def get_reissue_throttle() -> _ReissueThrottle:
    global _reissue_throttle_singleton
    if _reissue_throttle_singleton is None:
        _reissue_throttle_singleton = _ReissueThrottle()
    return _reissue_throttle_singleton



# ─── Pure compute helpers ──────────────────────────────────────────────────


@dataclass
class ReissuePlan:
    """The computed parameters the new OCA pair will be submitted with."""
    trade_id: str
    symbol: str
    direction: str          # "long" | "short"
    new_total_shares: int   # full position size after the scale event
    remaining_shares: int   # shares still un-executed (= total - already_filled)
    new_stop_price: float
    target_price_levels: List[float]
    target_qtys: List[int]  # one per target_price_level
    new_tif: str            # "DAY" | "GTC" — from bracket_tif()
    new_outside_rth: bool
    oca_group: str          # shared string for both legs
    reason: str             # "scale_in" | "scale_out" | "tif_promotion" | ...
    rationale: List[str] = field(default_factory=list)


def compute_reissue_params(
    *,
    trade,
    risk_params,
    reason: str,
    new_total_shares: Optional[int] = None,
    new_avg_entry: Optional[float] = None,
    already_executed_shares: int = 0,
    preserve_target_levels: bool = True,
    operator_stop_price: Optional[float] = None,
    operator_target_prices: Optional[List[float]] = None,
) -> ReissuePlan:
    """Pure computation of the new bracket parameters.

    Operator-defined rules (2026-05-05 PM):
      1. Stop = weighted_avg_entry × default_stop_pct (recomputed every time).
      2. Target price levels: preserved from trade.target_prices unless
         caller passes preserve_target_levels=False (forces 2R recompute).
      3. Target quantities: scale_out_pcts × new_remaining_shares, integer
         floored, residual lumped into the LAST target so total == remaining.
      4. TIF: re-resolved from trade.trade_style + trade.timeframe via
         services/bracket_tif.py (no manual override here).

    v19.34.40 (2026-05-07) — operator overrides:
      - `operator_stop_price` (chat AI / manual UI) bypasses rule (1) and
         pins the stop to the supplied price.
      - `operator_target_prices` bypasses rule (2) entirely — caller knows
         best. Direction-sanity check applied to each level.

    v19.34.62 (2026-02-09) — corrected `operator_stop_price` validation:
      now checks against CURRENT_PRICE (not entry). Trail stops on
      profitable longs frequently want stop > entry but < current — that's
      the whole point of trailing. Old rule wrongly rejected those.

    Raises:
      ValueError if computed remaining_shares <= 0 (no protection needed).
      ValueError if operator overrides violate direction sanity.
    """
    direction = (
        trade.direction.value if hasattr(trade.direction, "value")
        else str(trade.direction)
    ).lower()
    sym = (trade.symbol or "").upper()

    # ── total + remaining shares ────────────────────────────────────────────
    if new_total_shares is None:
        # Caller didn't override: fall back to the trade's current state.
        new_total_shares = int(getattr(trade, "shares", 0) or 0)
    new_total_shares = int(new_total_shares)
    if new_total_shares <= 0:
        raise ValueError(f"new_total_shares must be > 0, got {new_total_shares}")

    remaining = new_total_shares - max(0, int(already_executed_shares))
    if remaining <= 0:
        raise ValueError(
            f"remaining shares = {remaining} (total={new_total_shares} - "
            f"executed={already_executed_shares}) — no bracket needed"
        )

    # ── weighted-avg entry → recomputed stop ────────────────────────────────
    avg_entry = float(
        new_avg_entry if new_avg_entry is not None
        else getattr(trade, "entry_price", None) or
             getattr(trade, "fill_price", None) or 0
    )
    if avg_entry <= 0:
        raise ValueError(f"avg_entry must be > 0, got {avg_entry}")

    stop_pct = float(getattr(risk_params, "reconciled_default_stop_pct", 2.0)) / 100.0
    if operator_stop_price is not None:
        # v19.34.40 — operator override (chat AI / manual UI).
        # v19.34.62 (2026-02-09) — corrected validation. Pre-fix this rejected
        # any long stop ≥ entry (and short stop ≤ entry). That's correct for
        # an INITIAL stop, but operators frequently trail stops UP on
        # profitable longs (and DOWN on profitable shorts) to lock in
        # gains — which is the entire point of a trailing stop. The real
        # constraint is "stop must not immediately trigger": stop must be
        # strictly below CURRENT_PRICE for longs (above for shorts). A
        # stop at $731 on MU long with entry $713.69 / current $740.50 is
        # a perfectly valid +$17/share lock-in. Operator was getting
        # rejected by chat AI for trying to do exactly this.
        operator_stop = float(operator_stop_price)
        if operator_stop <= 0:
            raise ValueError(f"operator_stop_price must be > 0, got {operator_stop}")
        current_price = float(
            getattr(trade, "current_price", None)
            or getattr(trade, "fill_price", None)
            or avg_entry
        )
        if direction == "long" and operator_stop >= current_price:
            raise ValueError(
                f"operator_stop_price ${operator_stop:.2f} is at/above long "
                f"current price ${current_price:.2f} — would trigger "
                f"immediately. (Entry: ${avg_entry:.2f}; trail stops above "
                f"entry are fine, but must stay below current.)"
            )
        if direction == "short" and operator_stop <= current_price:
            raise ValueError(
                f"operator_stop_price ${operator_stop:.2f} is at/below short "
                f"current price ${current_price:.2f} — would trigger "
                f"immediately. (Entry: ${avg_entry:.2f}; trail stops below "
                f"entry are fine, but must stay above current.)"
            )
        new_stop = round(operator_stop, 2)
    elif direction == "long":
        new_stop = round(avg_entry * (1.0 - stop_pct), 2)
    else:  # short
        new_stop = round(avg_entry * (1.0 + stop_pct), 2)

    # ── target levels: preserve if requested, else 2R fallback ──────────────
    rationale: List[str] = []
    original_targets = list(getattr(trade, "target_prices", None) or [])
    if operator_target_prices:
        # v19.34.40 — operator override.
        # v19.34.63 (2026-02-09) — corrected validation. Pre-fix this rejected
        # any long target ≤ entry / short target ≥ entry, which was wrong
        # for two cases:
        #   1. Drawdown trim: long entry $100, current $95. Operator wants
        #      to scale out a third at $98 (still a $2 loss but cuts the
        #      bleeding). $98 < entry, but $98 > current — legitimate.
        #   2. The check missed the genuinely dangerous case: target
        #      between entry and current on a profitable position would
        #      fire immediately (e.g., long entry $100, current $110,
        #      target moved to $105 → instant fill).
        # Right rule (mirror of stop fix): target must be on the profit
        # side of CURRENT price. Long target > current; short target < current.
        current_price = float(
            getattr(trade, "current_price", None)
            or getattr(trade, "fill_price", None)
            or avg_entry
        )
        target_levels = [float(t) for t in operator_target_prices]
        for tlvl in target_levels:
            if tlvl <= 0:
                raise ValueError(f"operator_target_prices contains non-positive value: {tlvl}")
            if direction == "long" and tlvl <= current_price:
                raise ValueError(
                    f"operator target ${tlvl:.2f} is at/below long current "
                    f"price ${current_price:.2f} — would fire immediately. "
                    f"(Entry: ${avg_entry:.2f}; targets must be above current "
                    f"to remain pending.)"
                )
            if direction == "short" and tlvl >= current_price:
                raise ValueError(
                    f"operator target ${tlvl:.2f} is at/above short current "
                    f"price ${current_price:.2f} — would fire immediately. "
                    f"(Entry: ${avg_entry:.2f}; targets must be below current "
                    f"to remain pending.)"
                )
        rationale.append(
            f"target_levels: operator-supplied {len(target_levels)} levels "
            f"({target_levels})"
        )
    elif preserve_target_levels and original_targets:
        target_levels = [float(t) for t in original_targets]
        rationale.append(
            f"target_levels: preserved {len(target_levels)} original levels "
            f"({target_levels})"
        )
    else:
        # Synthetic: 2R from new stop, in the trade direction.
        risk = abs(avg_entry - new_stop)
        if risk <= 0:
            raise ValueError("computed stop distance is zero — refusing to build target")
        if direction == "long":
            target_levels = [round(avg_entry + 2 * risk, 2)]
        else:
            target_levels = [round(avg_entry - 2 * risk, 2)]
        rationale.append(
            f"target_levels: synthesized 2R level {target_levels[0]} "
            f"(no original targets to preserve)"
        )

    # ── target qtys: scale_out_pcts × remaining ─────────────────────────────
    sc_cfg = getattr(trade, "scale_out_config", None) or {}
    pcts = sc_cfg.get("scale_out_pcts") or []
    if not pcts or len(pcts) < len(target_levels):
        # Default even split if config is missing/short.
        pcts = [1.0 / max(1, len(target_levels))] * len(target_levels)
    pcts = [float(p) for p in pcts[: len(target_levels)]]

    qtys = [max(0, int(remaining * p)) for p in pcts]
    # Force every target to have at least 1 share if remaining permits, by
    # taking from the largest bucket. (Helps the case `remaining=1` + multiple
    # targets — we pick one target only via the residual reassignment below.)
    residual = remaining - sum(qtys)
    if residual > 0:
        # Lump leftovers into the last target so total exactly == remaining.
        qtys[-1] += residual
    elif residual < 0:
        # Over-allocated (shouldn't happen with floor, but defensive)
        qtys[-1] = max(0, qtys[-1] + residual)

    # Drop any 0-qty targets — IB rejects 0-qty orders.
    paired = [(p, q) for p, q in zip(target_levels, qtys) if q > 0]
    if not paired:
        # Edge case: remaining=0 after rounding. Fall back to single full-qty
        # target at the first level.
        paired = [(target_levels[0], remaining)]
    target_levels, qtys = [p for p, _ in paired], [q for _, q in paired]
    rationale.append(
        f"target_qtys: split {remaining} shares as {qtys} across {len(qtys)} "
        f"targets via pcts={pcts[: len(qtys)]}"
    )

    # ── TIF re-resolved from trade classification ───────────────────────────
    tif, outside_rth = bracket_tif(
        getattr(trade, "trade_style", None),
        getattr(trade, "timeframe", None),
    )
    rationale.append(
        f"tif: {tif} (outside_rth={outside_rth}) from trade_style="
        f"{getattr(trade, 'trade_style', None)!r} timeframe="
        f"{getattr(trade, 'timeframe', None)!r}"
    )

    # ── shared OCA group string ─────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    oca_group = f"REISSUE-{trade.id}-{ts}-{uuid.uuid4().hex[:6]}"

    rationale.append(
        f"new_stop: ${new_stop:.2f} (avg_entry=${avg_entry:.2f} × "
        f"{stop_pct * 100:.1f}% = "
        f"${abs(avg_entry - new_stop):.2f} risk)"
    )

    return ReissuePlan(
        trade_id=trade.id,
        symbol=sym,
        direction=direction,
        new_total_shares=new_total_shares,
        remaining_shares=remaining,
        new_stop_price=new_stop,
        target_price_levels=target_levels,
        target_qtys=qtys,
        new_tif=tif,
        new_outside_rth=outside_rth,
        oca_group=oca_group,
        reason=reason,
        rationale=rationale,
    )


# ─── Cancel + ack waiter ──────────────────────────────────────────────────


async def cancel_active_bracket_legs(
    *,
    trade_id: str,
    queue_service,
    cancel_ack_timeout_s: float = 2.0,
) -> Dict[str, Any]:
    """Cancel every active stop/target leg in `order_queue` for the given
    trade_id. Waits up to `cancel_ack_timeout_s` for status to flip to
    `cancelled` (the pusher updates this when IB acks).

    Returns:
      {
        "success": bool,            # True iff every targeted row reached `cancelled`
        "cancelled_orders": [str],  # order_ids successfully cancelled
        "stuck_orders":     [str],  # order_ids that did NOT reach `cancelled` in time
        "errors":           [str],
      }
    """
    cancelled_orders: List[str] = []
    stuck_orders: List[str] = []
    errors: List[str] = []

    try:
        active = list(queue_service._collection.find(
            {
                "trade_id": trade_id,
                "status": {"$in": ["pending", "claimed", "executing"]},
                # Only cancel the protective legs, not the (already-filled) parent.
                # We also include flat STP / LMT that came from a prior re-issue.
                "$or": [
                    {"order_type": "STP"},
                    {"order_type": "LMT"},
                    {"order_type": "bracket"},
                ],
            },
            {"_id": 0, "order_id": 1, "status": 1, "order_type": 1},
        ))
    except Exception as e:
        return {"success": False, "cancelled_orders": [], "stuck_orders": [],
                "errors": [f"queue_query_failed: {e}"]}

    if not active:
        # Nothing to cancel — vacuously success.
        return {"success": True, "cancelled_orders": [], "stuck_orders": [],
                "errors": []}

    target_ids = [a["order_id"] for a in active if a.get("order_id")]

    # Issue cancels in parallel.
    for oid in target_ids:
        try:
            queue_service.cancel_order(oid)
        except Exception as e:
            errors.append(f"cancel({oid}): {e}")

    # Poll for ack (each row goes status=cancelled).
    deadline = asyncio.get_event_loop().time() + cancel_ack_timeout_s
    pending = set(target_ids)
    while pending and asyncio.get_event_loop().time() < deadline:
        try:
            still = list(queue_service._collection.find(
                {"order_id": {"$in": list(pending)}},
                {"_id": 0, "order_id": 1, "status": 1},
            ))
        except Exception as e:
            errors.append(f"ack_poll_failed: {e}")
            break
        cleared = []
        for s in still:
            if (s.get("status") or "").lower() == "cancelled":
                cleared.append(s["order_id"])
        for oid in cleared:
            pending.discard(oid)
            cancelled_orders.append(oid)
        if pending:
            await asyncio.sleep(0.1)

    stuck_orders = list(pending)
    return {
        "success": not stuck_orders,
        "cancelled_orders": cancelled_orders,
        "stuck_orders": stuck_orders,
        "errors": errors,
    }


# ─── Submit OCA pair ──────────────────────────────────────────────────────


def submit_oca_pair(
    *,
    plan: ReissuePlan,
    queue_order_fn,
) -> Dict[str, Any]:
    """Submit a stop + target pair as flat STP + LMT orders, sharing the
    plan's `oca_group` string. Pusher already supports `oca_group` on
    flat orders (`order_queue_service.QueuedOrder.oca_group`).

    For multi-target plans (e.g. 50%/30%/20%), submits ONE stop sized for
    the full remaining qty + N target LMTs. All N+1 share the same OCA
    group, so when the stop fires IB cancels the targets, and vice versa.

    Returns:
      {
        "success": True,
        "stop_order_id": "...",
        "target_order_ids": ["...", ...],
        "oca_group": "...",
      }
    """
    direction = plan.direction
    child_action = "SELL" if direction == "long" else "BUY"

    submitted_targets: List[str] = []
    errors: List[str] = []

    # 1) Stop covers all remaining shares.
    try:
        stop_id = queue_order_fn({
            "symbol": plan.symbol,
            "action": child_action,
            "quantity": int(plan.remaining_shares),
            "order_type": "STP",
            "limit_price": None,
            "stop_price": float(plan.new_stop_price),
            "time_in_force": plan.new_tif,
            "outside_rth": plan.new_outside_rth,
            "oca_group": plan.oca_group,
            "trade_id": f"REISSUE-STOP-{plan.trade_id}",
            # v19.34.53 — explicit intent. Without this the v19.34.48
            # kill-switch chokepoint refused REISSUE-* trade_ids
            # (didn't match the startswith allow-list). Belt+suspenders
            # with the consumer-side oca_group / order_type detection.
            "intent": "protective",
        })
    except Exception as e:
        return {"success": False, "error": f"stop_submit_failed: {e}",
                "stop_order_id": None, "target_order_ids": [],
                "oca_group": plan.oca_group}

    # 2) Target LMTs.
    for level, qty in zip(plan.target_price_levels, plan.target_qtys):
        try:
            tid = queue_order_fn({
                "symbol": plan.symbol,
                "action": child_action,
                "quantity": int(qty),
                "order_type": "LMT",
                "limit_price": float(level),
                "stop_price": None,
                "time_in_force": plan.new_tif,
                "outside_rth": plan.new_outside_rth,
                "oca_group": plan.oca_group,
                "trade_id": f"REISSUE-TGT-{plan.trade_id}",
                # v19.34.53 — protective bracket leg, see stop above.
                "intent": "protective",
            })
            submitted_targets.append(tid)
        except Exception as e:
            errors.append(f"target_submit({level}, {qty}): {e}")

    return {
        "success": not errors,
        "stop_order_id": stop_id,
        "target_order_ids": submitted_targets,
        "oca_group": plan.oca_group,
        "errors": errors,
    }


# ─── Orchestrator ─────────────────────────────────────────────────────────


async def reissue_bracket_for_trade(
    *,
    trade,
    bot,
    reason: str,
    new_total_shares: Optional[int] = None,
    new_avg_entry: Optional[float] = None,
    already_executed_shares: int = 0,
    preserve_target_levels: bool = True,
    operator_stop_price: Optional[float] = None,
    operator_target_prices: Optional[List[float]] = None,
    cancel_ack_timeout_s: float = 2.0,
    queue_service=None,
    queue_order_fn=None,
) -> Dict[str, Any]:
    """Cancel the old bracket legs, then submit a freshly-computed OCA
    pair sized + priced for the post-event position state.

    On any cancel failure: ABORT — do NOT submit the new bracket. Emit a
    CRITICAL stream warning so the operator can intervene. We never want
    both old and new brackets live simultaneously.

    Returns: rich dict suitable for streaming to UI / journaling.
    """
    from datetime import datetime, timezone
    if queue_service is None:
        from services.order_queue_service import get_order_queue_service
        queue_service = get_order_queue_service()
        if not queue_service._initialized:
            queue_service.initialize()
    if queue_order_fn is None:
        from routers.ib import queue_order
        queue_order_fn = queue_order

    started_at = datetime.now(timezone.utc).isoformat()

    # ── v19.34.65 throttle gate (operator-driven, 2026-02-09) ──────────
    # Cap bracket re-issues at 1 per (symbol, 5-minute window) and
    # hard-guard remaining_shares > 0. Yesterday's IB trade log showed
    # ADBE took 18 entry tickets in a single morning — that loop ran
    # through this orchestrator. The throttle short-circuits BEFORE
    # any cancel call hits IB, so a thrash storm can't kill the
    # protective legs and leave the position naked.
    _sym_for_throttle = (getattr(trade, "symbol", "") or "").upper()
    _trade_id_for_throttle = getattr(trade, "id", None) or "?"

    # Hard remaining-shares guard. compute_reissue_params raises later,
    # but we want to NEVER touch IB if there's nothing to protect.
    _rs_check = int(
        getattr(trade, "remaining_shares", None)
        or getattr(trade, "shares", 0)
        or 0
    )
    if new_total_shares is not None:
        _rs_check = int(new_total_shares) - max(0, int(already_executed_shares))
    if _rs_check <= 0:
        msg = (
            f"v19.34.65 bracket re-issue REFUSED for {_sym_for_throttle} "
            f"({reason}): remaining_shares={_rs_check} ≤ 0 — nothing to "
            f"protect. trade_id={_trade_id_for_throttle}"
        )
        logger.warning(msg)
        ev = {
            "success": False,
            "phase": "throttle",
            "error": "remaining_shares_le_zero_v19_34_65",
            "trade_id": _trade_id_for_throttle,
            "symbol": _sym_for_throttle,
            "reason": reason,
            "remaining_shares": _rs_check,
            "started_at": started_at,
        }
        await _persist_lifecycle_event(bot=bot, event=ev)
        return ev

    _throttle = get_reissue_throttle()
    _blocked = _throttle.should_throttle(_sym_for_throttle)
    if _blocked is not None:
        age_s = (
            datetime.now(timezone.utc) - _blocked.submitted_at
        ).total_seconds()
        msg = (
            f"v19.34.65 bracket re-issue THROTTLED for {_sym_for_throttle} "
            f"({reason}): prior re-issue {_blocked.reason!r} succeeded "
            f"{age_s:.1f}s ago (window 300s, max 1). trade_id="
            f"{_trade_id_for_throttle}"
        )
        logger.warning(msg)
        ev = {
            "success": False,
            "phase": "throttle",
            "error": "reissue_throttled_v19_34_65",
            "trade_id": _trade_id_for_throttle,
            "symbol": _sym_for_throttle,
            "reason": reason,
            "blocked_by_reason": _blocked.reason,
            "blocked_by_trade_id": _blocked.trade_id,
            "blocked_age_seconds": round(age_s, 2),
            "started_at": started_at,
        }
        await _persist_lifecycle_event(bot=bot, event=ev)
        return ev

    # 1) Compute the new plan FIRST so a math error aborts before we cancel.
    try:
        plan = compute_reissue_params(
            trade=trade,
            risk_params=bot.risk_params,
            reason=reason,
            new_total_shares=new_total_shares,
            new_avg_entry=new_avg_entry,
            already_executed_shares=already_executed_shares,
            preserve_target_levels=preserve_target_levels,
            operator_stop_price=operator_stop_price,
            operator_target_prices=operator_target_prices,
        )
    except Exception as e:
        logger.error(
            "[v19.34.7 BRACKET-REISSUE] compute_reissue_params failed for "
            "trade=%s reason=%s: %s",
            getattr(trade, "id", "?"), reason, e,
        )
        ev = {
            "success": False,
            "phase": "compute",
            "error": f"{type(e).__name__}: {e}",
            "trade_id": getattr(trade, "id", None),
            "symbol": getattr(trade, "symbol", None),
            "reason": reason,
            "started_at": started_at,
        }
        await _persist_lifecycle_event(bot=bot, event=ev)
        return ev

    # 2) Cancel old bracket legs and wait for ack.
    cancel_result = await cancel_active_bracket_legs(
        trade_id=plan.trade_id,
        queue_service=queue_service,
        cancel_ack_timeout_s=cancel_ack_timeout_s,
    )
    if not cancel_result["success"]:
        # ABORT — don't submit a new bracket while old legs may still be live.
        msg = (
            f"v19.34.7 bracket re-issue ABORTED for {plan.symbol} ({reason}): "
            f"cancel of old legs FAILED. stuck={cancel_result['stuck_orders']} "
            f"errors={cancel_result['errors']}. Manual operator intervention "
            f"required — old protective legs may still be active at IB."
        )
        logger.critical(msg)
        # Best-effort stream warning.
        try:
            if hasattr(bot, "_emit_stream_event"):
                await bot._emit_stream_event({
                    "kind": "alert",
                    "severity": "critical",
                    "symbol": plan.symbol,
                    "trade_id": plan.trade_id,
                    "title": "Bracket re-issue aborted",
                    "body": msg,
                })
        except Exception as e:
            logger.debug("_emit_stream_event failed (non-fatal): %s", e)
        cancel_fail_event = {
            "success": False,
            "phase": "cancel",
            "error": "cancel_failed_abort",
            "trade_id": plan.trade_id,
            "symbol": plan.symbol,
            "reason": reason,
            "cancel_result": cancel_result,
            "plan": plan.__dict__,
            "started_at": started_at,
        }
        await _persist_lifecycle_event(bot=bot, event=cancel_fail_event)
        return cancel_fail_event

    # 3) Submit new OCA pair.
    submit_result = submit_oca_pair(plan=plan, queue_order_fn=queue_order_fn)
    if not submit_result["success"]:
        # Submit failure: log and return. The cancel already happened, so
        # the position is naked. The next manage-loop tick will re-place
        # protective stops — but the operator must be alerted NOW.
        msg = (
            f"v19.34.7 bracket re-issue submit failed for {plan.symbol} "
            f"({reason}): {submit_result.get('error')}. POSITION IS NAKED — "
            f"cancel succeeded but new bracket did NOT. Operator action required."
        )
        logger.critical(msg)
        try:
            if hasattr(bot, "_emit_stream_event"):
                await bot._emit_stream_event({
                    "kind": "alert",
                    "severity": "critical",
                    "symbol": plan.symbol,
                    "trade_id": plan.trade_id,
                    "title": "Bracket re-issue submit failed (NAKED)",
                    "body": msg,
                })
        except Exception:
            pass
        submit_fail_event = {
            "success": False,
            "phase": "submit",
            "error": submit_result.get("error", "submit_failed"),
            "trade_id": plan.trade_id,
            "symbol": plan.symbol,
            "reason": reason,
            "cancel_result": cancel_result,
            "submit_result": submit_result,
            "plan": plan.__dict__,
            "started_at": started_at,
        }
        await _persist_lifecycle_event(bot=bot, event=submit_fail_event)
        return submit_fail_event

    # 4) Persist the new IDs back onto the trade record so manage-loop tracks them.
    try:
        trade.stop_order_id = submit_result["stop_order_id"]
        # First target id — back-compat with the existing single target_order_id field.
        target_ids = submit_result["target_order_ids"]
        trade.target_order_id = target_ids[0] if target_ids else None
        trade.oca_group = submit_result["oca_group"]
        if hasattr(trade, "stop_price"):
            trade.stop_price = plan.new_stop_price
        if hasattr(trade, "target_prices"):
            trade.target_prices = list(plan.target_price_levels)
        if hasattr(bot, "_save_trade"):
            await bot._save_trade(trade)
    except Exception as e:
        # Persist failure is non-fatal — orders are already at IB, the
        # next save will pick them up.
        logger.warning(
            "[v19.34.7 BRACKET-REISSUE] post-submit save failed (orders "
            "are live at IB): %s", e,
        )

    finished_at = datetime.now(timezone.utc).isoformat()
    logger.warning(
        "[v19.34.7 BRACKET-REISSUE] %s %s OK — reason=%s, qty=%d, "
        "stop=$%.2f, targets=%s, oca=%s",
        plan.symbol, plan.direction, reason, plan.remaining_shares,
        plan.new_stop_price, list(zip(plan.target_price_levels, plan.target_qtys)),
        plan.oca_group,
    )

    # v19.34.65 — stamp the throttle ONLY on successful submit so a
    # transient compute/cancel/submit failure can be retried immediately.
    try:
        _throttle.record_success(
            symbol=plan.symbol,
            trade_id=plan.trade_id,
            reason=reason,
        )
    except Exception as _t_err:  # pragma: no cover
        logger.debug(
            "[v19.34.65] reissue throttle stamp failed (non-fatal): %s",
            _t_err,
        )

    success_event = {
        "success": True,
        "phase": "done",
        "trade_id": plan.trade_id,
        "symbol": plan.symbol,
        "reason": reason,
        "cancel_result": cancel_result,
        "submit_result": submit_result,
        "plan": plan.__dict__,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    await _persist_lifecycle_event(bot=bot, event=success_event)
    return success_event
