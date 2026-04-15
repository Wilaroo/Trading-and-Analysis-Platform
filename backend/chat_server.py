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
import requests
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
    """Build rich portfolio context by fetching from main backend + MongoDB.
    Returns dict with 'text' (for LLM) and 'debug' (for diagnostics)."""
    parts = []
    debug = {}
    backend = "http://127.0.0.1:8001"
    
    # 1. Live positions from main backend (in-memory, fast)
    try:
        r = requests.get(f"{backend}/api/ib/pushed-data", timeout=5)
        debug["ib_pushed_status"] = r.status_code
        if r.status_code == 200:
            data = r.json()
            connected = data.get("connected", False)
            positions = data.get("positions", [])
            quotes = data.get("quotes", {})
            account = data.get("account", {})
            debug["ib_connected"] = connected
            debug["ib_positions_count"] = len(positions)
            debug["ib_quotes_count"] = len(quotes)
            debug["ib_account_keys"] = list(account.keys())[:10]
            
            if positions:
                pos_lines = []
                total_pnl = 0
                for p in positions[:10]:
                    symbol = p.get("symbol", "?")
                    qty = p.get("quantity", p.get("position", 0))
                    direction = "LONG" if qty > 0 else "SHORT"
                    avg = p.get("avgCost", p.get("avg_cost", 0))
                    mkt = p.get("marketPrice", p.get("market_price", avg))
                    pnl = p.get("unrealizedPNL", p.get("unrealized_pnl", 0))
                    total_pnl += pnl
                    
                    quote = quotes.get(symbol, {})
                    if quote:
                        mkt = quote.get("last", quote.get("close", mkt))
                    
                    pos_lines.append(
                        f"  {symbol} ({direction}): {abs(qty):.0f} shares @ ${avg:.2f}, "
                        f"current ${mkt:.2f}, P&L ${pnl:+,.2f}"
                    )
                parts.append(
                    f"Current Positions ({len(pos_lines)}):\n"
                    + "\n".join(pos_lines)
                    + f"\n  Total Unrealized P&L: ${total_pnl:+,.2f}"
                )
            else:
                parts.append(f"IB Connected: {connected}. No open positions currently.")
            
            if account:
                netliq = account.get("NetLiquidation", account.get("net_liquidation", ""))
                buying = account.get("BuyingPower", account.get("buying_power", ""))
                if netliq:
                    parts.append(f"Account: Net Liq ${float(netliq):,.2f}" + (f", Buying Power ${float(buying):,.2f}" if buying else ""))
        else:
            debug["ib_pushed_error"] = f"HTTP {r.status_code}"
            logger.warning(f"IB pushed-data returned {r.status_code}")
    except Exception as e:
        debug["ib_pushed_error"] = str(e)
        logger.warning(f"Failed to get positions from backend: {e}")

    # 2. Scanner alerts (what the AI scanner is seeing right now)
    try:
        r = requests.get(f"{backend}/api/live-scanner/alerts?limit=10", timeout=5)
        debug["scanner_status"] = r.status_code
        if r.status_code == 200:
            data = r.json()
            alerts = data.get("alerts", data) if isinstance(data, dict) else data
            debug["scanner_alerts_count"] = len(alerts) if isinstance(alerts, list) else 0
            if isinstance(alerts, list) and alerts:
                alert_lines = []
                for a in alerts[:8]:
                    sym = a.get("symbol", "?")
                    setup = a.get("setup_type", a.get("pattern", ""))
                    score = a.get("score", a.get("confidence", ""))
                    alert_lines.append(f"  {sym}: {setup}" + (f" (score: {score})" if score else ""))
                parts.append("Scanner Alerts (live):\n" + "\n".join(alert_lines))
    except Exception as e:
        debug["scanner_error"] = str(e)

    # 3. Bot status (trading mode, today's stats)
    try:
        r = requests.get(f"{backend}/api/ai-training/confidence-gate/summary", timeout=5)
        debug["gate_status"] = r.status_code
        if r.status_code == 200:
            data = r.json()
            if data.get("success"):
                mode = data.get("trading_mode", "unknown")
                reason = data.get("mode_reason", "")
                today = data.get("today", {})
                evaluated = today.get("evaluated", 0)
                taken = today.get("taken", 0)
                skipped = today.get("skipped", 0)
                parts.append(
                    f"Trading Mode: {mode.upper()}" + (f" ({reason})" if reason else "")
                    + f"\nToday's Gate: {evaluated} evaluated, {taken} taken, {skipped} skipped"
                )
    except Exception as e:
        debug["gate_error"] = str(e)

    # 4. AI gate decisions (from MongoDB)
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

    # 5. Market regime (from MongoDB)
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

    # 6. Recent trade history (from MongoDB)
    try:
        recent_trades = list(
            db["trades"]
            .find({}, {"_id": 0, "symbol": 1, "direction": 1, "entry_price": 1,
                       "exit_price": 1, "pnl": 1, "status": 1, "setup_type": 1,
                       "entry_time": 1, "exit_time": 1})
            .sort("entry_time", -1)
            .limit(10)
        )
        debug["trades_count"] = len(recent_trades)
        if recent_trades:
            trade_lines = []
            wins = sum(1 for t in recent_trades if (t.get("pnl") or 0) > 0)
            total = len(recent_trades)
            for t in recent_trades[:5]:
                sym = t.get("symbol", "?")
                direction = t.get("direction", "?")
                pnl = t.get("pnl", 0)
                status = t.get("status", "?")
                setup = t.get("setup_type", "")
                trade_lines.append(
                    f"  {sym} ({direction}): ${pnl:+,.2f} [{status}]"
                    + (f" — {setup}" if setup else "")
                )
            parts.append(
                f"Recent Trades (last {total}): {wins}W / {total-wins}L "
                f"({wins/total*100:.0f}% win rate)\n" + "\n".join(trade_lines)
            )
    except Exception as e:
        debug["trades_error"] = str(e)

    # 7. Performance stats (from MongoDB)
    try:
        perf = db["performance_daily"].find_one(
            {}, {"_id": 0},
            sort=[("date", -1)]
        )
        debug["perf_found"] = perf is not None
        if perf:
            daily_pnl = perf.get("realized_pnl", perf.get("pnl", 0))
            total_trades = perf.get("total_trades", 0)
            win_rate = perf.get("win_rate", 0)
            parts.append(
                f"Today's Performance: P&L ${daily_pnl:+,.2f}, "
                f"{total_trades} trades, {win_rate:.0f}% win rate"
            )
    except Exception as e:
        debug["perf_error"] = str(e)

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


@app.post("/chat")
def chat(request: ChatRequest):
    """Process a chat message — fully sync, dedicated process"""
    start = time.time()
    
    # Build context
    ctx = _get_portfolio_context()
    context = ctx["text"]
    history = _get_chat_history(request.session_id, limit=6)
    
    system_prompt = f"""You are SentCom, an AI trading co-pilot for a live trading operation.
Speak in first person plural ("we", "our", "us") — you and the trader are a team.
Be concise, direct, and actionable. Use specific numbers from the data below.
When reviewing positions, mention entry price, current price, P&L, and whether stops/targets are hit.
When asked about risk, consider position sizing, portfolio concentration, and market regime.
If the data below shows no positions, tell the user we have no open positions right now (don't ask them to paste data).
If IB is disconnected or no data is available, say so directly.

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
        response_content = "I'm having trouble connecting to our AI right now. Please try again in a moment."
    
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
