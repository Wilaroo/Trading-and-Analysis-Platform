"""
Trade-drop recorder
====================

A tiny audit-trail service for the **silent execution drops** the
operator hit in the April-29 forensic investigation: alerts pass the
hard gates, the AI confidence gate returns GO, but no row ever lands
in `bot_trades` because some `return None` / `return` between the AI
gate and `bot_trades.insert_one()` aborted the trade silently.

Every silent exit between `_evaluate_opportunity` and the
`bot_trades` write now calls :func:`record_trade_drop` so we get one
canonical place to ask "why did 32 GOs become 0 trades today?".

Storage
-------
Drops land in the ``trade_drops`` Mongo collection with this shape::

    {
        "_id": ObjectId,
        "ts":            "2026-04-30T18:42:01.123456+00:00",
        "ts_epoch_ms":   1730351321123,
        "gate":          "account_guard",
        "symbol":        "AAPL",
        "setup_type":    "9_ema_scalp",
        "direction":     "long",
        "reason":        "account drift: expected paperesw100000/dum61566s …",
        "context":       {"current_account_id": "DUM61566S", ...},
    }

The collection auto-trims at 7 days via a TTL index created
idempotently from
:func:`ensure_indexes` (called from server lifespan if available; the
recorder also creates it lazily on first write so installations that
miss the lifespan hook still get the index).

Fallback
--------
When ``db`` is ``None`` (test harness, transient Mongo outage, etc.)
we keep the last 500 drops in an in-process deque so the
``/api/diagnostic/trade-drops`` endpoint can still surface them.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

# In-memory fallback ring buffer (survives Mongo flaps / test harness).
_MEMORY_LIMIT = 500
_memory_buffer: Deque[Dict[str, Any]] = deque(maxlen=_MEMORY_LIMIT)
_memory_lock = threading.Lock()

# Track whether the TTL index has been ensured this process lifetime
# so we don't pay the round-trip on every drop.
_indexes_ready: bool = False
_indexes_lock = threading.Lock()


# ----- known gate names — keep in sync with instrumentation sites -----
KNOWN_GATES = {
    # trading_bot_service._execute_trade
    "account_guard",            # IB_ACCOUNT_ACTIVE vs pusher account drift
    "safety_guardrail",         # SafetyGuardrails.check_can_enter rejected
    "safety_guardrail_crash",   # exception in the guardrail check path
    # trade_execution.execute_trade
    "no_trade_executor",        # bot._trade_executor is None
    "pre_exec_guardrail_veto",  # services.execution_guardrails ran_all_guardrails veto
    "strategy_paper_phase",     # strategy promotion still in PAPER (saved to bot_trades w/ status=paper)
    "strategy_simulation_phase",  # strategy still in SIMULATION
    "broker_rejected",          # place_bracket_order/execute_entry returned non-success, non-timeout
    "execution_exception",      # raised exception in execute_trade
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_epoch_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def ensure_indexes(db) -> None:
    """Create the TTL + lookup indexes on `trade_drops` once per process.

    Idempotent. Safe to call from server lifespan AND lazily from the
    first write — whichever fires first wins the lock and flips
    ``_indexes_ready=True``.
    """
    global _indexes_ready
    if _indexes_ready or db is None:
        return
    with _indexes_lock:
        if _indexes_ready:
            return
        try:
            col = db["trade_drops"]
            # 7-day TTL on the epoch-ms field. Mongo TTL needs a real
            # ``Date`` type so we mirror with a `ts_dt` field for the
            # index but keep the ISO string for human-readable curl
            # output.
            col.create_index("ts_epoch_ms")
            col.create_index([("gate", 1), ("ts_epoch_ms", -1)])
            col.create_index("ts_dt", expireAfterSeconds=7 * 24 * 60 * 60)
            _indexes_ready = True
        except Exception as exc:
            # Non-fatal — recorder still writes; we just won't have indexes.
            logger.debug(f"[TradeDropRecorder] index ensure skipped: {exc}")


def record_trade_drop(
    db,
    *,
    gate: str,
    symbol: Optional[str] = None,
    setup_type: Optional[str] = None,
    direction: Optional[str] = None,
    reason: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a silent execution drop. Never raises.

    ``db`` may be ``None`` (recorder falls back to in-memory deque).
    ``gate`` should be one of :data:`KNOWN_GATES` — unknown values are
    accepted (forward-compat) but logged at WARN so we notice
    instrumentation drift.
    """
    if gate not in KNOWN_GATES:
        logger.warning(
            "[TradeDropRecorder] unknown gate '%s' — keeping but please "
            "update KNOWN_GATES in trade_drop_recorder.py", gate,
        )

    now_iso = _now_iso()
    now_epoch = _now_epoch_ms()
    record = {
        "ts": now_iso,
        "ts_epoch_ms": now_epoch,
        "ts_dt": datetime.now(timezone.utc),
        "gate": gate,
        "symbol": (symbol or "").upper() if symbol else None,
        "setup_type": setup_type,
        "direction": direction,
        "reason": (reason or "")[:500] if reason else None,
        "context": context or {},
    }

    # Always write to the in-memory buffer (cheap, lossless when Mongo
    # flaps). Don't include ts_dt in the in-memory copy — datetimes
    # don't serialize cleanly through FastAPI/JSON without a custom
    # encoder, and the ISO string already covers it.
    mem_record = {k: v for k, v in record.items() if k != "ts_dt"}
    with _memory_lock:
        _memory_buffer.append(mem_record)

    # Always emit a structured WARN log line so operators grepping
    # backend.log can find drops without curl/db access. Truncated
    # context to keep log lines readable.
    try:
        ctx_str = ""
        if context:
            ctx_kv = ", ".join(f"{k}={str(v)[:60]}" for k, v in context.items())
            ctx_str = f" | {ctx_kv[:300]}"
        logger.warning(
            "[TRADE_DROP] gate=%s symbol=%s setup=%s dir=%s reason=%s%s",
            gate,
            (symbol or "—"),
            setup_type or "—",
            direction or "—",
            (reason or "")[:200],
            ctx_str,
        )
    except Exception:
        # Never let the log line crash the trade flow.
        pass

    # Best-effort persist to Mongo.
    if db is not None:
        try:
            ensure_indexes(db)
            db["trade_drops"].insert_one(record)
        except Exception as exc:
            logger.debug(f"[TradeDropRecorder] mongo write failed: {exc}")


