"""
SentCom Router - Sentient Command API Endpoints
Unified AI command center for the trading team.

Endpoints:
- GET /api/sentcom/status - Current operational status
- GET /api/sentcom/stream - Unified message stream (thoughts + chat + alerts)
- POST /api/sentcom/chat - Send a message to SentCom
- GET /api/sentcom/context - Current market context
- GET /api/sentcom/positions - Our current positions
- GET /api/sentcom/setups - Setups we're watching
- GET /api/sentcom/alerts - Recent alerts
"""
import logging
import os
from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.sentcom_service import get_sentcom_service, SentComService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sentcom", tags=["SentCom"])


class ChatRequest(BaseModel):
    """Chat message request"""
    message: str
    session_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    """Chat response"""
    success: bool
    response: str
    agent_used: Optional[str] = None
    intent: Optional[str] = None
    latency_ms: Optional[float] = None
    requires_confirmation: bool = False
    pending_trade: Optional[dict] = None
    source: str = "sentcom"


def _get_service() -> SentComService:
    """Get SentCom service instance"""
    return get_sentcom_service()


@router.get("/status")
async def get_status():
    """
    Get SentCom operational status.
    
    Returns:
    - connected: Whether we're connected to the broker
    - state: Current operational state (active, watching, paused, offline)
    - regime: Current market regime
    - positions_count: Number of open positions
    - watching_count: Number of setups being watched
    - order_pipeline: Order counts (pending, executing, filled)
    """
    try:
        service = _get_service()
        status = await service.get_status()
        return {
            "success": True,
            "status": status.to_dict()
        }
    except Exception as e:
        logger.error(f"Error getting SentCom status: {e}")
        return {
            "success": False,
            "error": str(e),
            "status": {
                "connected": False,
                "state": "error",
                "regime": None,
                "positions_count": 0,
                "watching_count": 0,
                "order_pipeline": {"pending": 0, "executing": 0, "filled": 0, "ib_pending": 0}
            }
        }


@router.get("/stream")
async def get_stream(limit: int = Query(20, ge=1, le=100)):
    """
    Get unified SentCom message stream.
    
    Combines:
    - Bot execution thoughts
    - Chat history
    - Filter decisions (smart strategy filtering)
    - System status messages
    
    All messages use "we" voice.
    
    Returns list of messages sorted by timestamp (newest first).
    """
    try:
        service = _get_service()
        messages = await service.get_unified_stream(limit=limit)
        return {
            "success": True,
            "messages": [m.to_dict() for m in messages],
            "count": len(messages)
        }
    except Exception as e:
        logger.error(f"Error getting SentCom stream: {e}")
        return {
            "success": False,
            "error": str(e),
            "messages": [],
            "count": 0
        }


