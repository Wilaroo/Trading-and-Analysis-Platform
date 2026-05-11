"""v19.34.69 — Shared kill-switch chokepoint logic.

This module exists because of the BMNR P-1 bypass discovered on
2026-05-11 14:14:34 UTC: the operator manually tripped the kill switch,
yet `BMNR` was opened anyway. Forensic audit traced the entry path
to `agents/trade_executor_agent.py::_execute_order`, which imports
`services.order_queue_service.get_order_queue_service` and calls
`order_queue.queue_order(...)` DIRECTLY — bypassing the
`routers/ib.py::_kill_switch_gate` wrapper that was the only chokepoint
prior to this patch.

Defense-in-depth fix: move the gate decision logic into a shared,
import-cheap module so BOTH the routers wrapper AND the underlying
`OrderQueueService.queue_order()` can enforce it. After v19.34.69 the
gate sits at the absolute lowest layer (the service) — no matter which
caller produces an order, it cannot reach the Windows pusher without
passing the gate.

Module surface:
  - `is_protective_intent(order)` — True if order is close/stop/target.
  - `evaluate_kill_switch_gate(order)` — returns a refusal dict if the
    order MUST be refused, else None. Pure: no DB side effects, no
    logging. Callers are responsible for persisting the refusal row
    and emitting observability events.

Fail mode policy:
  - If `safety_guardrails` cannot be imported / its state cannot be
    read → fail OPEN (return None). Rationale: matches pre-v19.34.69
    behaviour; refusing legitimate closes during a guardrails outage
    is more dangerous than letting an occasional entry through (the
    bot's other guards in `trade_executor_service` and the autonomy
    loop still apply). A future v19.34.70 may flip this to fail-closed
    for entries once we have a higher-confidence health probe.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


_PROTECTIVE_INTENTS = {"close", "protective", "stop", "target", "cancel", "exit"}
_STOP_FAMILY_ORDER_TYPES = {"STP", "STP_LMT", "TRAIL", "TRAIL_LMT"}
_PROTECTIVE_TRADE_ID_KEYWORDS = (
    "STOP", "TGT", "TARGET", "OCA", "REISSUE", "ADOPT",
    "CLOSE", "PARTIAL", "CANCEL", "FLATTEN", "EXIT",
)
_PROTECTIVE_TRADE_ID_PREFIXES = (
    "CLOSE-", "PARTIAL-", "STOP-", "ADOPT-STOP-", "ADOPT-TGT-",
    "TARGET-", "OCA-", "TGT-",
)


def is_protective_intent(order: Dict[str, Any]) -> bool:
    """Decide whether an order is a protective / close-side leg that
    must remain allowed even when the kill switch is active.

    Detection ladder (most-reliable to most-heuristic):
      1. Explicit `intent` field.
      2. Non-empty `oca_group` — every OCA bracket leg has one.
      3. `order_type` in the stop family (STP, STP_LMT, TRAIL, TRAIL_LMT).
      4. `trade_id` contains a protective keyword as a substring
         (catches REISSUE-STOP-, OCA-RESYNC-TGT-, etc. without
         requiring producers to know the magic prefix list).
      5. Legacy startswith() compatibility list.
    """
    intent = (order.get("intent") or "").lower()
    if intent in _PROTECTIVE_INTENTS:
        return True

    if order.get("oca_group"):
        return True

    order_type = (order.get("order_type") or "").upper().replace(" ", "_")
    if order_type in _STOP_FAMILY_ORDER_TYPES:
        return True

    trade_id = order.get("trade_id") or ""
    trade_id_upper = trade_id.upper()
    if any(kw in trade_id_upper for kw in _PROTECTIVE_TRADE_ID_KEYWORDS):
        return True

    if trade_id.startswith(_PROTECTIVE_TRADE_ID_PREFIXES):
        return True

    return False


def evaluate_kill_switch_gate(order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a refusal payload (sans order_id) if the order must be
    refused by the kill-switch gate, else None.

    The returned dict mirrors the shape the routers-level gate has been
    writing into `order_queue.completed` since v19.34.48, so callers can
    persist it verbatim — only the `order_id` field needs to be filled
    in by the caller.

    Refusal payload shape:
      {
        "status": "rejected",
        "result": {"status": "rejected", "error": "kill_switch_active_v19_34_48",
                   "error_code": 503, "fill_price": None, "filled_qty": 0},
        "queued_at": "<iso>",
        "completed_at": "<iso>",
        "symbol": ..., "action": ..., "quantity": ..., "trade_id": ...,
        "rejected_by": "_kill_switch_gate_v19_34_69",
        "reason": <kill_switch_reason or None>,
      }
    """
    try:
        from services.safety_guardrails import get_safety_guardrails
        guard = get_safety_guardrails()
        if not (guard and guard.state.kill_switch_active):
            return None
    except Exception:
        # Fail-open — see docstring "Fail mode policy".
        return None

    if is_protective_intent(order):
        return None

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "status": "rejected",
        "result": {
            "status": "rejected",
            "error": "kill_switch_active_v19_34_48",
            "error_code": 503,
            "fill_price": None,
            "filled_qty": 0,
        },
        "queued_at": now_iso,
        "completed_at": now_iso,
        "symbol": order.get("symbol"),
        "action": order.get("action"),
        "quantity": order.get("quantity"),
        "trade_id": order.get("trade_id") or "",
        "rejected_by": "_kill_switch_gate_v19_34_69",
        "reason": getattr(guard.state, "kill_switch_reason", None),
    }
