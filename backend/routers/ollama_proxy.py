"""
Ollama Proxy Router - HTTP polling proxy endpoints and usage tracking
Extracted from server.py for modularity
"""
from fastapi import APIRouter
from datetime import datetime, timezone
from typing import Dict
import asyncio
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Ollama Proxy"])

# Dependencies injected via init
_ollama_proxy_manager = None


def init_ollama_proxy_router(ollama_proxy_manager):
    global _ollama_proxy_manager
    _ollama_proxy_manager = ollama_proxy_manager


# ===================== STATE VARIABLES =====================

_http_proxy_sessions: Dict = {}
_http_proxy_requests: Dict = {}
_http_proxy_responses: Dict = {}

_ollama_usage = {
    "session_requests": 0,
    "session_start": datetime.now(timezone.utc).isoformat(),
    "daily_requests": 0,
    "daily_start": datetime.now(timezone.utc).date().isoformat(),
    "weekly_requests": 0,
    "weekly_start": datetime.now(timezone.utc).date().isoformat(),
    "models_used": {},
    "request_history": []
}


# ===================== HELPER FUNCTIONS =====================

def _reset_ollama_usage_if_needed():
    """Reset usage counters if session/day/week has rolled over"""
    global _ollama_usage
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    
    if _ollama_usage["daily_start"] != today:
        _ollama_usage["daily_requests"] = 0
        _ollama_usage["daily_start"] = today
    
    try:
        session_start = datetime.fromisoformat(_ollama_usage["session_start"].replace("Z", "+00:00"))
        if (now - session_start).total_seconds() > 5 * 3600:
            _ollama_usage["session_requests"] = 0
            _ollama_usage["session_start"] = now.isoformat()
    except:
        _ollama_usage["session_start"] = now.isoformat()
    
    try:
        days_diff = (now.date() - datetime.fromisoformat(_ollama_usage["weekly_start"]).date()).days
        if days_diff >= 7:
            _ollama_usage["weekly_requests"] = 0
            _ollama_usage["weekly_start"] = today
    except:
        _ollama_usage["weekly_start"] = today


def track_ollama_request(model: str, success: bool = True):
    """Track an Ollama request for usage monitoring"""
    global _ollama_usage
    _reset_ollama_usage_if_needed()
    
    _ollama_usage["session_requests"] += 1
    _ollama_usage["daily_requests"] += 1
    _ollama_usage["weekly_requests"] += 1
    
    if model not in _ollama_usage["models_used"]:
        _ollama_usage["models_used"][model] = 0
    _ollama_usage["models_used"][model] += 1
    
    _ollama_usage["request_history"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "success": success
    })
    if len(_ollama_usage["request_history"]) > 50:
        _ollama_usage["request_history"] = _ollama_usage["request_history"][-50:]


def is_http_ollama_proxy_connected() -> bool:
    """Check if any HTTP Ollama proxy is connected and has models available"""
    for sid, info in _http_proxy_sessions.items():
        try:
            last_hb = datetime.fromisoformat(info.get("last_heartbeat", "").replace("Z", "+00:00"))
            is_recent = (datetime.now(timezone.utc) - last_hb).total_seconds() < 30
            if is_recent and info.get("ollama_status", {}).get("available", False):
                return True
        except:
            pass
    return False


def get_http_proxy_info() -> dict:
    """Get info about the connected HTTP proxy"""
    for sid, info in _http_proxy_sessions.items():
        try:
            last_hb = datetime.fromisoformat(info.get("last_heartbeat", "").replace("Z", "+00:00"))
            is_recent = (datetime.now(timezone.utc) - last_hb).total_seconds() < 30
            if is_recent and info.get("ollama_status", {}).get("available", False):
                return {
                    "session_id": sid,
                    "models": info.get("ollama_status", {}).get("models", []),
                    "last_heartbeat": info.get("last_heartbeat")
                }
        except:
            pass
    return {}


