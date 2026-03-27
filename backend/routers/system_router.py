"""
System Status Router - Health checks, startup status, system monitoring
Extracted from server.py for modularity.
"""
from fastapi import APIRouter
from datetime import datetime, timezone
from typing import Optional
import os

router = APIRouter(tags=["System Status"])

# Module-level service references (injected via init)
_ib_service = None
_assistant_service = None
_ollama_proxy_manager = None
_is_http_ollama_proxy_connected = None
_strategy_promotion_service = None
_simulation_engine = None
_strategy_service = None
_db = None
_get_feature_engine = None
_get_scoring_engine = None
_get_stock_service = None
_get_service_optional = None
_background_scanner = None
_LLMProvider = None


def init_system_router(
    ib_service,
    assistant_service,
    ollama_proxy_manager,
    is_http_ollama_proxy_connected,
    strategy_promotion_service,
    simulation_engine,
    strategy_service,
    db,
    get_feature_engine,
    get_scoring_engine,
    get_stock_service,
    get_service_optional,
    background_scanner,
    LLMProvider,
):
    global _ib_service, _assistant_service, _ollama_proxy_manager
    global _is_http_ollama_proxy_connected
    global _strategy_promotion_service
    global _simulation_engine, _strategy_service
    global _db, _get_feature_engine, _get_scoring_engine, _get_stock_service
    global _get_service_optional, _background_scanner, _LLMProvider

    _ib_service = ib_service
    _assistant_service = assistant_service
    _ollama_proxy_manager = ollama_proxy_manager
    _is_http_ollama_proxy_connected = is_http_ollama_proxy_connected
    _strategy_promotion_service = strategy_promotion_service
    _simulation_engine = simulation_engine
    _strategy_service = strategy_service
    _db = db
    _get_feature_engine = get_feature_engine
    _get_scoring_engine = get_scoring_engine
    _get_stock_service = get_stock_service
    _get_service_optional = get_service_optional
    _background_scanner = background_scanner
    _LLMProvider = LLMProvider