# 2026-04-30 v19.8 — Wave 2 (#9) — Stream · Deep Feed history endpoint.
# Backed by the existing `sentcom_thoughts` Mongo collection (TTL 7 days,
# already indexed on created_at + symbol + kind). The right-pane Deep
# Feed previously rendered the SAME 30-row in-memory buffer as the
# center Unified Stream — adding zero forensic value. This endpoint
# turns it into the post-mortem tool: time-range chips + text search
# + kind filter, all server-side so 500-row scans stay fast.
@router.get("/stream/history")
async def get_stream_history(
    minutes: int = Query(60, ge=1, le=10080),  # default 1h, max 7d (TTL ceiling)
    limit: int = Query(500, ge=1, le=2000),
    symbol: Optional[str] = Query(None, description="Filter to a single symbol (case-insensitive)"),
    kind: Optional[str] = Query(None, description="Filter by kind (scan / brain / order / fill / win / loss / skip / info / thought)"),
    q: Optional[str] = Query(None, description="Text search across content + action_type"),
):
    """Deep-history stream events from `sentcom_thoughts` (TTL 7d).

    Operator workflow:
      • Quick chips: minutes=5/30/60/240/1440  (5m / 30m / 1h / 4h / 1d)
      • Forensics:   q="WULF skip"             (text search across content)
      • Symbol drill-in: symbol=AAPL           (case-insensitive)
      • Severity drill-in: kind=loss           (matches stored `kind`)

    Response shape mirrors `/api/sentcom/stream` so the frontend can
    swap the messages array transparently.
    """
    from datetime import datetime, timezone, timedelta
    import re

    try:
        from services.sentcom_service import THOUGHTS_COLLECTION
        from services.sentcom_service import _get_db as _sentcom_get_db
    except Exception as e:
        logger.error(f"sentcom history import failed: {e}")
        return {"success": False, "error": str(e), "messages": [], "count": 0}

    try:
        db = _sentcom_get_db()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        query = {"created_at": {"$gte": cutoff}}
        if symbol:
            query["symbol"] = {"$regex": f"^{re.escape(symbol)}$", "$options": "i"}
        if kind:
            query["kind"] = kind.lower()
        if q:
            # Search across content + action_type. `re.escape` keeps
            # operator-typed slashes / parens harmless.
            # v19.30: action_type is indexable for exact match — try
            # equality first; only fall back to regex on content. This
            # collapses 1000ms+ regex full-scans into 50ms index hits
            # for the common harness queries (direction_unstable,
            # wrong_direction_phantom, etc).
            q_lower = q.strip().lower()
            query["$or"] = [
                {"action_type": q_lower},
                {"content": {"$regex": re.escape(q), "$options": "i"}},
                {"action_type": {"$regex": re.escape(q), "$options": "i"}},
            ]

        # v19.30: Materialize the cursor in a worker thread so a slow
        # Mongo query (regex scan, large limit, cold cache) cannot
        # block the FastAPI event loop. Pre-v19.30, this `list(cursor)`
        # call wedged the loop for 44-61s under load — see
        # `EVENT LOOP BLOCKED` warnings in `/tmp/backend.log`.
        import asyncio as _asyncio_lh
        def _run_query():
            cursor = (
                db[THOUGHTS_COLLECTION]
                .find(query, {"_id": 0})
                .sort("created_at", -1)
                .limit(limit)
            )
            return list(cursor)
        rows = await _asyncio_lh.to_thread(_run_query)

        # Massage into the same shape `/api/sentcom/stream` returns so
        # the frontend can render via the same `<UnifiedStreamV5/>`.
        messages = []
        for r in rows:
            ts = r.get("timestamp") or r.get("created_at")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            messages.append({
                "id": r.get("id"),
                "type": r.get("kind", "info"),
                "kind": r.get("kind", "info"),
                "action_type": r.get("action_type"),
                "content": r.get("content"),
                "text": r.get("content"),
                "symbol": r.get("symbol"),
                "confidence": r.get("confidence"),
                "metadata": r.get("metadata") or {},
                "timestamp": ts,
            })

        return {
            "success": True,
            "messages": messages,
            "count": len(messages),
            "filters": {
                "minutes": minutes,
                "symbol": symbol,
                "kind": kind,
                "q": q,
            },
        }
    except Exception as e:
        logger.exception(f"Error fetching sentcom stream history: {e}")
        return {"success": False, "error": str(e), "messages": [], "count": 0}



@router.post("/chat-test")
async def chat_test(request: ChatRequest):
    """Quick diagnostic: tests LLM directly, bypasses orchestrator"""
    import time
    import asyncio
    import requests as sync_requests
    start = time.time()
    print(f"[CHAT-TEST] Endpoint reached: {request.message}", flush=True)
    try:
        ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
        model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
        
        def _sync_call():
            r = sync_requests.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful trading assistant. Be brief."},
                        {"role": "user", "content": request.message}
                    ],
                    "stream": False,
                    "options": {"temperature": 0.7, "num_predict": 200}
                },
                timeout=30
            )
            return r.json()
        
        data = await asyncio.to_thread(_sync_call)
        content = data.get("message", {}).get("content", "")
        latency = (time.time() - start) * 1000
        print(f"[CHAT-TEST] Success in {latency:.0f}ms: {content[:80]}", flush=True)
        return {
            "success": True,
            "response": content,
            "model": model,
            "latency_ms": latency
        }
    except Exception as e:
        print(f"[CHAT-TEST] Error: {type(e).__name__}: {e}", flush=True)
        return {"success": False, "error": f"{type(e).__name__}: {e}", "latency_ms": (time.time() - start) * 1000}