def get_recent_drops(
    db,
    *,
    minutes: int = 60,
    gate: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Return drops within the last ``minutes`` window.

    Reads from Mongo when ``db`` is available, otherwise from the
    in-memory ring buffer. Both branches return the same shape (sans
    ``_id`` / ``ts_dt``).
    """
    cutoff_ms = _now_epoch_ms() - max(1, int(minutes)) * 60 * 1000

    if db is not None:
        try:
            query: Dict[str, Any] = {"ts_epoch_ms": {"$gte": cutoff_ms}}
            if gate:
                query["gate"] = gate
            cursor = (
                db["trade_drops"]
                .find(query, {"_id": 0, "ts_dt": 0})
                .sort("ts_epoch_ms", -1)
                .limit(max(1, int(limit)))
            )
            return list(cursor)
        except Exception as exc:
            logger.debug(f"[TradeDropRecorder] mongo read failed: {exc}")

    # Fallback to in-memory buffer.
    with _memory_lock:
        snapshot = list(_memory_buffer)
    rows = [r for r in snapshot if r.get("ts_epoch_ms", 0) >= cutoff_ms]
    if gate:
        rows = [r for r in rows if r.get("gate") == gate]
    rows.sort(key=lambda r: r.get("ts_epoch_ms", 0), reverse=True)
    return rows[: max(1, int(limit))]


def summarize_recent_drops(
    db,
    *,
    minutes: int = 60,
) -> Dict[str, Any]:
    """Aggregate recent drops by gate for the operator-facing endpoint.

    Returns
    -------
    {
      "minutes": 60,
      "total": 47,
      "by_gate": {"account_guard": 32, "safety_guardrail": 15},
      "first_killing_gate": "account_guard",  # gate w/ highest count
      "recent": [<last 25 drops>],
    }
    """
    rows = get_recent_drops(db, minutes=minutes, limit=500)
    by_gate: Dict[str, int] = {}
    for r in rows:
        g = r.get("gate") or "unknown"
        by_gate[g] = by_gate.get(g, 0) + 1
    first_killing = max(by_gate.items(), key=lambda kv: kv[1])[0] if by_gate else None
    return {
        "minutes": minutes,
        "total": len(rows),
        "by_gate": by_gate,
        "first_killing_gate": first_killing,
        "recent": rows[:25],
    }


def reset_memory_buffer_for_tests() -> None:
    """Tests-only helper — clear the in-memory deque between cases."""
    with _memory_lock:
        _memory_buffer.clear()
