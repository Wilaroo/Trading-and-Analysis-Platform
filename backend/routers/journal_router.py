"""
SMB Trading Journal Router
Exposes Playbook, DRC, and Game Plan APIs
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import os
import asyncio

router = APIRouter(prefix="/api/journal", tags=["Trading Journal"])


async def _in_thread(coro):
    """Run a fake-async coroutine (sync PyMongo inside async def) in a thread
    to avoid blocking the FastAPI event loop."""
    def _run():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    return await asyncio.to_thread(_run)

# Pydantic Models for Request/Response
class IfThenStatement(BaseModel):
    condition: str = ""
    action: str = ""
    notes: str = ""

class EntryRules(BaseModel):
    trigger: str = ""
    confirmation: str = ""
    timing: str = ""
    notes: str = ""

class ExitRules(BaseModel):
    target_1: str = ""
    target_2: str = ""
    target_3: str = ""
    scaling_rules: str = ""
    trail_stop: str = ""
    notes: str = ""

class StopRules(BaseModel):
    initial_stop: str = ""
    break_even_rule: str = ""
    time_stop: str = ""
    notes: str = ""

class PlaybookCreate(BaseModel):
    name: str
    setup_type: str
    description: str = ""
    market_context: str = ""
    market_regime: str = ""
    catalyst_type: str = "Technical Setup Only"
    catalyst_description: str = ""
    trade_style: str = "M2M"
    if_then_statements: List[IfThenStatement] = []
    entry_rules: Optional[EntryRules] = None
    exit_rules: Optional[ExitRules] = None
    stop_rules: Optional[StopRules] = None
    risk_reward_target: float = 2.0
    max_risk_percent: float = 1.0
    position_sizing: str = "Standard"
    best_time_of_day: str = ""
    avoid_times: str = ""
    notes: str = ""
    tags: List[str] = []

class PlaybookTradeLog(BaseModel):
    symbol: str
    trade_date: Optional[str] = None
    entry_price: float = 0
    exit_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    shares: int = 0
    direction: str = "long"
    pnl: float = 0
    r_multiple: float = 0
    process_grade: str = "B"
    followed_rules: bool = True
    what_worked: str = ""
    what_didnt_work: str = ""
    lessons_learned: str = ""
    notes: str = ""

class DRCUpdate(BaseModel):
    overall_grade: Optional[str] = None
    day_pnl: Optional[float] = None
    day_pnl_percent: Optional[float] = None
    premarket_checklist: Optional[List[dict]] = None
    goal_for_today: Optional[str] = None
    focus_areas: Optional[List[str]] = None
    big_picture: Optional[dict] = None
    intraday_segments: Optional[List[dict]] = None
    trades_summary: Optional[dict] = None
    postmarket_checklist: Optional[List[dict]] = None
    reflections: Optional[dict] = None
    tomorrow_notes: Optional[dict] = None
    is_complete: Optional[bool] = None

class ChecklistItem(BaseModel):
    id: str
    label: str
    checked: bool = False

class ChecklistSettings(BaseModel):
    premarket: List[ChecklistItem] = []
    postmarket: List[ChecklistItem] = []

class StockInPlay(BaseModel):
    symbol: str
    catalyst: str = ""
    setup_type: str = ""
    direction: str = "long"
    if_then_statements: List[IfThenStatement] = []
    key_levels: dict = {}
    trade_plan: dict = {}
    priority: str = "secondary"
    notes: str = ""

class Day2Name(BaseModel):
    symbol: str
    reason_for_followup: str = ""
    setup_type: str = ""
    if_then_statements: List[IfThenStatement] = []
    key_levels: dict = {}
    notes: str = ""

class GamePlanUpdate(BaseModel):
    big_picture: Optional[dict] = None
    stocks_in_play: Optional[List[dict]] = None
    day_2_names: Optional[List[dict]] = None
    risk_management: Optional[dict] = None
    session_goals: Optional[dict] = None
    alerts: Optional[List[dict]] = None
    is_night_before: Optional[bool] = None
    is_complete: Optional[bool] = None

# Service instances
_playbook_service = None
_drc_service = None
_gameplan_service = None

def get_services():
    global _playbook_service, _drc_service, _gameplan_service
    
    if _playbook_service is None:
        from database import get_database
        db = get_database()
        
        from services.playbook_service import PlaybookService
        from services.drc_service import DRCService
        from services.gameplan_service import GamePlanService
        
        _playbook_service = PlaybookService(db)
        _drc_service = DRCService(db)
        _gameplan_service = GamePlanService(db)
    
    return _playbook_service, _drc_service, _gameplan_service


# ==================== PLAYBOOK ENDPOINTS ====================

@router.post("/playbooks")
async def create_playbook(data: PlaybookCreate):
    """Create a new playbook entry"""
    playbook_svc, _, _ = get_services()
    try:
        playbook = await playbook_svc.create_playbook(data.dict())
        return {"success": True, "playbook": playbook}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/playbooks")
async def get_playbooks(
    setup_type: Optional[str] = None,
    trade_style: Optional[str] = None,
    market_context: Optional[str] = None,
    is_active: bool = True,
    limit: int = 50
):
    """Get all playbooks with optional filters"""
    playbook_svc, _, _ = get_services()
    playbooks = await _in_thread(playbook_svc.get_playbooks(
        setup_type=setup_type,
        trade_style=trade_style,
        is_active=is_active,
        limit=limit
    ))
    return {"success": True, "playbooks": playbooks}

@router.get("/playbooks/summary")
async def get_playbook_summary():
    """Get summary of all playbooks including available options"""
    playbook_svc, _, _ = get_services()
    summary = await _in_thread(playbook_svc.get_playbook_summary())
    return {"success": True, **summary}

@router.get("/playbooks/best")
async def get_best_playbooks(min_trades: int = 3, limit: int = 10):
    """Get best performing playbooks"""
    playbook_svc, _, _ = get_services()
    playbooks = await playbook_svc.get_best_playbooks(min_trades=min_trades, limit=limit)
    return {"success": True, "playbooks": playbooks}

@router.get("/playbooks/{playbook_id}")
async def get_playbook(playbook_id: str):
    """Get a specific playbook by ID"""
    playbook_svc, _, _ = get_services()
    playbook = await playbook_svc.get_playbook_by_id(playbook_id)
    if not playbook:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return {"success": True, "playbook": playbook}

@router.put("/playbooks/{playbook_id}")
async def update_playbook(playbook_id: str, updates: dict):
    """Update a playbook"""
    playbook_svc, _, _ = get_services()
    playbook = await playbook_svc.update_playbook(playbook_id, updates)
    if not playbook:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return {"success": True, "playbook": playbook}

@router.delete("/playbooks/{playbook_id}")
async def delete_playbook(playbook_id: str):
    """Delete (deactivate) a playbook"""
    playbook_svc, _, _ = get_services()
    success = await playbook_svc.delete_playbook(playbook_id)
    if not success:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return {"success": True, "message": "Playbook deactivated"}

@router.post("/playbooks/{playbook_id}/trades")
async def log_playbook_trade(playbook_id: str, trade: PlaybookTradeLog):
    """Log a trade against a playbook"""
    playbook_svc, _, _ = get_services()
    try:
        result = await playbook_svc.log_playbook_trade(playbook_id, trade.dict())
        return {"success": True, "trade": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/playbooks/{playbook_id}/trades")
async def get_playbook_trades(playbook_id: str, limit: int = 50):
    """Get trades for a specific playbook"""
    playbook_svc, _, _ = get_services()
    trades = await playbook_svc.get_playbook_trades(playbook_id, limit=limit)
    return {"success": True, "trades": trades}

@router.post("/playbooks/generate-from-trade")
async def generate_playbook_from_trade(trade_data: dict):
    """AI-assisted: Generate a playbook template from trade data"""
    playbook_svc, _, _ = get_services()
    suggested = await playbook_svc.generate_playbook_from_trade(trade_data)
    return {"success": True, "suggested_playbook": suggested}


# ==================== DRC ENDPOINTS ====================

@router.post("/drc")
async def create_drc(date: Optional[str] = None, auto_populate: bool = True):
    """Create a new Daily Report Card"""
    _, drc_svc, _ = get_services()
    try:
        drc = await drc_svc.create_drc(date=date, auto_populate=auto_populate)
        return {"success": True, "drc": drc}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/drc/today")
async def get_today_drc():
    """Get or create today's DRC"""
    _, drc_svc, _ = get_services()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    drc = await _in_thread(drc_svc.get_drc(today))
    if not drc:
        drc = await _in_thread(drc_svc.create_drc(date=today, auto_populate=True))
    return {"success": True, "drc": drc}