@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Proxy to dedicated chat server (port 8002).
    Uses async httpx — doesn't block any threads.
    """
    import httpx
    
    chat_url = os.environ.get("CHAT_SERVER_URL", "http://127.0.0.1:8002")
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                f"{chat_url}/chat",
                json={"message": request.message, "session_id": request.session_id},
            )
            return r.json()
    except httpx.ConnectError:
        return {
            "success": False,
            "response": "Chat server is starting up. Please try again in a few seconds.",
            "source": "sentcom_proxy"
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "response": "Our AI took too long to respond. Please try again.",
            "source": "sentcom_timeout"
        }
    except Exception as e:
        return {
            "success": False,
            "response": f"Chat error: {e}",
            "source": "sentcom_error"
        }


@router.get("/chat/history")
def get_chat_history(limit: int = Query(50, ge=1, le=100)):
    """
    Get persisted chat history.
    
    Returns recent chat messages for display in the SentCom panel.
    Messages are loaded from MongoDB for persistence across sessions.
    """
    try:
        service = _get_service()
        # Return the in-memory chat history (already loaded from MongoDB)
        history = service._chat_history[-limit:] if service._chat_history else []
        return {
            "success": True,
            "messages": history,
            "count": len(history)
        }
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        return {
            "success": False,
            "error": str(e),
            "messages": [],
            "count": 0
        }


@router.get("/thoughts")
def get_thoughts(
    symbol: Optional[str] = Query(None, description="Filter to a single ticker"),
    kind: Optional[str] = Query(None, description="Filter to one event kind (evaluation / fill / skip / brain / etc.)"),
    minutes: int = Query(240, ge=1, le=20160, description="How far back to look. Default 4h, max 14d."),
    limit: int = Query(50, ge=1, le=500),
):
    """Recall persisted bot thoughts / decisions / fills from
    `sentcom_thoughts` (TTL 7d). Survives backend restarts — operator's V4
    "brain memory" carry-over.

    Use cases:
      - "What was the bot thinking about NVDA this morning?" — pass
        `?symbol=NVDA`
      - "Show me every safety block today" — pass `?kind=skip&minutes=480`
      - "Live feed of recent evaluations" — `?kind=evaluation&minutes=30`
    """
    from services.sentcom_service import get_recent_thoughts
    rows = get_recent_thoughts(
        symbol=symbol, kind=kind, minutes=minutes, limit=limit
    )
    return {
        "success": True,
        "count": len(rows),
        "filter": {"symbol": symbol, "kind": kind, "minutes": minutes},
        "thoughts": rows,
    }



@router.get("/context")
async def get_context():
    """
    Get current market context for SentCom display.
    
    Returns:
    - regime: Current market regime (RISK_ON, RISK_OFF, etc.)
    - spy_trend: SPY trend direction
    - vix: Current VIX level
    - sector_flow: Leading/lagging sectors
    - market_open: Whether market is currently open
    """
    try:
        service = _get_service()
        context = await service.get_market_context()
        return {
            "success": True,
            "context": context
        }
    except Exception as e:
        logger.error(f"Error getting market context: {e}")
        return {
            "success": False,
            "error": str(e),
            "context": {
                "regime": "UNKNOWN",
                "spy_trend": None,
                "vix": None,
                "market_open": False
            }
        }


@router.get("/positions")
async def get_positions():
    """
    Get our current positions with P&L.
    
    Returns list of positions with enriched data:
    - symbol, shares, entry_price, current_price
    - pnl, pnl_percent, market_value, cost_basis, portfolio_weight
    - risk_level (ok/warning/danger/critical)
    - today_change, today_change_pct
    - stop_price, target_prices
    - status, entry_time

    2026-05-04 v19.31.7 — operator reported HUD's CLOSE TODAY tile
    always reading 0 even after the bot demonstrably closed positions.
    Root cause: this endpoint returned only OPEN positions, but the
    HUD filtered `status === 'closed'` against THAT array, so it could
    never find anything. Now we also return:

      - `closed_today`: bot_trades closed since 00:00 ET today, with
        symbol/direction/realized_pnl/closed_at — feeds the HUD's
        CLOSE TODAY tile directly.
      - `total_realized_pnl`: sum of realized PnL across closed_today.
      - `total_unrealized_pnl`: sum of pnl across open positions
        (alias of `total_pnl` — kept for clarity in the new payload).
      - `total_pnl_today`: realized + unrealized (the operator's
        actual day-PnL number).
    """
    try:
        service = _get_service()
        positions = await service.get_our_positions()

        # ── Closed trades today (v19.31.7) ────────────────────────
        # 2026-02-13 (v19.34.141) — Anchor "today" at midnight America/New_York
        # via zoneinfo. Pre-fix:
        #   today_start_et = now_utc.replace(hour=0) - timedelta(hours=4)
        # was OFF BY 8-9 HOURS — `now_utc.replace(hour=0)` is today's UTC
        # midnight, then subtracting 4h lands at *yesterday* 20:00 UTC =
        # yesterday 3-4 PM ET. Result: every close that fired during
        # yesterday's RTH or after-hours session was summed into today's
        # realized PnL. On a portfolio of "DAY 2" overnight survivors,
        # that bleeds the entire prior session's close-out PnL into
        # today's number. Operator-reported: app showed −$4,378.49 vs IB's
        # −$442.54 (a $3,936 ghost loss) — exact match for "yesterday's
        # full afternoon of closes included".
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        try:
            from zoneinfo import ZoneInfo  # py 3.9+
            _ET = ZoneInfo("America/New_York")
        except Exception:
            _ET = None
        from server import db as _db
        now_utc = _dt.now(_tz.utc)
        if _ET is not None:
            now_et = now_utc.astimezone(_ET)
            today_midnight_et = now_et.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_start_et = today_midnight_et.astimezone(_tz.utc)
        else:
            # Defensive fallback (no zoneinfo): convert today's UTC midnight
            # forward by ET's offset (4h DST / 5h winter). Conservative —
            # assume DST so we don't accidentally include the prior session.
            today_start_et = (
                now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                + _td(hours=4)
            )
        cutoff_iso = today_start_et.isoformat()

        closed_today_raw = []
        try:
            # v19.34.28 L3-hotfix2 (2026-05-18) — Materialize the cursor in a
            # worker thread, mirroring the v19.30 fix already in place in
            # `get_thoughts` (line ~190 above). Pre-hotfix2, this sync pymongo
            # `list(cursor)` ran on the asyncio main loop and blocked on
            # `socket.recv_into` whenever Mongo took >5s to respond (busy load
            # or cold-cache scan over the `bot_trades` collection). That
            # triggered the wedge watchdog and stalled EVERYTHING — including
            # the trading bot's scan loop — for the duration of the block.
            # Forensic capture 2026-05-18: the watchdog dump pinned the main
            # thread inside `sentcom.py:485 list(cursor)` → `pymongo/network.py:
            # _receive_data_on_socket` → blocking `recv_into`. The frontend
            # polls `/api/sentcom/positions` on every dashboard tick so this
            # bug fired N times per minute under any Mongo latency.
            import asyncio as _asyncio_l3h2
            def _materialize_closed_today():
                _cur = _db["bot_trades"].find(
                    {
                        "status": "closed",
                        "$or": [
                            {"closed_at": {"$gte": cutoff_iso}},
                            # `executed_at` fallback for trades with no
                            # closed_at field (legacy, or where the close
                            # path skipped stamping it).
                            {"closed_at": None, "executed_at": {"$gte": cutoff_iso}},
                        ],
                    },
                    {"_id": 0},
                    sort=[("closed_at", -1)],
                    limit=200,
                )
                return list(_cur)
            closed_today_raw = await _asyncio_l3h2.to_thread(_materialize_closed_today)
        except Exception as e:
            logger.warning(f"closed_today lookup failed (non-fatal): {e}")

        # Slim shape for the HUD — same fields as positions but with
        # close-specific extras. Skip `_id` is already excluded above.
        closed_today = []
        total_realized_pnl = 0.0
        # v19.34.27 (2026-05-14) — Bifurcate realized PnL into two
        # buckets so the HUD's "R" chip matches IB exactly.
        #
        # Problem: pre-v19.34.27 `total_realized_pnl` summed every
        # bot_trade with `closed_at >= today_midnight_ET`. Trades the
        # *reconciler* closes (status flip from open → closed because
        # IB no longer holds the position — OCA fired externally,
        # operator flattened in TWS, zombie cleanup, stale pending,
        # consolidator merge) get `closed_at = NOW()` even though the
        # *actual fill* in IB happened yesterday afternoon. Operator
        # hit this 2026-05-14 morning: app `R −$2,056.86`, IB realized
        # `−$272.82` — exactly the prior session's overnight passenger
        # losses being booked as "today" because the reconciler
        # discovered them on the 9:22 ET pre-market tick.
        #
        # Fix: split the aggregator into:
        #   - total_realized_pnl_today    → REAL bot exits TODAY only
        #     (target_hit / stop_loss / stop_hit / manual flatten of a
        #     position the bot still owned, etc.). MATCHES IB.
        #   - total_realized_pnl_session  → legacy behaviour (every
        #     closed_at >= today_midnight). Preserved for the audit
        #     drilldown so the operator can still see the full picture.
        #
        # Discriminator: `close_reason`. The set below enumerates every
        # close_reason known to indicate a *passive / synthetic /
        # reconciler-stamped* closure where the actual realized event
        # was earlier than the closed_at timestamp.
        SYNTHETIC_CLOSE_REASONS = {
            "oca_closed_externally_v19_31",
            "external_close_v19_34_15b",
            "operator_external_flatten",
            "operator_sync_external_close_v19_34_47",
            "zombie_cleanup_v19_34_19",
            "consolidated_v19_34_42",
            "consolidated_in_flatten_v19_34_44",
            "stale_pending_v19_34_78",
            "stale_pending_cleared_v19_34_78",
        }
        # Some reconciler paths stamp the reason with a "phantom_close:" prefix
        # (see position_reconciler._close_phantom_trade L665). Match by prefix
        # so we catch every variation without enumerating each phantom-reason.
        SYNTHETIC_CLOSE_PREFIXES = ("phantom_close:",)
        total_realized_pnl_today = 0.0   # excludes synthetic — matches IB
        synthetic_realized_count = 0     # for the tooltip breakdown
        synthetic_realized_sum = 0.0     # historical bookings rolling in
        # 2026-02-13 (v19.34.141) — Dedup closed trades before summing.
        # The orphan reconciler, consolidator merge, and OCA-ext race
        # paths can each produce a SECOND `closed` row for the same
        # fill cluster — same symbol, same fill_time / fill_price /
        # exit_price / shares — and the prior implementation summed
        # both, inflating realized losses. Apply the exact same dedup
        # key the /api/diagnostic/realized-pnl-audit endpoint uses so
        # the displayed total and the audit total stay in lock-step.
        _seen_keys: set = set()
        _dropped_dupe_count = 0
        _dropped_dupe_pnl = 0.0
        # v19.34.1 (2026-05-04) — pusher account fallback so legacy
        # closed_today rows that pre-date v19.31.13 trade_type stamping
        # still chip PAPER/LIVE on the UI.
        _legacy_trade_type = None
        _legacy_account_id = None
        try:
            from services.account_guard import classify_account_id as _classify
            from services.ib_pusher_rpc import get_account_snapshot as _gas
            _snap = _gas()
            _legacy_account_id = (_snap or {}).get("account_id") or None
            if _legacy_account_id:
                _legacy_trade_type = _classify(_legacy_account_id)
        except Exception:
            pass
        for t in closed_today_raw:
            realized = float(t.get("realized_pnl") or t.get("net_pnl") or t.get("pnl") or 0)

            # Dedup key — match the audit endpoint logic.
            ft = t.get("fill_time") or t.get("entry_time")
            if ft:
                # ISO-coerce for stable comparisons across str / datetime rows.
                if hasattr(ft, "isoformat"):
                    ft = ft.isoformat()
                _key = ("ft", t.get("symbol"), str(ft))
            else:
                _key = ("sig", t.get("symbol"), t.get("fill_price"),
                        t.get("shares"), t.get("exit_price"))
            if _key in _seen_keys:
                _dropped_dupe_count += 1
                _dropped_dupe_pnl += realized
                continue
            _seen_keys.add(_key)

            total_realized_pnl += realized
            # v19.34.27 — bucket by close_reason. Synthetic / passive
            # reconciler-stamped closures don't contribute to "today
            # realized" because their actual IB fill predates today.
            _cr = (t.get("close_reason") or "").strip()
            _is_synthetic = (
                _cr in SYNTHETIC_CLOSE_REASONS
                or any(_cr.startswith(p) for p in SYNTHETIC_CLOSE_PREFIXES)
            )
            if _is_synthetic:
                synthetic_realized_count += 1
                synthetic_realized_sum += realized
            else:
                total_realized_pnl_today += realized
            row_trade_type = t.get("trade_type")
            if not row_trade_type or row_trade_type == "unknown":
                row_trade_type = _legacy_trade_type or "unknown"
            closed_today.append({
                "symbol": t.get("symbol"),
                "direction": t.get("direction"),
                "shares": t.get("shares"),
                "entry_price": t.get("fill_price") or t.get("entry_price"),
                "exit_price": t.get("exit_price") or t.get("close_price"),
                "realized_pnl": round(realized, 2),
                "r_multiple": t.get("r_multiple"),
                "executed_at": t.get("executed_at"),
                "closed_at": t.get("closed_at"),
                "close_reason": t.get("close_reason") or t.get("exit_reason"),
                "setup_type": t.get("setup_type"),
                "trade_id": t.get("id"),
                # v19.31.13 — surface trade_type for the CLOSE TODAY
                # drilldown table chip.
                # v19.34.1 — fall back to current pusher account when
                # the row's stamp is missing or "unknown".
                "trade_type": row_trade_type,
            })

        total_unrealized_pnl = sum(p.get("pnl", 0) for p in positions)
        total_market_value = sum(p.get("market_value", 0) for p in positions)
        total_cost_basis = sum(p.get("cost_basis", 0) for p in positions)
        total_today_change = sum(p.get("today_change", 0) for p in positions)
        bot_count = sum(1 for p in positions if p.get("source") == "bot")
        ib_count = sum(1 for p in positions if p.get("source") == "ib")
        positions_at_risk = sum(1 for p in positions if p.get("risk_level") in ("danger", "critical"))

        wins_today = sum(1 for c in closed_today if (c.get("realized_pnl") or 0) > 0)
        losses_today = sum(1 for c in closed_today if (c.get("realized_pnl") or 0) < 0)

        return {
            "success": True,
            "positions": positions,
            "count": len(positions),
            # Legacy field — keeps existing HUDs working unchanged.
            "total_pnl": round(total_unrealized_pnl, 2),
            # v19.31.7 explicit naming + new realized/total-today fields.
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            # v19.34.27 (2026-05-14) — `total_realized_pnl` now points to
            # the IB-matching "today only, real bot exits" figure. The
            # legacy "everything closed since midnight" total is exposed
            # separately as `total_realized_pnl_session` so the audit
            # drilldown + tooltip can still surface it. Operator-visible
            # `R` chip uses `total_realized_pnl` (= today, matches IB).
            "total_realized_pnl": round(total_realized_pnl_today, 2),
            "total_realized_pnl_session": round(total_realized_pnl, 2),
            # Diagnostics — used by the HUD tooltip + the audit drilldown.
            "realized_pnl_synthetic_count": synthetic_realized_count,
            "realized_pnl_synthetic_sum": round(synthetic_realized_sum, 2),
            "total_pnl_today": round(total_unrealized_pnl + total_realized_pnl_today, 2),
            "total_market_value": round(total_market_value, 2),
            "total_cost_basis": round(total_cost_basis, 2),
            "total_today_change": round(total_today_change, 2),
            "bot_positions": bot_count,
            "ib_positions": ib_count,
            "positions_at_risk": positions_at_risk,
            # v19.31.7 — closed trades for today (drives HUD CLOSE TODAY tile).
            "closed_today": closed_today,
            "closed_today_count": len(closed_today),
            "wins_today": wins_today,
            "losses_today": losses_today,
            # v19.34.141 — dedup diagnostics so the operator can see
            # whether realized was inflated by duplicate close rows.
            "dropped_duplicate_closes": _dropped_dupe_count,
            "dropped_duplicate_pnl": round(_dropped_dupe_pnl, 2),
        }
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        return {
            "success": False,
            "error": str(e),
            "positions": [],
            "count": 0,
            "total_pnl": 0,
            "total_unrealized_pnl": 0,
            "total_realized_pnl": 0,
            "total_realized_pnl_session": 0,
            "realized_pnl_synthetic_count": 0,
            "realized_pnl_synthetic_sum": 0,
            "total_pnl_today": 0,
            "closed_today": [],
            "closed_today_count": 0,
            "wins_today": 0,
            "losses_today": 0,
        }


@router.get("/setups")
async def get_setups():
    """
    Get setups we're currently watching.
    
    Returns list of setups with:
    - symbol, setup_type, trigger_price
    - current_price, risk_reward, confidence
    """
    try:
        service = _get_service()
        setups = await service.get_setups_watching()
        return {
            "success": True,
            "setups": setups,
            "count": len(setups)
        }
    except Exception as e:
        logger.error(f"Error getting setups: {e}")
        return {
            "success": False,
            "error": str(e),
            "setups": [],
            "count": 0
        }


@router.get("/alerts")
async def get_alerts(limit: int = Query(200, ge=1, le=500)):
    """
    Get recent alerts and notifications.

    Returns alerts about:
    - Positions approaching stops
    - Positions hitting targets
    - Strong runners
    - Market regime changes
    """
    try:
        service = _get_service()
        alerts = await service.get_recent_alerts(limit=limit)
        return {
            "success": True,
            "alerts": alerts,
            "count": len(alerts)
        }
    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        return {
            "success": False,
            "error": str(e),
            "alerts": [],
            "count": 0
        }


@router.get("/health")
async def health_check():
    """SentCom health check endpoint"""
    try:
        service = _get_service()
        status = await service.get_status()
        return {
            "healthy": True,
            "connected": status.connected,
            "state": status.state
        }
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e)
        }


@router.get("/learning/insights")
async def get_learning_insights(symbol: str = Query(None)):
    """
    Get learning insights for the trader or a specific symbol.
    
    Provides:
    - Trader profile (strengths, weaknesses)
    - Recent patterns and behaviors
    - Strategy performance data
    - Symbol-specific insights (if symbol provided)
    - AI recommendations based on learning
    """
    try:
        service = _get_service()
        insights = await service.get_learning_insights(symbol)
        return {
            "success": True,
            "insights": insights
        }
    except Exception as e:
        logger.error(f"Error getting learning insights: {e}")
        return {
            "success": False,
            "error": str(e),
            "insights": {"available": False}
        }



# ===================== Dynamic Risk Management =====================

class RiskAssessmentRequest(BaseModel):
    """Risk assessment request"""
    symbol: Optional[str] = None
    setup_type: Optional[str] = None


@router.get("/risk")
async def get_risk_status():
    """
    Get current dynamic risk status.
    
    Returns:
    - enabled: Whether dynamic risk is enabled
    - multiplier: Current position size multiplier (0.25x - 2.0x)
    - risk_level: Current risk level (minimal, reduced, normal, elevated, maximum)
    - position_size: Effective position size
    - override_active: Whether a manual override is active
    """
    try:
        service = _get_service()
        context = await service.get_market_context()
        risk_data = context.get("dynamic_risk")
        
        if risk_data:
            return {
                "success": True,
                **risk_data
            }
        else:
            return {
                "success": True,
                "enabled": False,
                "multiplier": 1.0,
                "risk_level": "normal",
                "message": "Dynamic risk engine not available"
            }
    except Exception as e:
        logger.error(f"Error getting risk status: {e}")
        return {
            "success": False,
            "error": str(e),
            "multiplier": 1.0
        }


@router.post("/risk/assess")
async def assess_risk(request: RiskAssessmentRequest):
    """
    Perform a risk assessment for a potential trade.
    
    Args:
        symbol: Optional stock symbol for stock-specific scoring
        setup_type: Optional setup type for learning layer scoring
    
    Returns:
        Complete risk assessment with multiplier, factor breakdown, and explanation
    """
    try:
        service = _get_service()
        assessment = await service.get_risk_assessment(
            symbol=request.symbol,
            setup_type=request.setup_type
        )
        return assessment
    except Exception as e:
        logger.error(f"Error performing risk assessment: {e}")
        return {
            "success": False,
            "error": str(e),
            "multiplier": 1.0,
            "explanation": "Assessment failed"
        }



@router.get("/drift")
async def get_model_drift(model_version: Optional[str] = None):
    """Model drift snapshot using PSI + KS on live prediction distributions.

    When `model_version` is omitted, returns drift for every model seen
    in the confidence_gate_log within the baseline window.
    """
    try:
        from services.model_drift_service import (
            check_drift_for_model, check_drift_all_models,
        )
        service = _get_service()
        db = getattr(getattr(service, "_trading_bot", None), "_db", None)
        if model_version:
            return {"success": True, "results": [check_drift_for_model(db, model_version)]}
        return {"success": True, "results": check_drift_all_models(db)}
    except Exception as e:
        logger.error(f"Error running drift check: {e}")
        return {"success": False, "error": str(e), "results": []}


@router.get("/audit")
async def get_trade_audit(
    symbol: Optional[str] = None,
    setup_type: Optional[str] = None,
    model_version: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Post-mortem audit log of every trade decision.

    Each record captures entry geometry, gate decision + reasons, model
    attribution (with calibrated thresholds at decision time), applied
    sizing multipliers, and regime. Backs the V5 audit view.
    """
    try:
        from services.trade_audit_service import query_audit
        service = _get_service()
        db = getattr(getattr(service, "_trading_bot", None), "_db", None)
        records = query_audit(
            db,
            symbol=symbol,
            setup_type=setup_type,
            model_version=model_version,
            since=since,
            limit=limit,
        )
        return {"success": True, "count": len(records), "records": records}
    except Exception as e:
        logger.error(f"Error fetching trade audit: {e}")
        return {"success": False, "error": str(e), "records": []}