async def call_ollama_via_http_proxy(model: str, messages: list, options: dict = None, timeout: float = 120.0) -> dict:
    """Call Ollama through the HTTP proxy"""
    import uuid
    
    now = datetime.now(timezone.utc)
    active_sessions = []
    for sid, info in _http_proxy_sessions.items():
        last_hb = info.get("last_heartbeat", "")
        if last_hb:
            try:
                hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
                is_recent = (now - hb_time).total_seconds() < 120
            except:
                is_recent = False
        else:
            is_recent = False
        
        ollama_status = info.get("ollama_status", {})
        is_available = ollama_status.get("available", False) or len(ollama_status.get("models", [])) > 0
        
        if is_recent and is_available:
            active_sessions.append(sid)
    
    if not active_sessions:
        return {"success": False, "error": "No HTTP proxy connected"}
    
    request_id = f"req_{uuid.uuid4().hex[:8]}"
    future = asyncio.get_event_loop().create_future()
    
    _http_proxy_requests[request_id] = {
        "request": {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options or {}
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "future": future
    }
    
    try:
        result = await asyncio.wait_for(future, timeout=timeout)
        track_ollama_request(model, success=True)
        return result
    except asyncio.TimeoutError:
        track_ollama_request(model, success=False)
        return {"success": False, "error": "Request timed out"}
    finally:
        _http_proxy_requests.pop(request_id, None)
        _http_proxy_responses.pop(request_id, None)


# ===================== ENDPOINTS =====================

@router.get("/api/ollama-proxy/status")
async def get_ollama_proxy_status():
    """Get Ollama proxy connection status (both WebSocket and HTTP)"""
    ws_status = _ollama_proxy_manager.get_status()
    
    http_connected = False
    http_sessions = []
    for sid, info in _http_proxy_sessions.items():
        try:
            last_hb = datetime.fromisoformat(info.get("last_heartbeat", "").replace("Z", "+00:00"))
            is_recent = (datetime.now(timezone.utc) - last_hb).total_seconds() < 30
            if is_recent and info.get("ollama_status", {}).get("available", False):
                http_connected = True
                http_sessions.append({
                    "session_id": sid,
                    "models": info.get("ollama_status", {}).get("models", []),
                    "last_heartbeat": info.get("last_heartbeat")
                })
        except:
            pass
    
    return {
        "websocket": ws_status,
        "http": {
            "connected": http_connected,
            "sessions": http_sessions
        },
        "any_connected": ws_status.get("connected", False) or http_connected
    }


@router.get("/api/ollama-usage")
async def get_ollama_usage():
    """Get Ollama usage statistics"""
    _reset_ollama_usage_if_needed()
    
    session_limit = 150
    weekly_limit = 750
    
    session_used_pct = min(100, (_ollama_usage["session_requests"] / session_limit) * 100)
    weekly_used_pct = min(100, (_ollama_usage["weekly_requests"] / weekly_limit) * 100)
    
    now = datetime.now(timezone.utc)
    try:
        session_start = datetime.fromisoformat(_ollama_usage["session_start"].replace("Z", "+00:00"))
        session_age_hours = (now - session_start).total_seconds() / 3600
        session_reset_hours = max(0, 5 - session_age_hours)
    except:
        session_reset_hours = 5
    
    try:
        days_until_weekly_reset = 7 - (now.date() - datetime.fromisoformat(_ollama_usage["weekly_start"]).date()).days
    except:
        days_until_weekly_reset = 7
    
    return {
        "session": {
            "requests": _ollama_usage["session_requests"],
            "limit": session_limit,
            "used_percent": round(session_used_pct, 1),
            "reset_hours": round(session_reset_hours, 1)
        },
        "weekly": {
            "requests": _ollama_usage["weekly_requests"],
            "limit": weekly_limit,
            "used_percent": round(weekly_used_pct, 1),
            "reset_days": days_until_weekly_reset
        },
        "daily": {
            "requests": _ollama_usage["daily_requests"]
        },
        "models_used": _ollama_usage["models_used"],
        "recent_requests": _ollama_usage["request_history"][-10:],
        "subscription": "Pro"
    }


@router.post("/api/ollama-proxy/register")
async def register_http_proxy(data: dict):
    """Register an HTTP-based Ollama proxy"""
    session_id = data.get("session_id")
    ollama_status = data.get("ollama_status", {})
    
    _http_proxy_sessions[session_id] = {
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        "ollama_status": ollama_status
    }
    
    print(f"HTTP Ollama proxy registered: {session_id}, models: {ollama_status.get('models', [])}")
    return {"success": True, "message": "Registered"}


@router.post("/api/ollama-proxy/heartbeat")
async def http_proxy_heartbeat(data: dict):
    """Heartbeat from HTTP proxy"""
    session_id = data.get("session_id")
    ollama_status = data.get("ollama_status", {})
    
    if session_id not in _http_proxy_sessions:
        _http_proxy_sessions[session_id] = {
            "ollama_status": ollama_status,
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "registered_at": datetime.now(timezone.utc).isoformat()
        }
        print(f"HTTP Ollama proxy auto-registered via heartbeat: {session_id}")
    else:
        _http_proxy_sessions[session_id]["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        _http_proxy_sessions[session_id]["ollama_status"] = ollama_status
    
    return {"success": True}


@router.get("/api/ollama-proxy/poll")
async def poll_http_proxy(session_id: str):
    """Poll for pending requests (long-poll style)"""
    if session_id not in _http_proxy_sessions:
        return {"requests": [], "error": "Not registered"}
    
    pending = []
    for req_id, req_data in list(_http_proxy_requests.items()):
        if not req_data.get("assigned"):
            req_data["assigned"] = session_id
            pending.append({"request_id": req_id, "request": req_data.get("request")})
    
    return {"requests": pending}


@router.post("/api/ollama-proxy/response")
async def submit_http_proxy_response(data: dict):
    """Submit response from HTTP proxy"""
    request_id = data.get("request_id")
    result = data.get("result", {})
    
    if request_id in _http_proxy_requests:
        _http_proxy_responses[request_id] = result
        if "future" in _http_proxy_requests[request_id]:
            future = _http_proxy_requests[request_id]["future"]
            if not future.done():
                future.set_result(result)
    
    return {"success": True}


@router.post("/api/ollama-proxy/chat")
async def ollama_proxy_chat(data: dict):
    """
    Direct chat endpoint for services to call Ollama via HTTP proxy.
    This is the main entry point for LLM services to use local Ollama.
    """
    model = data.get("model", os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud"))
    messages = data.get("messages", [])
    options = data.get("options", {})
    
    if not messages:
        return {"success": False, "error": "No messages provided"}
    
    if not is_http_ollama_proxy_connected():
        return {"success": False, "error": "No Ollama proxy connected"}
    
    result = await call_ollama_via_http_proxy(model, messages, options)
    
    if result.get("success", True) and "error" not in result:
        return {"success": True, "response": result}
    else:
        return {"success": False, "error": result.get("error", "Unknown error"), "details": result}