@router.get("/drc/date/{date}")
async def get_drc_by_date(date: str):
    """Get DRC for a specific date"""
    _, drc_svc, _ = get_services()
    drc = await _in_thread(drc_svc.get_drc(date))
    if not drc:
        raise HTTPException(status_code=404, detail="DRC not found for this date")
    return {"success": True, "drc": drc}

@router.get("/drc/recent")
async def get_recent_drcs(limit: int = 30):
    """Get recent DRCs"""
    _, drc_svc, _ = get_services()
    drcs = await _in_thread(drc_svc.get_recent_drcs(limit=limit))
    return {"success": True, "drcs": drcs}

@router.put("/drc/date/{date}")
async def update_drc(date: str, updates: DRCUpdate):
    """Update a DRC"""
    _, drc_svc, _ = get_services()
    update_dict = {k: v for k, v in updates.dict().items() if v is not None}
    drc = await _in_thread(drc_svc.update_drc(date, update_dict))
    if not drc:
        raise HTTPException(status_code=404, detail="DRC not found")
    return {"success": True, "drc": drc}

@router.get("/drc/stats")
async def get_drc_stats(days: int = 30):
    """Get DRC statistics"""
    _, drc_svc, _ = get_services()
    stats = await _in_thread(drc_svc.get_drc_stats(days=days))
    return {"success": True, **stats}

@router.get("/drc/date/{date}/summary")
async def get_drc_summary(date: str):
    """AI-assisted: Get DRC summary with insights"""
    _, drc_svc, _ = get_services()
    summary = await drc_svc.generate_drc_summary(date)
    return {"success": True, **summary}

@router.get("/drc/checklist-settings")
async def get_checklist_settings():
    """Get current checklist settings"""
    _, drc_svc, _ = get_services()
    settings = await drc_svc.get_checklist_settings()
    return {"success": True, "settings": settings}

