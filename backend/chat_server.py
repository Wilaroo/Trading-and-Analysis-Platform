"""
SentCom Chat Server — Dedicated LLM Process
Runs on port 8002, completely isolated from the main backend's event loop.

Usage:
    python chat_server.py

The main backend (port 8001) handles everything else.
This server ONLY handles chat — clean event loop, fast responses.
"""
import os
import sys
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import requests  # Still needed for Ollama calls
from pymongo import MongoClient

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chat_server")

# MongoDB connection (same DB as main backend)
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
mongo_client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = mongo_client[DB_NAME]

# Ensure indexes for fast queries on chat collections
try:
    db["sentcom_chat_history"].create_index([("session_id", 1), ("timestamp", -1)])
    db["sentcom_chat_history"].create_index([("timestamp", -1)])
    db["sentcom_memory"].create_index([("active", 1), ("created_at", -1)])
    db["sentcom_chat_sessions"].create_index([("session_id", 1)], unique=True)
    db["sentcom_chat_sessions"].create_index([("created_at", -1)])
    db["sentcom_context_archive"].create_index([("hash", 1), ("session_id", 1)])
    db["sentcom_context_archive"].create_index([("timestamp", -1)])
except Exception:
    pass  # Indexes may already exist

# Ollama config
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
OLLAMA_FALLBACK = os.environ.get("OLLAMA_FALLBACK_MODEL", "qwen3:30b")

