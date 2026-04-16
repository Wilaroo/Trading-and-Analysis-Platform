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
        if 'quotes' in dir() and quotes:
            idx_lines = []
            for idx_sym in ['SPY', 'QQQ', 'IWM', 'DIA', 'VIX']:
                q = quotes.get(idx_sym, {})
                if q:
                    last = q.get("last") or q.get("close") or 0
                    chg = q.get("change") or 0
                    chg_pct = q.get("changePercent") or q.get("change_pct") or 0
                    if last > 0:
                        idx_lines.append(f"  {idx_sym}: ${last:.2f} ({chg_pct:+.2f}%)")
            if idx_lines:
                parts.append("Market Indices (LIVE):\n" + "\n".join(idx_lines))
    except Exception:
        pass
    try:
        recent = list(
            db["shadow_decisions"]
            .find({}, {"_id": 0, "symbol": 1, "combined_recommendation": 1, "confidence_score": 1})
            .sort("created_at", -1)
            .limit(5)
        )
        debug["shadow_decisions_count"] = len(recent)
        if recent:
            gate_lines = [
                f"  {r.get('symbol','?')}: {r.get('combined_recommendation','?').upper()} "
                f"(score: {r.get('confidence_score', 0)})"
                for r in recent
            ]
            parts.append("Recent AI Gate Decisions:\n" + "\n".join(gate_lines))
    except Exception as e:
        debug["shadow_error"] = str(e)

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
            .find({}, {"_id": 0, "symbol": 1, "direction": 1, "entry_price": 1,
                       "exit_price": 1, "pnl": 1, "status": 1, "setup_type": 1,
                       "entry_time": 1, "exit_time": 1})
            .sort("entry_time", -1)
            .limit(10)
        )
        # Also get recent bot_trades for richer history
        bot_closed = list(
            db["bot_trades"]
            .find({"status": {"$in": ["closed", "stopped_out", "target_hit"]}},
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

    text = "\n\n".join(parts) if parts else "No portfolio data available at this moment. IB Pusher may not be connected or market is closed."
    debug["context_sections"] = len(parts)
    logger.info(f"Portfolio context: {len(parts)} sections, debug={json.dumps(debug)}")
    return {"text": text, "debug": debug}


def _get_chat_history(session_id: str = "default", limit: int = 10) -> list:
    """Get recent chat history for context"""
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


def _store_message(role: str, content: str, session_id: str = "default"):
    """Store a chat message"""
    try:
        db["sentcom_chat_history"].insert_one({
            "role": role,
            "content": content,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except Exception:
        pass


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
    history = _get_chat_history(request.session_id, limit=6)
    
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

TRADE EXECUTION:
- When I ask to close, buy, or sell a position, include a JSON block at the END of your response:
  <<<TRADE_ACTION: {{"action": "close", "symbol": "LABD", "reason": "user_requested"}}>>>
  <<<TRADE_ACTION: {{"action": "buy", "symbol": "TSLA", "shares": 100, "reason": "second_chance_scalp"}}>>>
- Only include this when I'm clearly requesting a trade action, not when discussing hypotheticals.
- Confirm the action in plain English BEFORE the JSON block.

CONTEXT:
- If our positions are flat or at zero P&L, they likely just entered — don't panic about them.
- LABD is a 3x leveraged inverse biotech ETF — it decays over time. If we're holding it as a hedge, mention that.
- When evaluating the portfolio, focus on: what's working, what's not, and what we should do about it RIGHT NOW.

=== LIVE DATA ===
{context}
=== END DATA ==="""
    
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history
    for msg in history:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    
    # Add current message
    messages.append({"role": "user", "content": request.message})
    
    # Store user message
    _store_message("user", request.message, request.session_id)
    
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
    if "<<<TRADE_ACTION:" in response_content:
        trade_result = _execute_trade_action(response_content)
        # Clean the action block from the user-facing response
        import re
        response_content = re.sub(r'<<<TRADE_ACTION:.*?>>>', '', response_content).strip()
        if trade_result:
            if trade_result.get("success"):
                response_content += f"\n\n✓ Order submitted: {trade_result.get('summary', 'Processing...')}"
            else:
                response_content += f"\n\nCouldn't execute that — {trade_result.get('error', 'unknown error')}. You may need to do it manually in TWS."
    
    # Store response
    _store_message("assistant", response_content, request.session_id)
    
    latency = (time.time() - start) * 1000
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


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CHAT_PORT", 8002))
    logger.info(f"Starting SentCom Chat Server on port {port}")
    logger.info(f"  Primary model: {OLLAMA_MODEL}")
    logger.info(f"  Fallback model: {OLLAMA_FALLBACK}")
    logger.info(f"  Ollama URL: {OLLAMA_URL}")
    logger.info(f"  MongoDB: {MONGO_URL}/{DB_NAME}")
    uvicorn.run(app, host="0.0.0.0", port=port)