@router.put("/drc/checklist-settings")
async def update_checklist_settings(settings: ChecklistSettings):
    """Update checklist settings"""
    _, drc_svc, _ = get_services()
    result = await drc_svc.update_checklist_settings(
        premarket=[item.dict() for item in settings.premarket] if settings.premarket else None,
        postmarket=[item.dict() for item in settings.postmarket] if settings.postmarket else None
    )
    return {"success": True, "settings": result}


# ==================== GAME PLAN ENDPOINTS ====================

@router.post("/gameplan")
async def create_game_plan(date: Optional[str] = None, auto_populate: bool = True):
    """Create a new Game Plan"""
    _, _, gameplan_svc = get_services()
    try:
        plan = await gameplan_svc.create_game_plan(date=date, auto_populate=auto_populate)
        return {"success": True, "game_plan": plan}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/gameplan/today")
async def get_today_game_plan():
    """Get or create today's Game Plan"""
    _, _, gameplan_svc = get_services()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    plan = await _in_thread(gameplan_svc.get_game_plan(today))
    if not plan:
        plan = await _in_thread(gameplan_svc.create_game_plan(date=today, auto_populate=True))
    return {"success": True, "game_plan": plan}

@router.get("/gameplan/date/{date}")
async def get_game_plan_by_date(date: str):
    """Get Game Plan for a specific date"""
    _, _, gameplan_svc = get_services()
    plan = await _in_thread(gameplan_svc.get_game_plan(date))
    if not plan:
        raise HTTPException(status_code=404, detail="Game Plan not found for this date")
    return {"success": True, "game_plan": plan}

@router.get("/gameplan/recent")
async def get_recent_game_plans(limit: int = 14):
    """Get recent Game Plans"""
    _, _, gameplan_svc = get_services()
    plans = await _in_thread(gameplan_svc.get_recent_game_plans(limit=limit))
    return {"success": True, "game_plans": plans}

@router.put("/gameplan/date/{date}")
async def update_game_plan(date: str, updates: GamePlanUpdate):
    """Update a Game Plan"""
    _, _, gameplan_svc = get_services()
    update_dict = {k: v for k, v in updates.dict().items() if v is not None}
    plan = await _in_thread(gameplan_svc.update_game_plan(date, update_dict))
    if not plan:
        raise HTTPException(status_code=404, detail="Game Plan not found")
    return {"success": True, "game_plan": plan}

# 2026-05-01 v19.20 — per-stock narrative cards for the Morning Briefing.
# Fetches the gameplan row, locates the requested symbol, enriches with live
# TechnicalSnapshot levels, composes deterministic bullets, and asks Ollama
# GPT-OSS 120B for a 2-3 sentence trader narrative. Falls back to bullets-
# only when the LLM proxy is offline so the UI always renders something.
@router.get("/gameplan/narrative/{symbol}")
async def get_gameplan_narrative(symbol: str, date: Optional[str] = None, use_llm: bool = True):
    """Per-symbol trader-style briefing card for the morning briefing UI."""
    _, _, gameplan_svc = get_services()
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    plan = await _in_thread(gameplan_svc.get_game_plan(target_date))
    if not plan:
        raise HTTPException(status_code=404, detail="Game plan not found for date")

    sym_upper = (symbol or "").upper()
    stock_entry = next(
        (s for s in plan.get("stocks_in_play", []) if (s.get("symbol") or "").upper() == sym_upper),
        None,
    )
    if not stock_entry:
        # Allow narrative requests on any symbol tied to today's watchlist
        # even if the gameplan doc hasn't promoted it into stocks_in_play yet.
        stock_entry = {"symbol": sym_upper, "setup_type": "", "direction": "long"}

    from services.gameplan_narrative_service import get_gameplan_narrative_service
    service = get_gameplan_narrative_service()
    # Lazy-bind the technical service singleton so every request gets the
    # same cache-warmed TechnicalSnapshot feeder used by the scanner.
    if service._technical_service is None:
        try:
            from services.realtime_technical_service import get_realtime_technical_service
            service.set_technical_service(get_realtime_technical_service())
        except Exception:
            pass

    big = plan.get("big_picture") or {}
    card = await service.build_card(
        symbol=sym_upper,
        stock_in_play=stock_entry,
        gameplan_date=target_date,
        market_bias=plan.get("bias") or big.get("bias"),
        market_regime=big.get("market_regime"),
        use_llm=use_llm,
    )
    return {"success": True, "card": card}


@router.post("/gameplan/date/{date}/stocks")
async def add_stock_in_play(date: str, stock: StockInPlay):
    """Add a stock to the Game Plan"""
    _, _, gameplan_svc = get_services()
    result = await gameplan_svc.add_stock_in_play(date, stock.dict())
    return {"success": True, "stock": result}

@router.delete("/gameplan/date/{date}/stocks/{symbol}")
async def remove_stock_from_play(date: str, symbol: str):
    """Remove a stock from the Game Plan"""
    _, _, gameplan_svc = get_services()
    success = await gameplan_svc.remove_stock_from_play(date, symbol)
    if not success:
        raise HTTPException(status_code=404, detail="Stock not found in Game Plan")
    return {"success": True, "message": f"{symbol} removed from Game Plan"}