# FastAPI app
app = FastAPI(title="SentCom Chat Server", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatHistory(BaseModel):
    limit: int = 50


def _get_portfolio_context() -> dict:
    """Build rich portfolio context from MongoDB only.
    No HTTP calls to main backend — avoids thread pool exhaustion hangs.
    Returns dict with 'text' (for LLM) and 'debug' (for diagnostics)."""
    parts = []
    debug = {}
    
    # 0. Current date/time and market status
    now_utc = datetime.now(timezone.utc)
    try:
        import zoneinfo
        et = now_utc.astimezone(zoneinfo.ZoneInfo("America/New_York"))
    except Exception:
        # Fallback: manual ET offset
        et = now_utc.replace(tzinfo=None)  # Approximate
    
    hour = et.hour if hasattr(et, 'hour') else now_utc.hour - 5
    is_weekday = et.weekday() < 5 if hasattr(et, 'weekday') else True
    market_open = is_weekday and 9 <= hour < 16
    pre_market = is_weekday and 4 <= hour < 9
    after_hours = is_weekday and 16 <= hour < 20
    
    if market_open:
        market_status = "MARKET OPEN (regular trading hours)"
        session_mode = "live"
    elif pre_market:
        if hour >= 7:
            market_status = "PRE-MARKET (7:00-9:30 ET) — Scanner is building morning watchlist: gaps, ORB candidates, opening drives"
            session_mode = "premarket_active"
        else:
            market_status = "EARLY PRE-MARKET — Market opens at 9:30 AM ET. Scanner analyzing daily charts."
            session_mode = "premarket_early"
    elif after_hours:
        market_status = "AFTER HOURS — Scanner analyzing daily charts for swing/position setups forming for tomorrow"
        session_mode = "after_hours"
    else:
        market_status = "MARKET CLOSED — Using last session data. Scanner analyzing daily charts for swing/position setups."
        session_mode = "closed"
    
    parts.append(f"Current Time: {et.strftime('%A, %B %d, %Y %I:%M %p ET') if hasattr(et, 'strftime') else str(now_utc)}\n{market_status}")
    debug["session_mode"] = session_mode
    
    # 1. Live positions from MongoDB snapshot (written by IB push endpoint)
    try:
        snapshot = db["ib_live_snapshot"].find_one({"_id": "current"})
        if snapshot:
            connected = snapshot.get("connected", False)
            positions = snapshot.get("positions", [])
            quotes = snapshot.get("quotes", {})
            account = snapshot.get("account", {})
            last_update = snapshot.get("last_update", "")
            
            # Check staleness (>90s = stale)
            if last_update:
                try:
                    last_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                    age = (datetime.now(timezone.utc) - last_dt).total_seconds()
                    debug["ib_data_age_seconds"] = round(age, 1)
                    if age > 90:
                        connected = False
                except Exception:
                    pass
            
            debug["ib_connected"] = connected
            debug["ib_positions_count"] = len(positions)
            debug["ib_quotes_count"] = len(quotes)
            debug["ib_account_keys"] = list(account.keys())[:10]
            
            if positions:
                pos_lines = []
                total_pnl = 0
                winners = []
                losers = []
                for p in positions:  # ALL positions, not just top 10
                    symbol = p.get("symbol", "?")
                    qty = p.get("quantity", p.get("position", 0)) or 0
                    direction = "LONG" if qty > 0 else "SHORT"
                    avg = p.get("avgCost", p.get("avg_cost", 0)) or 0
                    mkt = p.get("marketPrice", p.get("market_price", avg)) or avg
                    pnl = p.get("unrealizedPNL", p.get("unrealized_pnl", 0)) or 0
                    total_pnl += pnl
                    
                    quote = quotes.get(symbol, {})
                    if quote:
                        mkt = quote.get("last", quote.get("close", mkt)) or mkt
                    
                    pnl_pct = ((mkt - avg) / avg * 100) if avg > 0 else 0
                    if direction == "SHORT":
                        pnl_pct = -pnl_pct
                    
                    pos_lines.append(
                        f"  {symbol} ({direction}): {abs(qty):.0f} sh @ ${avg:.2f}, "
                        f"now ${mkt:.2f}, P&L ${pnl:+,.2f} ({pnl_pct:+.1f}%)"
                    )
                    if pnl > 0:
                        winners.append(f"{symbol} +${pnl:,.0f}")
                    elif pnl < -500:
                        losers.append(f"{symbol} ${pnl:,.0f}")
                
                summary = f"Current Positions ({len(positions)} total), Unrealized P&L: ${total_pnl:+,.2f}"
                if winners:
                    summary += f"\n  Winners: {', '.join(winners[:5])}"
                if losers:
                    summary += f"\n  Losers: {', '.join(losers[:5])}"
                parts.append(summary + "\n" + "\n".join(pos_lines))
            else:
                parts.append(f"IB Connected: {connected}. No open positions currently.")
            
            # Bot-tracked trades with stops/targets
            bot_trades = snapshot.get("bot_open_trades", [])
            if bot_trades:
                bot_lines = []
                for bt in bot_trades[:10]:
                    sym = bt.get("symbol", "?")
                    d = bt.get("direction", "?")
                    entry = bt.get("entry_price", 0)
                    stop = bt.get("stop_price", 0)
                    targets = bt.get("target_prices", [])
                    setup = bt.get("setup_type", "")
                    shares = bt.get("shares", 0)
                    target_str = ", ".join([f"${t:.2f}" for t in targets[:2]]) if targets else "none"
                    bot_lines.append(
                        f"  {sym} ({d}): {shares} shares, entry=${entry:.2f}, "
                        f"stop=${stop:.2f}, targets=[{target_str}] — {setup}"
                    )
                parts.append(
                    f"Bot-Tracked Trades ({len(bot_trades)} open):\n"
                    + "\n".join(bot_lines)
                )
            
            if account:
                netliq = account.get("NetLiquidation", account.get("net_liquidation", ""))
                buying = account.get("BuyingPower", account.get("buying_power", ""))
                if netliq:
                    try:
                        parts.append(f"Account: Net Liq ${float(netliq):,.2f}" + (f", Buying Power ${float(buying):,.2f}" if buying else ""))
                    except (ValueError, TypeError):
                        pass
        else:
            debug["ib_snapshot"] = "not_found"
            parts.append("IB data not available (pusher may not have sent data yet).")
    except Exception as e:
        debug["ib_error"] = str(e)
        logger.warning(f"Failed to read IB snapshot from MongoDB: {e}")

    # 1b. Key market index quotes (always include for context)
    try:
        snapshot = db["ib_live_snapshot"].find_one({"_id": "current"}, {"_id": 0, "quotes": 1})
        idx_quotes = (snapshot or {}).get("quotes", {})
        if idx_quotes:
            idx_lines = []
            # Check quote freshness
            sample_q = next(iter(idx_quotes.values()), {})
            q_timestamp = sample_q.get("timestamp", "")
            stale_note = ""
            if q_timestamp:
                try:
                    q_dt = datetime.fromisoformat(q_timestamp.replace('Z', '+00:00'))
                    q_age_min = (datetime.now(timezone.utc) - q_dt).total_seconds() / 60
                    if q_age_min > 30:
                        stale_note = f" (last updated {int(q_age_min)} minutes ago — may be stale)"
                except Exception:
                    pass
            
            for idx_sym in ['SPY', 'QQQ', 'IWM', 'DIA', 'VIX', 'NVDA', 'XOM']:
                q = idx_quotes.get(idx_sym, {})
                if q:
                    last = q.get("last") or q.get("close") or 0
                    prev_close = q.get("close") or last
                    chg = last - prev_close if last and prev_close else 0
                    chg_pct = (chg / prev_close * 100) if prev_close else 0
                    if last > 0:
                        idx_lines.append(f"  {idx_sym}: ${last:.2f} ({chg_pct:+.2f}% today)")
            if idx_lines:
                parts.append(f"LIVE Market Prices{stale_note} (use THESE numbers, not from memory):\n" + "\n".join(idx_lines))
    except Exception as e:
        logger.debug(f"Index quotes error: {e}")
    # 2. Recent AI Gate Decisions (from confidence_gate_log — TODAY only, not stale shadow_decisions)
    try:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        recent_gate = list(
            db["confidence_gate_log"]
            .find(
                {"timestamp": {"$gte": today_start.isoformat()}},
                {"_id": 0, "symbol": 1, "setup_type": 1, "decision": 1,
                 "confidence_score": 1, "reasoning": 1}
            )
            .sort("timestamp", -1)
            .limit(8)
        )
        debug["gate_decisions_today"] = len(recent_gate)
        if recent_gate:
            gate_lines = []
            for r in recent_gate:
                sym = r.get("symbol", "?")
                setup = r.get("setup_type", "?")
                decision = r.get("decision", "?")
                score = r.get("confidence_score", 0)
                gate_lines.append(f"  {sym} {setup}: {decision} ({score} pts)")
            parts.append("Today's Confidence Gate Decisions (most recent):\n" + "\n".join(gate_lines))
        else:
            parts.append("No confidence gate decisions yet today (pre-market or scanner not active).")
    except Exception as e:
        debug["gate_error"] = str(e)

    # 3. Market regime (from MongoDB)
    try:
        regime = db["market_regime_snapshots"].find_one(
            {}, {"_id": 0, "state": 1, "composite_score": 1},
            sort=[("timestamp", -1)]
        )
        debug["regime_found"] = regime is not None
        if regime:
            parts.append(
                f"Market Regime: {regime.get('state', 'UNKNOWN')} "
                f"(score: {regime.get('composite_score', 0):.1f})"
            )
    except Exception as e:
        debug["regime_error"] = str(e)

    # 4. Recent trade history (from MongoDB — both trades and bot_trades)
    try:
        recent_trades = list(
            db["trades"]
            .find({"symbol": {"$not": {"$regex": "^TEST"}}},
                  {"_id": 0, "symbol": 1, "direction": 1, "entry_price": 1,
                       "exit_price": 1, "pnl": 1, "status": 1, "setup_type": 1,
                       "entry_time": 1, "exit_time": 1})
            .sort("entry_time", -1)
            .limit(10)
        )
        # Also get recent bot_trades for richer history (exclude cancelled and test trades)
        bot_closed = list(
            db["bot_trades"]
            .find({"status": {"$in": ["closed", "stopped_out", "target_hit"]},
                   "symbol": {"$not": {"$regex": "^TEST"}}},
                  {"_id": 0, "symbol": 1, "direction": 1, "entry_price": 1,
                   "exit_price": 1, "pnl": 1, "status": 1, "setup_type": 1,
                   "close_reason": 1, "created_at": 1})
            .sort("created_at", -1)
            .limit(15)
        )
        all_trades = recent_trades + bot_closed
        debug["trades_count"] = len(all_trades)
        if all_trades:
            # Deduplicate by symbol+status
            seen = set()
            trade_lines = []
            wins = 0
            losses = 0
            total_pnl_closed = 0
            for t in all_trades:
                sym = t.get("symbol", "?")
                pnl = t.get("pnl") or 0
                key = f"{sym}_{t.get('status')}_{pnl}"
                if key in seen:
                    continue
                seen.add(key)
                direction = t.get("direction", "?") or "?"
                status = t.get("status", "?") or "?"
                setup = t.get("setup_type", "") or ""
                close_reason = t.get("close_reason", "") or ""
                total_pnl_closed += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                trade_lines.append(
                    f"  {sym} ({direction}): ${pnl:+,.2f} [{status}]"
                    + (f" — {setup}" if setup else "")
                    + (f" ({close_reason})" if close_reason else "")
                )
            total = wins + losses
            wr = (wins / total * 100) if total > 0 else 0
            parts.append(
                f"Closed Trades ({total} recent): {wins}W / {losses}L "
                f"({wr:.0f}% win rate), net ${total_pnl_closed:+,.2f}\n"
                + "\n".join(trade_lines[:10])
            )
    except Exception as e:
        debug["trades_error"] = str(e)

    # 5. Performance stats (from MongoDB)
    try:
        perf = db["performance_daily"].find_one(
            {}, {"_id": 0},
            sort=[("date", -1)]
        )
        debug["perf_found"] = perf is not None
        if perf:
            daily_pnl = perf.get("realized_pnl", perf.get("pnl", 0)) or 0
            total_trades = perf.get("total_trades", 0) or 0
            win_rate = perf.get("win_rate", 0) or 0
            parts.append(
                f"Today's Performance: P&L ${daily_pnl:+,.2f}, "
                f"{total_trades} trades, {win_rate:.0f}% win rate"
            )
    except Exception as e:
        debug["perf_error"] = str(e)

    # 6. Scanner alerts (from MongoDB — live_scanner_alerts collection)
    try:
        alerts = list(
            db["live_scanner_alerts"]
            .find({}, {"_id": 0, "symbol": 1, "setup_type": 1, "pattern": 1,
                       "score": 1, "confidence": 1})
            .sort("created_at", -1)
            .limit(8)
        )
        debug["scanner_alerts_count"] = len(alerts)
        if alerts:
            alert_lines = []
            for a in alerts:
                sym = a.get("symbol", "?")
                setup = a.get("setup_type", a.get("pattern", ""))
                score = a.get("score", a.get("confidence", ""))
                alert_lines.append(f"  {sym}: {setup}" + (f" (score: {score})" if score else ""))
            parts.append("Scanner Alerts:\n" + "\n".join(alert_lines))
    except Exception as e:
        debug["scanner_error"] = str(e)

    # 6b. Scanner mode + pre-market/after-hours setups (from main backend)
    try:
        scanner_resp = requests.get("http://127.0.0.1:8001/api/live-scanner/status", timeout=3)
        if scanner_resp.status_code == 200:
            scanner = scanner_resp.json()
            scan_mode = scanner.get("scan_mode", "unknown")
            time_window = scanner.get("time_window", "unknown")
            active_alerts = scanner.get("active_alerts", 0)
            regime = scanner.get("market_regime", "unknown")
            parts.append(
                f"Scanner Status: mode={scan_mode}, window={time_window}, "
                f"{active_alerts} active alerts, regime={regime}"
            )
        
        # Get live alerts for pre-market/after-hours context
        alerts_resp = requests.get("http://127.0.0.1:8001/api/live-scanner/alerts", timeout=3)
        if alerts_resp.status_code == 200:
            live_alerts = alerts_resp.json().get("alerts", [])
            if live_alerts:
                # Separate by type
                pm_alerts = [a for a in live_alerts if a.get("id", "").startswith("pm_")]
                daily_alerts = [a for a in live_alerts if a.get("scan_tier", "").lower() in ("swing", "position")]
                intraday_alerts = [a for a in live_alerts if a.get("scan_tier", "").lower() in ("intraday", "scalp")]
                
                if pm_alerts:
                    pm_lines = []
                    for a in pm_alerts[:8]:
                        sym = a.get("symbol", "?")
                        setup = a.get("setup_type", "")
                        direction = a.get("direction", "?")
                        price = a.get("trigger_price", 0)
                        reasoning = a.get("reasoning", "")
                        pm_lines.append(f"  {sym} ({direction}): {setup} @ ${price:.2f} — {reasoning[:80]}")
                    parts.append(
                        f"PRE-MARKET WATCHLIST ({len(pm_alerts)} setups for the open):\n"
                        + "\n".join(pm_lines)
                    )
                
                if daily_alerts:
                    daily_lines = []
                    for a in daily_alerts[:6]:
                        sym = a.get("symbol", "?")
                        setup = a.get("setup_type", "")
                        price = a.get("trigger_price", 0)
                        daily_lines.append(f"  {sym}: {setup} @ ${price:.2f}")
                    parts.append(
                        f"Daily Chart Setups (swing/position, {len(daily_alerts)} total):\n"
                        + "\n".join(daily_lines)
                    )
                
                if intraday_alerts and session_mode == "live":
                    intra_lines = []
                    for a in intraday_alerts[:6]:
                        sym = a.get("symbol", "?")
                        setup = a.get("setup_type", "")
                        price = a.get("trigger_price", 0)
                        intra_lines.append(f"  {sym}: {setup} @ ${price:.2f}")
                    parts.append(
                        f"Intraday Alerts ({len(intraday_alerts)} active):\n"
                        + "\n".join(intra_lines)
                    )
    except Exception as e:
        debug["scanner_status_error"] = str(e)
    try:
        import requests
        acct_resp = requests.get("http://127.0.0.1:8001/api/ib/account/summary", timeout=3)
        if acct_resp.status_code == 200:
            acct = acct_resp.json()
            if acct.get("success"):
                net_liq = acct.get("net_liquidation", 0)
                bp = acct.get("buying_power", 0)
                daily_pnl_val = acct.get("daily_pnl", 0)
                daily_pnl_pct = acct.get("daily_pnl_pct", 0)
                if net_liq:
                    parts.append(
                        f"Account Summary: Net Liquidation ${net_liq:,.2f}, "
                        f"Buying Power ${bp:,.2f}, "
                        f"Daily P&L ${daily_pnl_val:+,.2f} ({daily_pnl_pct:+.2f}%)"
                    )
    except Exception:
        pass

    # 8. Confidence gate stats (today's decisions)
    try:
        from datetime import timedelta
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        gate_stats = db["confidence_gate_log"].aggregate([
            {"$match": {"timestamp": {"$gte": today_start.isoformat()}}},
            {"$group": {
                "_id": None,
                "total": {"$sum": 1},
                "go": {"$sum": {"$cond": [{"$eq": ["$decision", "GO"]}, 1, 0]}},
                "reduce": {"$sum": {"$cond": [{"$eq": ["$decision", "REDUCE"]}, 1, 0]}},
                "skip": {"$sum": {"$cond": [{"$eq": ["$decision", "SKIP"]}, 1, 0]}},
                "avg_score": {"$avg": "$confidence_score"},
            }}
        ])
        gate_stats = list(gate_stats)
        if gate_stats:
            gs = gate_stats[0]
            total = gs["total"]
            go = gs["go"]
            take_rate = (go / total * 100) if total > 0 else 0
            parts.append(
                f"Confidence Gate Today: {total} evaluated, {go} GO, {gs['reduce']} REDUCE, {gs['skip']} SKIP "
                f"({take_rate:.0f}% take rate, avg score {gs['avg_score']:.0f})"
            )
    except Exception:
        pass

    # 9. Risk concentration analysis
    try:
        snapshot = db["ib_live_snapshot"].find_one({"_id": "current"}, {"_id": 0, "positions": 1})
        positions = (snapshot or {}).get("positions", [])
        if positions:
            total_value = 0
            position_values = []
            for p in positions:
                qty = abs(p.get("quantity", p.get("position", 0)) or 0)
                price = p.get("marketPrice", p.get("market_price", p.get("avgCost", 0))) or 0
                val = qty * price
                total_value += val
                position_values.append((p.get("symbol", "?"), val))
            
            if total_value > 0:
                position_values.sort(key=lambda x: x[1], reverse=True)
                conc_lines = []
                for sym, val in position_values[:5]:
                    pct = val / total_value * 100
                    conc_lines.append(f"  {sym}: ${val:,.0f} ({pct:.1f}%)")
                parts.append(
                    f"Position Concentration (top 5 of {len(positions)}, total ${total_value:,.0f}):\n"
                    + "\n".join(conc_lines)
                )
    except Exception:
        pass

    # 10. Bot risk parameters
    try:
        parts.append(
            "Risk Parameters: $2,500 max risk/trade, 1.5:1 min R:R, "
            "50% max position size, 10 max open positions, 1% max daily loss"
        )
    except Exception:
        pass

    # 10.5. Live symbol snapshots (Phase 3 live-data pipeline)
    # One-liner freshest-price + %change for held positions and key indices.
    # Sourced from /api/live/symbol-snapshot (Windows pusher RPC + TTL cache).
    # When pusher RPC is down the endpoint gracefully returns success=false —
    # we silently skip those rows so the assistant doesn't hallucinate data.
    try:
        import requests as _live_req
        _live_snapshot_targets: list = []
        _snapshot_doc = db["ib_live_snapshot"].find_one(
            {"_id": "current"}, {"_id": 0, "positions": 1}
        )
        _held = [
            p.get("symbol")
            for p in (_snapshot_doc or {}).get("positions", [])
            if p.get("symbol")
        ]
        for _s in _held:
            if _s and _s not in _live_snapshot_targets:
                _live_snapshot_targets.append(_s)
        for _idx in ("SPY", "QQQ", "IWM", "VIX"):
            if _idx not in _live_snapshot_targets:
                _live_snapshot_targets.append(_idx)
        _snap_lines = []
        for _sym in _live_snapshot_targets[:10]:
            try:
                _r = _live_req.get(
                    f"http://127.0.0.1:8001/api/live/symbol-snapshot/{_sym}",
                    timeout=2,
                )
                if _r.status_code == 200:
                    _d = _r.json()
                    if _d.get("success"):
                        _price = _d.get("latest_price")
                        _chg = _d.get("change_pct")
                        _bar_ts = _d.get("latest_bar_time") or "unknown"
                        _state = _d.get("market_state") or "?"
                        _src = _d.get("source") or "?"
                        if _price is not None and _chg is not None:
                            _sign = "+" if _chg >= 0 else ""
                            _snap_lines.append(
                                f"  {_sym} ${_price:.2f} {_sign}{_chg:.2f}% "
                                f"(bar {_bar_ts}, {_state}, {_src})"
                            )
            except Exception:
                pass
        if _snap_lines:
            parts.append(
                "Live Snapshots (Phase 3 live-data — IB pusher RPC, freshest "
                "available prices for held + indices):\n"
                + "\n".join(_snap_lines)
            )
    except Exception:
        pass

    # 11. Technical indicators for held positions (RSI, VWAP, EMAs, squeeze, etc.)
    try:
        import requests
        # Get symbols from positions
        snapshot = db["ib_live_snapshot"].find_one({"_id": "current"}, {"_id": 0, "positions": 1})
        held_symbols = [p.get("symbol") for p in (snapshot or {}).get("positions", []) if p.get("symbol")]
        # Add key indices
        for idx in ["SPY", "QQQ"]:
            if idx not in held_symbols:
                held_symbols.append(idx)
        
        tech_lines = []
        symbols_without_tech = []
        # Batch fetch technicals for held positions (limit to top 12)
        for sym in held_symbols[:12]:
            try:
                resp = requests.get(f"http://127.0.0.1:8001/api/technicals/{sym}", timeout=2)
                if resp.status_code == 200:
                    t = resp.json()
                    if t.get("success") and t.get("snapshot"):
                        s = t["snapshot"]
                        rsi = s.get("rsi_14", 0)
                        vwap = s.get("vwap", 0)
                        dist_vwap = s.get("dist_from_vwap", 0)
                        ema9 = s.get("ema_9", 0)
                        ema20 = s.get("ema_20", 0)
                        atr_pct = s.get("atr_percent", 0)
                        rvol = s.get("rvol", 0)
                        trend = s.get("trend", "?")
                        squeeze = s.get("squeeze_on", False)
                        above_vwap = s.get("above_vwap", False)
                        support = s.get("support", 0)
                        resistance = s.get("resistance", 0)
                        rs_spy = s.get("rs_vs_spy", 0)
                        price = s.get("current_price", 0)
                        
                        if rsi > 0 and price > 0:
                            line = f"  {sym} ${price:.2f}: RSI {rsi:.0f}"
                            line += f", {'above' if above_vwap else 'below'} VWAP (${vwap:.2f}, {dist_vwap:+.1f}%)"
                            line += f", EMA9 ${ema9:.2f}, EMA20 ${ema20:.2f}"
                            line += f", trend={trend}, RVOL {rvol:.1f}x, ATR {atr_pct:.1f}%"
                            if support: line += f", support ${support:.2f}"
                            if resistance: line += f", resistance ${resistance:.2f}"
                            if squeeze: line += " ** SQUEEZE ACTIVE **"
                            if abs(rs_spy) > 1: line += f", RS vs SPY {rs_spy:+.1f}%"
                            tech_lines.append(line)
                        else:
                            symbols_without_tech.append(sym)
                    else:
                        symbols_without_tech.append(sym)
                else:
                    symbols_without_tech.append(sym)
            except Exception:
                symbols_without_tech.append(sym)
        
        if tech_lines:
            parts.append(
                f"Technical Indicators (LIVE — use these when discussing technicals):\n"
                + "\n".join(tech_lines)
            )
        if symbols_without_tech:
            parts.append(
                f"No technical data for: {', '.join(symbols_without_tech)} "
                f"(pre-market or no bars — do NOT guess their technicals)"
            )
    except Exception:
        pass

    # 12. Strategy performance by setup type
    try:
        strat_stats = list(db["strategy_stats"].find(
            {"alerts_triggered": {"$gt": 5}},
            {"_id": 0, "setup_type": 1, "win_rate": 1, "profit_factor": 1,
             "expected_value_r": 1, "total_pnl": 1, "alerts_triggered": 1}
        ).sort("expected_value_r", -1).limit(10))
        if strat_stats:
            strat_lines = []
            for s in strat_stats:
                ev = s.get("expected_value_r", 0)
                wr = s.get("win_rate", 0) * 100
                pf = s.get("profit_factor", 0)
                n = s.get("alerts_triggered", 0)
                label = "STRONG" if ev > 0.3 else "OK" if ev > 0 else "WEAK"
                strat_lines.append(
                    f"  {s['setup_type']:25s} WR {wr:.0f}% | PF {pf:.1f} | EV {ev:+.2f}R | {n} trades | {label}"
                )
            parts.append("Strategy Performance (by EV):\n" + "\n".join(strat_lines))
    except Exception:
        pass

    # 13. Latest self-reflections and playbook learnings (for coaching conversations)
    try:
        # Recent DRC reflections
        latest_drc = db["daily_report_cards"].find_one(
            {"self_reflection_complete": True},
            {"_id": 0, "date": 1, "reflections": 1},
            sort=[("date", -1)]
        )
        if latest_drc and latest_drc.get("reflections"):
            ref = latest_drc["reflections"]
            drc_text = f"Latest Self-Reflection ({latest_drc.get('date', '?')}): {ref.get('summary', '')}"
            if ref.get("what_went_right"):
                drc_text += f" Went right: {'; '.join(ref['what_went_right'][:3])}."
            if ref.get("what_went_wrong"):
                drc_text += f" Went wrong: {'; '.join(ref['what_went_wrong'][:3])}."
            if ref.get("what_to_improve"):
                drc_text += f" Action items: {'; '.join(ref['what_to_improve'][:2])}."
            parts.append(drc_text)
        
        # Playbook learnings (recent updates)
        playbooks_with_learnings = list(db["playbooks"].find(
            {"trade_review.last_updated": {"$exists": True}},
            {"_id": 0, "setup_type": 1, "name": 1, "trade_review": 1}
        ).sort("trade_review.last_updated", -1).limit(5))
        
        if playbooks_with_learnings:
            pb_lines = []
            for pb in playbooks_with_learnings:
                review = pb.get("trade_review", {})
                learned = review.get("what_did_i_learn", "")
                improve = review.get("how_could_i_do_better", "")
                perf = review.get("historical_performance", "")
                if learned:
                    pb_lines.append(f"  {pb.get('name', pb.get('setup_type', '?'))}: {learned[:100]} | Action: {improve[:80]}")
            if pb_lines:
                parts.append(
                    f"Playbook Self-Assessment (use when coaching on specific setups):\n"
                    + "\n".join(pb_lines)
                )
    except Exception:
        pass

    text = "\n\n".join(parts) if parts else "No portfolio data available at this moment. IB Pusher may not be connected or market is closed."
    debug["context_sections"] = len(parts)
    logger.info(f"Portfolio context: {len(parts)} sections, debug={json.dumps(debug)}")
    return {"text": text, "debug": debug}


def _get_chat_history(session_id: str = "default", limit: int = 20) -> list:
    """Get recent chat history for context — expanded to 20 messages for better recall"""
    try:
        docs = list(
            db["sentcom_chat_history"]
            .find({"session_id": session_id}, {"_id": 0, "role": 1, "content": 1})
            .sort("timestamp", -1)
            .limit(limit)
        )
        docs.reverse()
        return docs
    except Exception:
        return []


def _store_message(role: str, content: str, session_id: str = "default",
                   model: str = None, latency_ms: float = None, 
                   context_hash: str = None, trade_action: dict = None,
                   session_mode: str = None):
    """Store a chat message with rich metadata"""
    try:
        doc = {
            "role": role,
            "content": content,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if model:
            doc["model"] = model
        if latency_ms is not None:
            doc["latency_ms"] = round(latency_ms)
        if context_hash:
            doc["context_hash"] = context_hash
        if trade_action:
            doc["trade_action"] = trade_action
        if session_mode:
            doc["session_mode"] = session_mode
        db["sentcom_chat_history"].insert_one(doc)
    except Exception as e:
        logger.warning(f"Failed to store chat message: {e}")


def _archive_context(context_text: str, session_id: str = "default") -> str:
    """Archive the full context snapshot for audit trail. Returns a hash for linking."""
    try:
        import hashlib
        ctx_hash = hashlib.md5(context_text[:500].encode()).hexdigest()[:12]
        # Only store if we haven't stored this exact context recently (dedup)
        existing = db["sentcom_context_archive"].find_one(
            {"hash": ctx_hash, "session_id": session_id},
            {"_id": 0, "hash": 1}
        )
        if not existing:
            db["sentcom_context_archive"].insert_one({
                "hash": ctx_hash,
                "session_id": session_id,
                "context": context_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "context_length": len(context_text),
            })
        return ctx_hash
    except Exception as e:
        logger.debug(f"Context archive error: {e}")
        return ""


def _get_persistent_memories(limit: int = 30) -> list:
    """Get all persistent memories — trading rules, lessons, preferences."""
    try:
        docs = list(
            db["sentcom_memory"]
            .find({"active": True}, {"_id": 0, "content": 1, "category": 1, "created_at": 1})
            .sort("created_at", -1)
            .limit(limit)
        )
        return docs
    except Exception:
        return []


def _extract_and_store_memory(user_msg: str, assistant_msg: str, session_id: str):
    """Auto-extract lessons/decisions from conversation and store as persistent memory.
    
    Looks for patterns like:
    - Explicit agreements ("let's avoid...", "from now on...", "rule:...")
    - Strategy decisions ("we should always...", "never...")
    - Lessons learned ("that didn't work because...", "lesson:...")
    """
    combined = (user_msg + " " + assistant_msg).lower()
    
    # Keywords that signal a persistent memory worth saving
    memory_triggers = [
        "from now on", "let's always", "let's never", "new rule", "lesson learned",
        "remember this", "note to self", "going forward", "we agreed", "our rule is",
        "don't forget", "important:", "key takeaway", "strategy change",
        "stop doing", "start doing", "avoid", "preference:"
    ]
    
    triggered = any(trigger in combined for trigger in memory_triggers)
    if not triggered:
        return
    
    try:
        # Store the memory with context
        memory_content = f"[From chat on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}]\n"
        # Use the assistant's response as the memory (it's the synthesized version)
        # But cap it to keep memories concise
        if len(assistant_msg) > 300:
            memory_content += assistant_msg[:300] + "..."
        else:
            memory_content += assistant_msg
        
        db["sentcom_memory"].insert_one({
            "content": memory_content,
            "category": "auto_extracted",
            "source_user_msg": user_msg[:200],
            "session_id": session_id,
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Stored new persistent memory from chat session {session_id}")
    except Exception as e:
        logger.debug(f"Memory extraction error: {e}")


def _get_last_session_summary(current_session_id: str) -> str:
    """Get the most recent session summary (from a different session) for continuity."""
    try:
        doc = db["sentcom_chat_sessions"].find_one(
            {"session_id": {"$ne": current_session_id}},
            {"_id": 0, "summary": 1, "session_id": 1, "created_at": 1},
            sort=[("created_at", -1)]
        )
        if doc:
            return f"[Previous session ({doc.get('created_at', '?')[:10]})] {doc.get('summary', '')}"
        return ""
    except Exception:
        return ""


def _generate_session_summary(session_id: str):
    """Generate and store a summary for a session when it ends or goes stale."""
    try:
        # Get all messages for this session
        messages = list(
            db["sentcom_chat_history"]
            .find({"session_id": session_id}, {"_id": 0, "role": 1, "content": 1, "timestamp": 1})
            .sort("timestamp", 1)
            .limit(50)
        )
        if len(messages) < 2:
            return
        
        # Check if summary already exists
        existing = db["sentcom_chat_sessions"].find_one({"session_id": session_id})
        if existing:
            return
        
        # Build a simple extractive summary (key topics, decisions, action items)
        topics = set()
        decisions = []
        user_questions = []
        
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            
            if role == "user" and len(content) > 10:
                user_questions.append(content[:100])
            
            # Look for trade-related content
            content_lower = content.lower()
            for keyword in ["close", "buy", "sell", "stop", "target", "exit", "entry"]:
                if keyword in content_lower:
                    decisions.append(content[:120])
                    break
            
            # Extract mentioned symbols
            import re
            symbols = re.findall(r'\b[A-Z]{2,5}\b', content)
            for s in symbols:
                if s not in ('THE', 'AND', 'FOR', 'NOT', 'ARE', 'BUT', 'HAS', 'WAS', 'THIS', 'THAT', 'WITH', 'FROM', 'HAVE', 'WILL', 'BEEN', 'THEY', 'SOME', 'WHAT', 'WHEN', 'YOUR', 'JUST', 'LIKE', 'THAN', 'THEM', 'THEN', 'ALSO', 'INTO', 'OVER', 'SUCH', 'TAKE', 'HERE', 'EACH', 'MAKE', 'VERY', 'AFTER', 'ABOUT'):
                    topics.add(s)
        
        summary = f"Discussed {len(messages)} messages. "
        if topics:
            summary += f"Symbols: {', '.join(list(topics)[:10])}. "
        if user_questions:
            summary += f"Key questions: {'; '.join(user_questions[:3])}. "
        if decisions:
            summary += f"Decisions: {'; '.join(decisions[:3])}"
        
        db["sentcom_chat_sessions"].insert_one({
            "session_id": session_id,
            "summary": summary[:500],
            "message_count": len(messages),
            "topics": list(topics)[:15],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "first_message": messages[0].get("timestamp", ""),
            "last_message": messages[-1].get("timestamp", ""),
        })
        logger.info(f"Generated session summary for {session_id}: {len(messages)} messages")
    except Exception as e:
        logger.debug(f"Session summary error: {e}")


def _call_ollama(messages: list, model: str, timeout: int = 60) -> Optional[str]:
    """Call Ollama and return content, or None on failure"""
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 1500}
            },
            timeout=timeout
        )
        data = r.json()
        if "error" in data:
            logger.warning(f"Ollama {model}: {data['error']}")
            return None
        return data.get("message", {}).get("content", "")
    except Exception as e:
        logger.warning(f"Ollama {model} failed: {e}")
        return None


@app.get("/health")
def health():
    return {"status": "healthy", "service": "chat_server", "port": 8002}


@app.get("/context-debug")
def context_debug():
    """Diagnostic: shows exactly what context the chat server can see"""
    result = _get_portfolio_context()
    return {
        "context_text": result["text"],
        "debug": result["debug"],
        "mongo_connected": _check_mongo(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def _check_mongo() -> bool:
    try:
        db.command("ping")
        return True
    except Exception:
        return False


def _execute_trade_action(response_text: str) -> Optional[dict]:
    """Parse and execute trade actions from LLM response."""
    import re
    import requests
    
    match = re.search(r'<<<TRADE_ACTION:\s*(\{.*?\})\s*>>>', response_text)
    if not match:
        return None
    
    try:
        action_data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"success": False, "error": "Invalid trade action format"}
    
    action = action_data.get("action", "").lower()
    symbol = action_data.get("symbol", "").upper()
    reason = action_data.get("reason", "chat_requested")
    
    if not symbol:
        return {"success": False, "error": "No symbol specified"}
    
    # Route to main backend API
    backend_url = os.environ.get("BACKEND_URL", "http://127.0.0.1:8001")
    
    try:
        if action == "close":
            # Find the bot trade ID for this symbol and close it
            resp = requests.post(
                f"{backend_url}/api/trading-bot/close-by-symbol",
                json={"symbol": symbol, "reason": reason},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return {"success": True, "summary": f"Sold {symbol} — {data.get('message', 'order submitted')}"}
                else:
                    return {"success": False, "error": data.get("error", "Close failed")}
            else:
                return {"success": False, "error": f"Backend returned {resp.status_code}"}
        
        elif action in ("buy", "sell"):
            # Place a new order
            shares = action_data.get("shares", 0)
            resp = requests.post(
                f"{backend_url}/api/trading-bot/quick-order",
                json={
                    "symbol": symbol,
                    "action": action,
                    "shares": shares,
                    "reason": reason
                },
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"success": data.get("success", False), "summary": data.get("message", f"{action} {shares} {symbol}")}
            else:
                return {"success": False, "error": f"Backend returned {resp.status_code}"}
        
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    
    except requests.Timeout:
        return {"success": False, "error": "Backend timeout — order may still be processing"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/chat")
def chat(request: ChatRequest):
    """Process a chat message — fully sync, dedicated process"""
    start = time.time()
    
    # Build context
    ctx = _get_portfolio_context()
    context = ctx["text"]
    session_mode = ctx.get("debug", {}).get("session_mode", "unknown")
    history = _get_chat_history(request.session_id, limit=20)
    
    # Archive context for audit trail
    ctx_hash = _archive_context(context, request.session_id)
    
    # Load persistent memories (trading rules, lessons, preferences)
    memories = _get_persistent_memories(limit=30)
    memory_block = ""
    if memories:
        mem_lines = [m.get("content", "") for m in memories]
        memory_block = "\n\nPERSISTENT MEMORY (our agreed rules, lessons, and preferences — always follow these):\n" + "\n".join(f"- {m}" for m in mem_lines)
    
    # Load last session summary for cross-session continuity
    last_session = _get_last_session_summary(request.session_id)
    session_block = ""
    if last_session:
        session_block = f"\n\nLAST SESSION CONTEXT:\n{last_session}"
    
    system_prompt = f"""You are SentCom — my AI trading partner. We trade together as a team.

PERSONALITY:
- Talk like a sharp, experienced trading buddy sitting next to me. Not a report generator.
- Use "we", "our", "us" — we're in this together.
- Be direct and conversational. Do not use markdown tables. Do not use ### headers. Just talk to me naturally.
- Lead with what matters most. If something is bleeding, say it first.
- Suggest specific actions with conviction: "I think we should close LABD now — it's down 30% and dragging the whole book" not "Consider evaluating the LABD position."
- When you see a setup forming, be proactive: "I'm watching TSLA for a second chance scalp — I'll pull the trigger when VWAP confirms."
- Use ONLY the real numbers from the LIVE DATA section below. Never guess prices from memory. If a price isn't in the data, say "I don't have a live quote on that right now."
- Keep responses tight. 2-4 short paragraphs max. Only use bullet lists if I ask for a breakdown.
- Be professional but human. Keep it clean and direct.

CRITICAL RULES — DO NOT BREAK THESE:
- NEVER state technical indicator values (RSI, MACD, moving averages, support/resistance levels) unless they are explicitly provided in the LIVE DATA below. You do NOT have access to charts.
- NEVER reference specific news events, earnings dates, Fed meetings, or macro releases. You do NOT have a news feed. If asked about news, say "I don't have a live news feed right now — check your usual sources."
- NEVER guess prices for symbols not in the LIVE DATA. Say "I don't have a quote on [symbol] right now."
- When the market is closed, say so. Do not pretend prices are moving in real-time.
- If technical indicators ARE provided for a symbol in the data below, USE them confidently and specifically.

TRADING KNOWLEDGE — Use this to guide your advice:

Setup Evaluation Framework:
- A good long entry has: price above VWAP, RSI between 40-65 (not overbought), RVOL > 1.2x, trend = uptrend, support nearby
- A good short entry has: price below VWAP, RSI between 35-60 (not oversold), declining into resistance
- Squeeze setups (BB inside KC): wait for the "fire" — momentum direction tells you which way it breaks. Don't enter DURING the squeeze, enter on the breakout with volume confirmation
- Second chance entries: must retest VWAP and hold. If it slices through VWAP, it's not a second chance — it's a breakdown
- Breakout entries: need volume confirmation (RVOL > 1.3x minimum). No volume = false breakout

Risk Management Rules:
- Never risk more than $2,500 on a single trade
- Minimum R:R is 1.5:1 — never take a trade where the reward doesn't justify the risk
- If our daily P&L hits -1% of account, recommend stopping for the day
- If we have 3+ losers in a row, suggest reducing size by 50% or taking a 15 min break
- Max 10 open positions at once — if we're at the limit, something must close before we add
- Concentration risk: no single position should be more than 15% of the portfolio. Flag it if so.
- Stops must be respected. Never suggest moving a stop further away from entry.

Position Sizing Logic (when asked "how many shares"):
- shares = max_risk / (entry - stop)
- Then cap at 50% of account / entry_price
- Scale with volatility: low ATR = more shares, high ATR = fewer
- REDUCE decisions from the gate = 60% of calculated size

How to Read the Technical Data:
- RSI < 30 = oversold (potential bounce), RSI > 70 = overbought (potential fade)
- RSI 40-60 = neutral zone, good for trend continuation entries
- RVOL > 1.5 = strong interest, RVOL > 2.0 = unusual activity worth investigating
- Above VWAP + above EMA9 = strong intraday trend, ride it
- Below VWAP + below EMA9 = weak, look for shorts or wait for reclaim
- ATR% tells you how volatile the stock is: < 2% = low vol, 2-4% = normal, > 4% = high vol
- Squeeze active = volatility compression, prepare for explosive move. Direction determined by momentum
- RS vs SPY positive = outperforming market (bullish), negative = underperforming (bearish)

When to Suggest Exits:
- If a position hits its target R:R (e.g., 2:1), suggest taking at least partial profits
- If RSI > 80 on a long position, suggest tightening stop to lock in gains
- If price breaks below VWAP on a long after being above all day, suggest exiting
- If a stock gaps down through support, suggest immediate exit — don't wait for it to "come back"
- If volume dries up on a breakout, the move is losing momentum — tighten stop

When Asked About Tomorrow / Next Session:
- Look at today's trend, key levels (support/resistance), and whether we closed strong or weak
- Suggest watching the opening 5-15 minutes for direction
- Identify which positions need attention based on their levels
- Do NOT make predictions — instead say "If X happens, we should do Y. If Z happens, we should do W."
- Reference the PRE-MARKET WATCHLIST if available — those are real setups the scanner identified

SESSION-AWARE COACHING:
- PRE-MARKET (7:00-9:30 AM): Focus on the morning watchlist. Discuss which gap plays look best, which ORB candidates have the tightest ranges, and what the opening drive might look like based on pre-market action. Help prioritize which 2-3 names to focus on at the bell. Review overnight positions and whether any stops need adjusting before the open.
- MARKET OPEN (9:30-4:00 PM): Full trading mode. React to live data. Suggest entries, exits, stops. Monitor positions actively.
- AFTER HOURS (4:00+ PM): Review the day's performance. Discuss what worked and what didn't. Look at daily chart setups forming for tomorrow (swing/position trades). Identify which sectors showed relative strength or weakness. Help plan tomorrow's focus areas.
- WEEKENDS/CLOSED: Discuss longer-term strategy. Review weekly performance. Analyze daily chart setups. Discuss risk management adjustments. Look at portfolio allocation and concentration.

SELF-AWARENESS & COACHING:
- You have access to your own self-reflections (DRC data, playbook learnings). Use them honestly.
- When asked "how are we doing on X setup?" — reference the actual playbook win rate and reflections, not guesses.
- When asked "what should we improve?" — pull from the latest DRC reflections and playbook action items.
- Be honest about what's working and what isn't. If a setup has a 30% win rate, say so and suggest changes.
- Track patterns across days: "We've been struggling with [setup] for 3 days — let's pause it and review."
- The user can challenge your reflections. Be open to discussion, not defensive.
- Your reflections update daily after market close. Reference the date so the user knows how current the data is.

TRADE EXECUTION:
- When I ask to close, buy, or sell a position, include a JSON block at the END of your response:
  <<<TRADE_ACTION: {{"action": "close", "symbol": "LABD", "reason": "user_requested"}}>>>
- Only include this when I'm clearly requesting a trade action, not when discussing hypotheticals.
- Confirm the action in plain English BEFORE the JSON block.

=== LIVE DATA ===
{context}
=== END DATA ==={memory_block}{session_block}"""
    
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history
    for msg in history:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    
    # Add current message
    messages.append({"role": "user", "content": request.message})
    
    # Store user message with rich metadata
    _store_message("user", request.message, request.session_id, 
                   session_mode=session_mode, context_hash=ctx_hash)
    
    # Call Ollama (try primary, then fallback)
    response_content = _call_ollama(messages, OLLAMA_MODEL)
    used_model = OLLAMA_MODEL
    
    if not response_content and OLLAMA_FALLBACK != OLLAMA_MODEL:
        logger.info(f"Falling back to {OLLAMA_FALLBACK}")
        response_content = _call_ollama(messages, OLLAMA_FALLBACK, timeout=120)
        used_model = OLLAMA_FALLBACK
    
    if not response_content:
        response_content = "Having trouble connecting to our AI right now. Give me a sec and try again."
    
    # Check for trade action commands in the response
    trade_result = None
    trade_action_data = None
    if "<<<TRADE_ACTION:" in response_content:
        trade_result = _execute_trade_action(response_content)
        trade_action_data = trade_result
        # Clean the action block from the user-facing response
        import re
        response_content = re.sub(r'<<<TRADE_ACTION:.*?>>>', '', response_content).strip()
        if trade_result:
            if trade_result.get("success"):
                response_content += f"\n\n✓ Order submitted: {trade_result.get('summary', 'Processing...')}"
            else:
                response_content += f"\n\nCouldn't execute that — {trade_result.get('error', 'unknown error')}. You may need to do it manually in TWS."
    
    latency = (time.time() - start) * 1000
    
    # Store response with full metadata
    _store_message("assistant", response_content, request.session_id,
                   model=used_model, latency_ms=latency, context_hash=ctx_hash,
                   trade_action=trade_action_data, session_mode=session_mode)
    
    # Auto-extract persistent memories from this exchange
    _extract_and_store_memory(request.message, response_content, request.session_id)
    
    # Generate session summary if switching sessions (check if last message was from a different session)
    try:
        last_msg = db["sentcom_chat_history"].find_one(
            {"session_id": {"$ne": request.session_id}, "role": "user"},
            {"_id": 0, "session_id": 1},
            sort=[("timestamp", -1)]
        )
        if last_msg:
            _generate_session_summary(last_msg["session_id"])
    except Exception:
        pass
    
    logger.info(f"Chat response in {latency:.0f}ms via {used_model}")
    
    return {
        "success": True,
        "response": response_content,
        "source": f"sentcom ({used_model})",
        "latency_ms": latency,
        "agent": "sentcom",
        "model": used_model,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/chat/history")
def get_history(limit: int = 50, session_id: str = "default"):
    """Get chat history"""
    try:
        docs = list(
            db["sentcom_chat_history"]
            .find({"session_id": session_id}, {"_id": 0})
            .sort("timestamp", -1)
            .limit(limit)
        )
        docs.reverse()
        return {"success": True, "history": docs}
    except Exception as e:
        return {"success": False, "error": str(e), "history": []}


@app.get("/chat/memories")
def get_memories():
    """Get all persistent memories"""
    try:
        docs = list(
            db["sentcom_memory"]
            .find({"active": True}, {"_id": 0})
            .sort("created_at", -1)
        )
        return {"success": True, "memories": docs, "count": len(docs)}
    except Exception as e:
        return {"success": False, "error": str(e), "memories": []}


@app.post("/chat/memories")
def add_memory(memory: dict):
    """Manually add a persistent memory (trading rule, lesson, preference)"""
    try:
        content = memory.get("content", "").strip()
        category = memory.get("category", "manual")
        if not content:
            return {"success": False, "error": "Content is required"}
        
        db["sentcom_memory"].insert_one({
            "content": content,
            "category": category,
            "source_user_msg": "manual_entry",
            "session_id": "manual",
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"success": True, "message": "Memory stored"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/chat/memories/{memory_id}")
def deactivate_memory(memory_id: str):
    """Deactivate a persistent memory (soft delete)"""
    try:
        from bson import ObjectId
        result = db["sentcom_memory"].update_one(
            {"_id": ObjectId(memory_id)},
            {"$set": {"active": False, "deactivated_at": datetime.now(timezone.utc).isoformat()}}
        )
        if result.modified_count > 0:
            return {"success": True, "message": "Memory deactivated"}
        return {"success": False, "error": "Memory not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/chat/sessions")
def get_sessions(limit: int = 20):
    """Get session summaries"""
    try:
        docs = list(
            db["sentcom_chat_sessions"]
            .find({}, {"_id": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        return {"success": True, "sessions": docs, "count": len(docs)}
    except Exception as e:
        return {"success": False, "error": str(e), "sessions": []}


@app.get("/chat/context/{context_hash}")
def get_archived_context(context_hash: str):
    """Retrieve an archived context snapshot by hash (for auditing)"""
    try:
        doc = db["sentcom_context_archive"].find_one(
            {"hash": context_hash},
            {"_id": 0}
        )
        if doc:
            return {"success": True, "context": doc}
        return {"success": False, "error": "Context not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/chat/stats")
def get_chat_stats():
    """Get overall chat system stats"""
    try:
        total_messages = db["sentcom_chat_history"].count_documents({})
        total_memories = db["sentcom_memory"].count_documents({"active": True})
        total_sessions = db["sentcom_chat_sessions"].count_documents({})
        total_contexts = db["sentcom_context_archive"].count_documents({})
        
        # Recent activity
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
        today_messages = db["sentcom_chat_history"].count_documents(
            {"timestamp": {"$gte": today}}
        )
        
        return {
            "success": True,
            "total_messages": total_messages,
            "today_messages": today_messages,
            "active_memories": total_memories,
            "session_summaries": total_sessions,
            "context_archives": total_contexts,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CHAT_PORT", 8002))
    logger.info(f"Starting SentCom Chat Server on port {port}")
    logger.info(f"  Primary model: {OLLAMA_MODEL}")
    logger.info(f"  Fallback model: {OLLAMA_FALLBACK}")
    logger.info(f"  Ollama URL: {OLLAMA_URL}")
    logger.info(f"  MongoDB: {MONGO_URL}/{DB_NAME}")
    uvicorn.run(app, host="0.0.0.0", port=port)