@router.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/api/startup-check")
async def startup_check():
    """
    Ultra-lightweight startup check endpoint for the StartupModal.
    Returns ALL service statuses in a SINGLE call using ONLY in-memory state.
    No heavy DB queries, no blocking operations.
    Responds in <10ms even when event loop is under heavy load.
    """
    backend_ok = True

    # Check actual WebSocket connections
    ws_connected = False
    ws_connection_count = 0
    try:
        from server import manager as ws_manager
        ws_connection_count = len(ws_manager.active_connections)
        ws_connected = ws_connection_count > 0
    except Exception:
        pass

    # Check MongoDB — use in-memory state only (no network call)
    # If backend started, DB was connected at boot. Only flag false if known disconnect.
    db_ok = True
    try:
        from server import mongo_client
        # Check if client has an active topology — purely in-memory, no I/O
        db_ok = mongo_client is not None
    except Exception:
        db_ok = True  # Fallback — if backend is up, DB was ok at startup

    ib_connected = False
    ib_data_flowing = False
    try:
        ib_status = _ib_service.get_connection_status()
        ib_connected = ib_status.get("connected", False)
        # Check if actual data is flowing (not just socket connected)
        # IB Gateway can be "connected" but farms (market data, historical) may be red
        try:
            from routers.ib import _pushed_ib_data, is_pusher_connected
            if is_pusher_connected():
                quotes = _pushed_ib_data.get("quotes", {})
                positions = _pushed_ib_data.get("positions", [])
                ib_data_flowing = len(quotes) > 0 or len(positions) > 0
        except Exception:
            pass
    except Exception:
        pass

    ollama_available = False
    ai_fallback_only = False
    try:
        if _is_http_ollama_proxy_connected():
            ollama_available = True
        elif _ollama_proxy_manager and _ollama_proxy_manager.is_connected:
            ollama_available = True
        elif _LLMProvider.OLLAMA in _assistant_service.llm_clients:
            ollama_available = True
        elif _LLMProvider.EMERGENT in _assistant_service.llm_clients and _assistant_service.llm_clients[_LLMProvider.EMERGENT].get("available"):
            ai_fallback_only = True
    except Exception:
        pass

    timeseries_available = False
    try:
        ts_ai = _get_service_optional('timeseries_ai')
        timeseries_available = ts_ai is not None
    except Exception:
        pass

    scanner_running = False
    try:
        scanner_running = getattr(_background_scanner, '_running', False)
    except Exception:
        pass

    learning_available = False
    try:
        lc = _get_service_optional('learning_connectors')
        learning_available = lc is not None
    except Exception:
        pass

    return {
        "backend": backend_ok,
        "database": db_ok,
        "websocket": ws_connected,
        "ws_connections": ws_connection_count,
        "ib": ib_connected and ib_data_flowing,
        "ib_connected": ib_connected,
        "ib_data_flowing": ib_data_flowing,
        "ollama": ollama_available,
        "ai_fallback_only": ai_fallback_only,
        "timeseries": timeseries_available,
        "scanner": scanner_running,
        "learning": learning_available,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/api/consolidated-status")
async def consolidated_status():
    """
    Consolidated status endpoint - combines multiple status checks into one call.
    Reduces frontend polling from 11+ endpoints to 1.
    """
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ai_modules": {},
        "learning": {},
        "strategy": {},
        "collector": {},
        "simulation": {}
    }

    if not _get_service_optional:
        result["error"] = "System router not initialized"
        return result

    try:
        # AI Timeseries Status
        try:
            ts_ai = _get_service_optional('timeseries_ai')
            ts_status = {
                "available": ts_ai is not None,
                "training_active": getattr(ts_ai, 'training_active', False) if ts_ai else False,
            }
            if ts_ai:
                active = ts_ai.get_active_model()
                ts_status["model_active"] = active is not None
            result["ai_modules"]["timeseries"] = ts_status
        except Exception as e:
            result["ai_modules"]["timeseries"] = {"error": str(e)}

        # AI Debate/Advisor Status
        try:
            debate = _get_service_optional('debate_agents')
            result["ai_modules"]["debate"] = {
                "available": debate is not None,
            }
        except Exception as e:
            result["ai_modules"]["debate"] = {"error": str(e)}

        # Shadow Stats
        try:
            shadow = _get_service_optional('shadow_tracker')
            if shadow:
                stats = shadow.get_summary_stats()
                result["ai_modules"]["shadow"] = {
                    "total_signals": stats.get("total_signals", 0),
                    "accurate_signals": stats.get("accurate_signals", 0),
                }
            else:
                result["ai_modules"]["shadow"] = {"available": False}
        except Exception as e:
            result["ai_modules"]["shadow"] = {"error": str(e)}

        # Learning Connectors Status
        try:
            lc = _get_service_optional('learning_connectors')
            if lc:
                result["learning"]["status"] = {
                    "connected": True,
                    "thresholds_active": getattr(lc, 'thresholds', None) is not None
                }
            else:
                result["learning"]["status"] = {"connected": False}
        except Exception as e:
            result["learning"]["status"] = {"error": str(e)}

        # Strategy Promotion
        try:
            if _strategy_promotion_service:
                phases = _strategy_promotion_service.get_phase_status()
                result["strategy"]["phases_count"] = len(phases) if phases else 0
                result["strategy"]["available"] = True
            else:
                result["strategy"]["available"] = False
        except Exception as e:
            result["strategy"] = {"error": str(e)}

        # IB Collector Stats
        try:
            collector = _get_service_optional('ib_collector')
            if collector:
                stats = collector.get_collection_stats()
                result["collector"] = {
                    "available": True,
                    "total_symbols": stats.get("total_symbols", 0),
                    "active_collection": stats.get("is_collecting", False)
                }
            else:
                result["collector"] = {"available": False}
        except Exception as e:
            result["collector"] = {"error": str(e)}

        # Simulation Jobs
        try:
            sim = _get_service_optional('simulation_engine')
            if sim:
                try:
                    jobs = await sim.get_recent_jobs(limit=5)
                    result["simulation"] = {
                        "recent_jobs": len(jobs) if jobs else 0,
                        "available": True
                    }
                except AttributeError:
                    result["simulation"] = {"available": True, "recent_jobs": 0}
            else:
                result["simulation"] = {"available": False}
        except Exception as e:
            result["simulation"] = {"error": str(e)}

    except Exception as e:
        result["error"] = str(e)

    return result


@router.get("/api/llm/status")
async def llm_status():
    """Check which LLM provider is active and show smart routing config"""
    status = {
        "primary_provider": _assistant_service.provider.value,
        "smart_routing": {
            "light": "Ollama (free) - quick chat, summaries",
            "standard": "Ollama first, GPT-4o fallback - general use",
            "deep": "GPT-4o (Emergent) - strategy analysis, trade evaluation, complex reasoning",
        },
        "providers": {}
    }

    for provider, cfg in _assistant_service.llm_clients.items():
        info = {"available": cfg.get("available", False)}
        if provider.value == "ollama":
            info["url"] = cfg.get("url", "")
            info["model"] = cfg.get("model", "")
            info["role"] = "primary (light + standard tasks)"
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{cfg['url']}/api/tags",
                        timeout=5
                    )
                info["connected"] = resp.status_code == 200
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    info["models_available"] = models
            except Exception as e:
                info["connected"] = False
                info["error"] = str(e)
        elif provider.value == "emergent":
            info["role"] = "deep tasks + fallback"
        status["providers"][provider.value] = info

    return status