@router.post("/gameplan/date/{date}/day2")
async def add_day_2_name(date: str, stock: Day2Name):
    """Add a Day 2 candidate"""
    _, _, gameplan_svc = get_services()
    result = await gameplan_svc.add_day_2_name(date, stock.dict())
    return {"success": True, "day2": result}

@router.post("/gameplan/date/{date}/review")
async def mark_game_plan_reviewed(date: str):
    """Mark Game Plan as reviewed"""
    _, _, gameplan_svc = get_services()
    plan = await gameplan_svc.mark_as_reviewed(date)
    return {"success": True, "game_plan": plan}

@router.get("/gameplan/stats")
async def get_game_plan_stats(days: int = 30):
    """Get Game Plan statistics"""
    _, _, gameplan_svc = get_services()
    stats = await gameplan_svc.get_game_plan_stats(days=days)
    return {"success": True, **stats}

@router.post("/gameplan/generate")
async def generate_game_plan_from_ai(market_data: dict = {}, scanner_alerts: List[dict] = []):
    """AI-assisted: Generate a suggested Game Plan"""
    _, _, gameplan_svc = get_services()
    plan = await gameplan_svc.generate_game_plan_from_ai(market_data, scanner_alerts)
    return {"success": True, "suggested_plan": plan}


# ==================== COMBINED JOURNAL ENDPOINT ====================

@router.get("/overview")
async def get_journal_overview():
    """Get overview of all journal components"""
    playbook_svc, drc_svc, gameplan_svc = get_services()
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Get summaries
    playbook_summary = await playbook_svc.get_playbook_summary()
    drc_stats = await drc_svc.get_drc_stats(days=30)
    gameplan_stats = await gameplan_svc.get_game_plan_stats(days=30)
    
    # Get today's items
    today_drc = await drc_svc.get_drc(today)
    today_plan = await gameplan_svc.get_game_plan(today)
    
    return {
        "success": True,
        "overview": {
            "playbooks": {
                "total": playbook_summary.get("total_playbooks", 0),
                "total_trades": playbook_summary.get("total_trades", 0),
                "total_pnl": playbook_summary.get("total_pnl", 0)
            },
            "drc": {
                "total_drcs": drc_stats.get("total_drcs", 0),
                "complete_drcs": drc_stats.get("complete_drcs", 0),
                "total_pnl": drc_stats.get("total_pnl", 0),
                "today_exists": today_drc is not None,
                "today_complete": today_drc.get("is_complete", False) if today_drc else False
            },
            "gameplan": {
                "total_plans": gameplan_stats.get("total_plans", 0),
                "completion_rate": gameplan_stats.get("completion_rate", 0),
                "today_exists": today_plan is not None,
                "today_complete": today_plan.get("is_complete", False) if today_plan else False
            }
        },
        "options": {
            "setup_types": playbook_summary.get("setup_types", []),
            "market_contexts": playbook_summary.get("market_contexts", []),
            "catalyst_types": playbook_summary.get("catalyst_types", []),
            "trade_styles": playbook_summary.get("trade_styles", []),
            "process_grades": playbook_summary.get("process_grades", [])
        }
    }


# ==================== TRADERSYNC IMPORT ENDPOINTS ====================

_tradersync_service = None
_ai_journal_service = None

def get_import_services():
    global _tradersync_service, _ai_journal_service
    
    if _tradersync_service is None:
        from database import get_database
        db = get_database()
        
        from services.tradersync_import_service import TraderSyncImportService
        from services.ai_journal_generation_service import AIJournalGenerationService
        
        _tradersync_service = TraderSyncImportService(db)
        _ai_journal_service = AIJournalGenerationService(db)
    
    return _tradersync_service, _ai_journal_service


class TraderSyncImportRequest(BaseModel):
    csv_content: str
    batch_name: str = None


@router.post("/tradersync/import")
async def import_tradersync_csv(request: TraderSyncImportRequest):
    """Import trades from TraderSync CSV content"""
    tradersync_svc, _ = get_import_services()
    try:
        result = await tradersync_svc.import_csv(request.csv_content, request.batch_name)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tradersync/batches")
async def get_import_batches(limit: int = 20):
    """Get list of import batches"""
    tradersync_svc, _ = get_import_services()
    batches = await tradersync_svc.get_import_batches(limit=limit)
    return {"success": True, "batches": batches}


@router.get("/tradersync/trades")
async def get_imported_trades(
    batch_id: str = None,
    symbol: str = None,
    setup_type: str = None,
    min_pnl: float = None,
    min_r_multiple: float = None,
    limit: int = 100
):
    """Get imported trades with filters"""
    tradersync_svc, _ = get_import_services()
    trades = await tradersync_svc.get_imported_trades(
        batch_id=batch_id,
        symbol=symbol,
        setup_type=setup_type,
        min_pnl=min_pnl,
        min_r_multiple=min_r_multiple,
        limit=limit
    )
    return {"success": True, "trades": trades, "count": len(trades)}


@router.get("/tradersync/playbook-candidates")
async def get_playbook_candidates(min_r_multiple: float = 1.5, min_trades_per_setup: int = 2):
    """Get trades grouped by setup type that are candidates for playbooks"""
    tradersync_svc, _ = get_import_services()
    result = await tradersync_svc.get_trades_for_playbook_generation(
        min_r_multiple=min_r_multiple,
        min_trades_per_setup=min_trades_per_setup
    )
    return {"success": True, **result}


@router.delete("/tradersync/batch/{batch_id}")
async def delete_import_batch(batch_id: str):
    """Delete an import batch"""
    tradersync_svc, _ = get_import_services()
    result = await tradersync_svc.delete_import_batch(batch_id)
    return {"success": True, **result}


# ==================== AI GENERATION ENDPOINTS ====================

class AIPlaybookGenerateRequest(BaseModel):
    trades: List[dict] = []
    setup_type: str = None


@router.post("/ai/generate-playbook")
async def generate_playbook_from_trades(request: AIPlaybookGenerateRequest):
    """AI-assisted: Generate a playbook from a list of trades"""
    _, ai_svc = get_import_services()
    try:
        playbook = await ai_svc.generate_playbook_from_trades(request.trades, request.setup_type)
        return {"success": True, "playbook": playbook}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/generate-playbooks-from-tradersync")
async def generate_playbooks_from_tradersync(min_trades: int = 2, min_pnl: float = 0):
    """AI-assisted: Generate playbooks for all setup types from TraderSync imports"""
    _, ai_svc = get_import_services()
    try:
        result = await ai_svc.generate_multiple_playbooks_from_tradersync(
            min_trades=min_trades,
            min_pnl=min_pnl
        )
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/generate-drc/{date}")
async def generate_drc_content(date: str):
    """AI-assisted: Auto-generate DRC content for a date"""
    _, ai_svc = get_import_services()
    try:
        drc_content = await ai_svc.generate_drc_content(date)
        return {"success": True, "drc": drc_content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/auto-populate-drc")
async def auto_populate_drc(date: str = None):
    """Auto-populate today's DRC with AI-generated content"""
    _, ai_svc = get_import_services()
    _, drc_svc, _ = get_services()
    
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    try:
        # Generate AI content
        ai_content = await ai_svc.generate_drc_content(date)
        
        # Get or create DRC
        drc = await drc_svc.get_drc(date)
        if not drc:
            drc = await drc_svc.create_drc(date=date, auto_populate=False)
        
        # Update with AI content
        updates = {
            "overall_grade": ai_content.get("overall_grade", drc.get("overall_grade", "")),
            "day_pnl": ai_content.get("day_pnl", drc.get("day_pnl", 0)),
            "trades_summary": ai_content.get("trades_summary", drc.get("trades_summary", {})),
            "intraday_segments": ai_content.get("intraday_segments", drc.get("intraday_segments", [])),
            "reflections": {
                **drc.get("reflections", {}),
                **ai_content.get("reflections", {})
            },
            "auto_generated": True
        }
        
        updated_drc = await drc_svc.update_drc(date, updates)
        
        return {"success": True, "drc": updated_drc, "ai_generated": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/playbooks/generate-from-bot-strategies")
async def generate_playbooks_from_bot_strategies():
    """Auto-generate Bellafiore-style playbook starters from the bot's enabled strategies.
    
    Uses real performance data from bot_trades + strategy configs to pre-fill:
    - Setup type, direction, timeframe, risk params
    - Win rate and avg P&L from historical bot trades
    - Trade management rules (scale-out, trail, EOD close)
    - Suggested IF/THEN statements based on setup type
    """
    playbook_svc, _, _ = get_services()
    if not playbook_svc:
        raise HTTPException(status_code=503, detail="Playbook service not initialized")
    
    try:
        from database import get_database
        db = get_database()
        if db is None:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Get bot status for strategy configs
        from services.trading_bot_service import get_trading_bot_service
        bot = get_trading_bot_service()
        if not bot:
            raise HTTPException(status_code=503, detail="Trading bot not initialized")
        
        strategy_configs = bot.get_strategy_configs() if hasattr(bot, 'get_strategy_configs') else {}
        enabled_setups = bot._enabled_setups if hasattr(bot, '_enabled_setups') else []
        
        generated = []
        skipped = []
        
        for setup_type in enabled_setups:
            # Check if playbook already exists for this setup
            existing = playbook_svc.playbooks_col.find_one(
                {"setup_type": {"$regex": setup_type, "$options": "i"}}
            )
            if existing:
                skipped.append(setup_type)
                continue
            
            config = strategy_configs.get(setup_type, {})
            timeframe = config.get("timeframe", "scalp")
            trail_pct = config.get("trail_pct", 0.01)
            scale_out = config.get("scale_out_pcts", [0.5, 0.3, 0.2])
            close_eod = config.get("close_at_eod", True)
            
            # Get real performance stats from bot_trades
            closed_trades = list(db["bot_trades"].find(
                {"setup_type": setup_type, "status": "closed"},
                {"_id": 0, "realized_pnl": 1, "pnl_percent": 1, "direction": 1,
                 "fill_price": 1, "close_price": 1, "shares": 1,
                 "market_regime": 1, "quality_grade": 1}
            ))
            
            total = len(closed_trades)
            wins = sum(1 for t in closed_trades if (t.get("realized_pnl") or 0) > 0)
            total_pnl = sum(t.get("realized_pnl") or 0 for t in closed_trades)
            win_rate = (wins / total * 100) if total > 0 else 0
            avg_pnl = (total_pnl / total) if total > 0 else 0
            
            # Determine primary direction from trades
            long_count = sum(1 for t in closed_trades if t.get("direction") == "long")
            short_count = sum(1 for t in closed_trades if t.get("direction") == "short")
            primary_direction = "long" if long_count >= short_count else "short"
            
            # Build IF/THEN statements based on setup type
            if_thens = _generate_if_thens(setup_type, primary_direction, timeframe)
            
            # Format scale-out rules
            scale_rules = " / ".join([f"{int(p*100)}%" for p in scale_out]) if scale_out else "50% / 30% / 20%"
            
            playbook_data = {
                "name": setup_type.replace("_", " ").title(),
                "setup_type": setup_type,
                "direction": primary_direction,
                "trade_style": "Scalp" if timeframe == "scalp" else "Day Trade" if timeframe == "intraday" else "Swing" if timeframe == "swing" else "Position",
                
                "bigger_picture": {
                    "market_context": "Works best in trending markets with clear direction",
                    "spy_action": f"Preferred regime: {'trending' if timeframe in ('scalp', 'intraday') else 'any'}",
                    "trade_rationale": f"{setup_type.replace('_', ' ').title()} — {timeframe} timeframe setup"
                },
                
                "intraday_fundamentals": {
                    "catalyst_type": "Technical Setup Only",
                    "why_in_play": f"Scanner-detected {setup_type.replace('_', ' ')} pattern",
                    "volume_analysis": "Requires RVOL > 0.8x average"
                },
                
                "technical_analysis": {
                    "chart_pattern": setup_type.replace("_", " ").title(),
                    "key_support_levels": [],
                    "key_resistance_levels": [],
                    "timeframe": timeframe,
                },
                
                "reading_the_tape": {
                    "tape_patterns": ["Clean price action", "Volume confirmation"],
                    "clean_or_choppy": "Requires clean tape — skip if choppy",
                    "key_tape_signals": f"Look for volume surge on {primary_direction} side"
                },
                
                "trade_management": {
                    "entry_trigger": f"Scanner alert + confidence gate GO",
                    "trail_pct": f"{trail_pct*100:.1f}%",
                    "scaling_rules": f"Scale out: {scale_rules}",
                    "close_at_eod": close_eod,
                    "max_risk": "$2,500 per trade"
                },
                
                "trade_review": {
                    "historical_performance": f"{total} trades, {win_rate:.0f}% WR, avg P&L: ${avg_pnl:.0f}",
                    "what_did_i_learn": "",
                    "how_could_i_do_better": "",
                    "what_would_i_do_differently": ""
                },
                
                "if_then_statements": if_thens,
                
                "description": f"Auto-generated from bot strategy. {total} historical trades.",
                "tags": [setup_type, timeframe, primary_direction],
                "auto_generated": True,
            }
            
            result = await playbook_svc.create_playbook(playbook_data)
            generated.append({"setup_type": setup_type, "id": result.get("id"), "trades": total, "win_rate": f"{win_rate:.0f}%"})
        
        return {
            "success": True,
            "generated": len(generated),
            "skipped": len(skipped),
            "playbooks": generated,
            "skipped_existing": skipped,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _generate_if_thens(setup_type: str, direction: str, timeframe: str) -> list:
    """Generate setup-specific IF/THEN statements (Bellafiore style)"""
    base = []
    st = setup_type.lower()
    
    if "orb" in st or "opening" in st:
        base = [
            {"condition": "IF stock breaks above/below the opening 5-min range with volume", "action": f"THEN enter {direction} with stop at opposite end of range", "notes": "Wait for the 5-min candle to CLOSE before entry"},
            {"condition": "IF breakout fails and reverses back through range", "action": "THEN exit immediately — failed ORB", "notes": "Don't hold through a failed breakout"},
            {"condition": "IF it reaches 1R", "action": "THEN scale out 50%, trail stop to breakeven", "notes": "Protect profits on the first target"},
        ]
    elif "gap" in st and "go" in st:
        base = [
            {"condition": "IF stock gaps up >2% and holds above pre-market low", "action": f"THEN enter long on first pullback to VWAP or 9EMA", "notes": "Gap must be into an uptrend (above 20 SMA)"},
            {"condition": "IF gap fills more than 50%", "action": "THEN exit — gap fill = failed thesis", "notes": "The gap should hold for this to work"},
            {"condition": "IF it makes a new high of day after entry", "action": "THEN add to position, trail stop to low of entry candle", "notes": "Strength confirmation = add size"},
        ]
    elif "gap" in st and "fade" in st:
        base = [
            {"condition": "IF stock gaps up >3% into overhead resistance, extended from 20 SMA", "action": "THEN short on first sign of weakness (failed new high, red candle)", "notes": "Requires overextension — not just any gap"},
            {"condition": "IF it makes a new high after shorting", "action": "THEN stop out — thesis invalidated", "notes": "Honor the stop on fades"},
            {"condition": "IF gap starts to fill", "action": "THEN cover 50% at VWAP, trail rest", "notes": "VWAP is first target on gap fades"},
        ]
    elif "vwap" in st and "bounce" in st:
        base = [
            {"condition": f"IF stock pulls back to VWAP and shows support (hammer, doji)", "action": f"THEN enter {direction} with stop below VWAP by 1 ATR", "notes": "VWAP must be rising (uptrend day)"},
            {"condition": "IF it breaks through VWAP and doesn't reclaim in 5 min", "action": "THEN exit — VWAP support broken", "notes": "Quick stop on VWAP failures"},
            {"condition": "IF it bounces and clears HOD", "action": "THEN hold runner, trail at 9EMA", "notes": "VWAP bounce + new high = strong trend"},
        ]
    elif "squeeze" in st:
        base = [
            {"condition": "IF Bollinger Bands tighten inside Keltner Channels (squeeze fires)", "action": f"THEN enter {direction} on first expansion candle", "notes": "Wait for the squeeze to FIRE, not just form"},
            {"condition": "IF squeeze fires opposite direction", "action": "THEN flip direction or stand aside", "notes": "Squeezes can fire either way"},
            {"condition": "IF momentum continues after entry", "action": "THEN hold for 2-3R, trail at 20 SMA", "notes": "Squeezes often produce extended moves"},
        ]
    elif "bella" in st or "fade" in st:
        base = [
            {"condition": "IF stock spikes on volume then shows distribution (lower highs)", "action": "THEN short on failed new high attempt", "notes": "Bella Fade requires clear distribution pattern"},
            {"condition": "IF it makes a new high with volume", "action": "THEN cover — thesis invalidated", "notes": "Respect the momentum"},
            {"condition": "IF it drops below VWAP", "action": "THEN cover 50%, trail rest to breakeven", "notes": "Below VWAP = fade is working"},
        ]
    else:
        # Generic IF/THEN
        base = [
            {"condition": f"IF {setup_type.replace('_', ' ')} pattern confirms", "action": f"THEN enter {direction} with defined stop", "notes": "Wait for confirmation, don't anticipate"},
            {"condition": "IF stop level is hit", "action": "THEN exit full position immediately", "notes": "No hoping — honor every stop"},
            {"condition": "IF first target reached", "action": "THEN scale out 50%, trail remainder", "notes": "Take profits at planned levels"},
        ]
    
    return base



@router.post("/playbooks/save-generated")
async def save_generated_playbook(playbook_data: dict):
    """Save an AI-generated playbook"""
    playbook_svc, _, _ = get_services()
    try:
        playbook = await playbook_svc.create_playbook(playbook_data)
        return {"success": True, "playbook": playbook}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ==================== END-OF-DAY GENERATION ENDPOINTS ====================

def get_eod_service_instance():
    """Get the singleton EOD service instance"""
    from services.eod_generation_service import get_eod_service
    
    eod_svc = get_eod_service()
    if eod_svc is None:
        from database import get_database
        db = get_database()
        eod_svc = get_eod_service(db)
    
    return eod_svc


@router.get("/eod/status")
def get_eod_status():
    """Get the status of the end-of-day auto-generation scheduler"""
    eod_svc = get_eod_service_instance()
    
    is_running = eod_svc.scheduler is not None and eod_svc.scheduler.running
    next_run_times = {}
    
    if is_running:
        for job in eod_svc.scheduler.get_jobs():
            next_run = job.next_run_time
            if next_run:
                next_run_times[job.id] = next_run.isoformat()
    
    return {
        "success": True,
        "scheduler_running": is_running,
        "scheduled_time": "4:30 PM ET (weekdays)",
        "next_runs": next_run_times,
        "timezone": "America/New_York"
    }


@router.post("/eod/trigger")
async def trigger_eod_generation(date: str = None):
    """Manually trigger end-of-day DRC and Playbook generation"""
    eod_svc = get_eod_service_instance()
    try:
        result = await eod_svc.trigger_manual_generation(date)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/eod/pending-playbooks")
async def get_pending_playbooks():
    """Get AI-generated playbooks pending review"""
    eod_svc = get_eod_service_instance()
    try:
        playbooks = await eod_svc.get_pending_playbooks()
        return {"success": True, "pending_playbooks": playbooks, "count": len(playbooks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/eod/pending-playbooks/{playbook_id}/approve")
async def approve_pending_playbook(playbook_id: str):
    """Approve a pending playbook and make it active"""
    eod_svc = get_eod_service_instance()
    try:
        result = await eod_svc.approve_pending_playbook(playbook_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/eod/pending-playbooks/{playbook_id}/reject")
async def reject_pending_playbook(playbook_id: str):
    """Reject/delete a pending playbook"""
    eod_svc = get_eod_service_instance()
    try:
        result = await eod_svc.reject_pending_playbook(playbook_id)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/eod/logs")
async def get_eod_generation_logs(days: int = 7):
    """Get recent end-of-day generation logs"""
    eod_svc = get_eod_service_instance()
    try:
        logs = await eod_svc.get_generation_logs(days=days)
        return {"success": True, "logs": logs, "count": len(logs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WEEKLY INTELLIGENCE REPORT ENDPOINTS ====================

_weekly_report_service = None

def get_weekly_report_service_instance():
    """Get the singleton weekly report service instance"""
    global _weekly_report_service
    
    if _weekly_report_service is None:
        from database import get_database
        db = get_database()
        
        from services.weekly_report_service import init_weekly_report_service
        from services.medium_learning import (
            get_calibration_service,
            get_context_performance_service,
            get_confirmation_validator_service,
            get_playbook_performance_service,
            get_edge_decay_service
        )
        
        _weekly_report_service = init_weekly_report_service(
            db=db,
            calibration_service=get_calibration_service(),
            context_performance_service=get_context_performance_service(),
            confirmation_validator_service=get_confirmation_validator_service(),
            playbook_performance_service=get_playbook_performance_service(),
            edge_decay_service=get_edge_decay_service()
        )
    
    return _weekly_report_service


class ReflectionUpdate(BaseModel):
    what_went_well: str = ""
    what_to_improve: str = ""
    key_lessons: str = ""
    goals_for_next_week: str = ""
    mood_rating: int = 3
    confidence_rating: int = 3
    notes: str = ""


@router.post("/weekly-report/generate")
async def generate_weekly_report(week_start: str = None, force: bool = False):
    """
    Generate a weekly intelligence report.
    
    - week_start: Start date of the week (Monday, YYYY-MM-DD). If None, uses current week.
    - force: If True, regenerate even if report exists.
    """
    service = get_weekly_report_service_instance()
    
    import asyncio
    
    def _generate_sync():
        import asyncio as aio
        loop = aio.new_event_loop()
        try:
            return loop.run_until_complete(service.generate_weekly_report(week_start=week_start, force=force))
        finally:
            loop.close()
    
    try:
        report = await asyncio.wait_for(
            asyncio.to_thread(_generate_sync),
            timeout=15.0
        )
        return {"success": True, "report": report.to_dict()}
    except asyncio.TimeoutError:
        return {"success": False, "error": "Report generation timed out. Try again — it may complete faster on second attempt."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weekly-report/current")
async def get_current_weekly_report():
    """Get current week's report — returns cached if available, generates in background if not"""
    import asyncio
    from datetime import datetime as dt, timezone as tz, timedelta
    
    service = get_weekly_report_service_instance()
    
    # Calculate current week boundaries
    today = dt.now(tz.utc)
    days_since_monday = today.weekday()
    start = today - timedelta(days=days_since_monday)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    wn = start.isocalendar()[1]
    year = start.year
    
    # Fast path: check for cached report first (single MongoDB read, <10ms)
    try:
        if service._weekly_reports_col is not None:
            cached = service._weekly_reports_col.find_one(
                {"year": year, "week_number": wn},
                {"_id": 0}
            )
            if cached:
                from services.weekly_report_service import WeeklyIntelligenceReport
                return {"success": True, "report": WeeklyIntelligenceReport.from_dict(cached).to_dict()}
    except Exception:
        pass
    
    # No cached report — generate in a thread so blocking PyMongo doesn't freeze event loop
    def _generate_sync():
        import asyncio as aio
        loop = aio.new_event_loop()
        try:
            return loop.run_until_complete(service.generate_weekly_report())
        finally:
            loop.close()
    
    try:
        report = await asyncio.wait_for(
            asyncio.to_thread(_generate_sync),
            timeout=12.0
        )
        return {"success": True, "report": report.to_dict()}
    except (asyncio.TimeoutError, Exception):
        # Return empty skeleton — user can click "Regenerate" later
        from services.weekly_report_service import WeeklyIntelligenceReport
        empty = WeeklyIntelligenceReport(
            id=f"wir_{year}_w{wn}",
            week_number=wn, year=year,
            week_start=start.strftime("%Y-%m-%d"),
            week_end=(start + timedelta(days=4)).strftime("%Y-%m-%d"),
            generated_at=today.isoformat(),
            last_updated=today.isoformat()
        )
        return {"success": True, "report": empty.to_dict(), "timeout": True}


@router.get("/weekly-report/stats")
def get_weekly_report_stats():
    """Get weekly report service statistics"""
    service = get_weekly_report_service_instance()
    return {"success": True, **service.get_stats()}


@router.get("/weekly-report/week/{year}/{week_number}")
async def get_weekly_report_by_week(year: int, week_number: int):
    """Get weekly report by year and week number"""
    service = get_weekly_report_service_instance()
    report = await service.get_report_by_week(year, week_number)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found for this week")
    return {"success": True, "report": report.to_dict()}


@router.get("/weekly-report/{report_id}")
async def get_weekly_report(report_id: str):
    """Get a specific weekly report by ID"""
    service = get_weekly_report_service_instance()
    report = await service.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"success": True, "report": report.to_dict()}


@router.get("/weekly-report")
async def get_recent_weekly_reports(limit: int = 12):
    """Get recent weekly reports (for archive view)"""
    service = get_weekly_report_service_instance()
    reports = await service.get_recent_reports(limit=limit)
    return {
        "success": True,
        "reports": [r.to_dict() for r in reports],
        "count": len(reports)
    }


@router.put("/weekly-report/{report_id}/reflection")
async def update_weekly_reflection(report_id: str, reflection: ReflectionUpdate):
    """Update the personal reflection section of a weekly report"""
    service = get_weekly_report_service_instance()
    report = await service.update_reflection(report_id, reflection.dict())
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"success": True, "report": report.to_dict()}


@router.post("/weekly-report/{report_id}/complete")
async def mark_weekly_report_complete(report_id: str):
    """Mark a weekly report as complete (user has reviewed and added reflection)"""
    service = get_weekly_report_service_instance()
    success = await service.mark_complete(report_id)
    if not success:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"success": True, "message": "Report marked as complete"}