@router.get("/api/system/monitor")
async def system_monitor():
    """
    Comprehensive system health monitor.
    Returns status of all backend services and integrations.
    """
    services = []

    # 1. Database (MongoDB)
    try:
        _db.command("ping")
        services.append({
            "name": "MongoDB",
            "status": "healthy",
            "icon": "database",
            "details": f"DB: {os.environ.get('DB_NAME', 'tradecommand')}"
        })
    except Exception as e:
        services.append({
            "name": "MongoDB",
            "status": "error",
            "icon": "database",
            "details": str(e)[:50]
        })

    # 2. IB Gateway Connection
    try:
        ib_status = _ib_service.get_connection_status()
        services.append({
            "name": "IB Gateway",
            "status": "healthy" if ib_status.get("connected") else "disconnected",
            "icon": "activity",
            "details": f"Port {ib_status.get('port', 4002)}" + (" - Connected" if ib_status.get("connected") else " - Not connected")
        })
    except Exception as e:
        services.append({
            "name": "IB Gateway",
            "status": "error",
            "icon": "activity",
            "details": str(e)[:50]
        })

    # 3. Strategies Service
    try:
        strategy_count = _strategy_service.get_strategy_count()
        services.append({
            "name": "Strategies",
            "status": "healthy",
            "icon": "target",
            "details": f"{strategy_count} strategies loaded"
        })
    except Exception as e:
        services.append({
            "name": "Strategies",
            "status": "error",
            "icon": "target",
            "details": str(e)[:50]
        })

    # 4. Feature Engine
    try:
        fe = _get_feature_engine()
        if fe:
            services.append({
                "name": "Feature Engine",
                "status": "healthy",
                "icon": "cpu",
                "details": "Technical indicators ready"
            })
        else:
            services.append({
                "name": "Feature Engine",
                "status": "error",
                "icon": "cpu",
                "details": "Not initialized"
            })
    except Exception as e:
        services.append({
            "name": "Feature Engine",
            "status": "error",
            "icon": "cpu",
            "details": str(e)[:50]
        })

    # 5. Scoring Engine
    try:
        se = _get_scoring_engine(_db)
        if se:
            services.append({
                "name": "Scoring Engine",
                "status": "healthy",
                "icon": "bar-chart",
                "details": "Scoring system ready"
            })
        else:
            services.append({
                "name": "Scoring Engine",
                "status": "error",
                "icon": "bar-chart",
                "details": "Not initialized"
            })
    except Exception as e:
        services.append({
            "name": "Scoring Engine",
            "status": "error",
            "icon": "bar-chart",
            "details": str(e)[:50]
        })

    # 6. AI/LLM
    try:
        llm_key = os.environ.get("EMERGENT_LLM_KEY", "")
        if llm_key:
            services.append({
                "name": "AI/LLM",
                "status": "healthy",
                "icon": "brain",
                "details": "Emergent LLM Key configured"
            })
        else:
            services.append({
                "name": "AI/LLM",
                "status": "warning",
                "icon": "brain",
                "details": "No LLM key configured"
            })
    except Exception as e:
        services.append({
            "name": "AI/LLM",
            "status": "error",
            "icon": "brain",
            "details": str(e)[:50]
        })

    # 7. Data Services (Alpaca, Finnhub, yfinance)
    try:
        stock_svc = _get_stock_service()
        data_status = await stock_svc.get_service_status()

        alpaca_info = data_status.get("alpaca", {})
        services.append({
            "name": "Alpaca",
            "status": "healthy" if alpaca_info.get("available") else "warning",
            "icon": "trending-up",
            "details": alpaca_info.get("status", "unknown")
        })

        finnhub_info = data_status.get("finnhub", {})
        services.append({
            "name": "Finnhub",
            "status": "healthy" if finnhub_info.get("available") else "warning",
            "icon": "bar-chart-2",
            "details": finnhub_info.get("status", "not_configured")
        })

        yf_info = data_status.get("yfinance", {})
        services.append({
            "name": "Yahoo Finance",
            "status": "healthy" if yf_info.get("available") else "warning",
            "icon": "globe",
            "details": yf_info.get("status", "available")
        })
    except Exception as e:
        services.append({
            "name": "Data Services",
            "status": "error",
            "icon": "trending-up",
            "details": str(e)[:50]
        })

    # Calculate overall health
    healthy_count = sum(1 for s in services if s["status"] == "healthy")
    warning_count = sum(1 for s in services if s["status"] == "warning")
    error_count = sum(1 for s in services if s["status"] == "error")
    disconnected_count = sum(1 for s in services if s["status"] == "disconnected")

    if error_count > 0:
        overall_status = "degraded"
    elif warning_count > 0 or disconnected_count > 0:
        overall_status = "partial"
    else:
        overall_status = "healthy"

    return {
        "overall_status": overall_status,
        "services": services,
        "summary": {
            "healthy": healthy_count,
            "warning": warning_count,
            "disconnected": disconnected_count,
            "error": error_count,
            "total": len(services)
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
