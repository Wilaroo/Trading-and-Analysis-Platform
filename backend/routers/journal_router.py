"""
SMB Trading Journal Router
Exposes Playbook, DRC, and Game Plan APIs
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import os

router = APIRouter(prefix="/api/journal", tags=["Trading Journal"])

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
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "trading_app")
        client = MongoClient(mongo_url)
        db = client[db_name]
        
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
    playbooks = await playbook_svc.get_playbooks(
        setup_type=setup_type,
        trade_style=trade_style,
        market_context=market_context,
        is_active=is_active,
        limit=limit
    )
    return {"success": True, "playbooks": playbooks}

@router.get("/playbooks/summary")
async def get_playbook_summary():
    """Get summary of all playbooks including available options"""
    playbook_svc, _, _ = get_services()
    summary = await playbook_svc.get_playbook_summary()
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
    drc = await drc_svc.get_drc(today)
    if not drc:
        drc = await drc_svc.create_drc(date=today, auto_populate=True)
    return {"success": True, "drc": drc}

@router.get("/drc/date/{date}")
async def get_drc_by_date(date: str):
    """Get DRC for a specific date"""
    _, drc_svc, _ = get_services()
    drc = await drc_svc.get_drc(date)
    if not drc:
        raise HTTPException(status_code=404, detail="DRC not found for this date")
    return {"success": True, "drc": drc}

@router.get("/drc/recent")
async def get_recent_drcs(limit: int = 30):
    """Get recent DRCs"""
    _, drc_svc, _ = get_services()
    drcs = await drc_svc.get_recent_drcs(limit=limit)
    return {"success": True, "drcs": drcs}

@router.put("/drc/date/{date}")
async def update_drc(date: str, updates: DRCUpdate):
    """Update a DRC"""
    _, drc_svc, _ = get_services()
    update_dict = {k: v for k, v in updates.dict().items() if v is not None}
    drc = await drc_svc.update_drc(date, update_dict)
    if not drc:
        raise HTTPException(status_code=404, detail="DRC not found")
    return {"success": True, "drc": drc}

@router.get("/drc/stats")
async def get_drc_stats(days: int = 30):
    """Get DRC statistics"""
    _, drc_svc, _ = get_services()
    stats = await drc_svc.get_drc_stats(days=days)
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
    plan = await gameplan_svc.get_game_plan(today)
    if not plan:
        plan = await gameplan_svc.create_game_plan(date=today, auto_populate=True)
    return {"success": True, "game_plan": plan}

@router.get("/gameplan/date/{date}")
async def get_game_plan_by_date(date: str):
    """Get Game Plan for a specific date"""
    _, _, gameplan_svc = get_services()
    plan = await gameplan_svc.get_game_plan(date)
    if not plan:
        raise HTTPException(status_code=404, detail="Game Plan not found for this date")
    return {"success": True, "game_plan": plan}

@router.get("/gameplan/recent")
async def get_recent_game_plans(limit: int = 14):
    """Get recent Game Plans"""
    _, _, gameplan_svc = get_services()
    plans = await gameplan_svc.get_recent_game_plans(limit=limit)
    return {"success": True, "game_plans": plans}

@router.put("/gameplan/date/{date}")
async def update_game_plan(date: str, updates: GamePlanUpdate):
    """Update a Game Plan"""
    _, _, gameplan_svc = get_services()
    update_dict = {k: v for k, v in updates.dict().items() if v is not None}
    plan = await gameplan_svc.update_game_plan(date, update_dict)
    if not plan:
        raise HTTPException(status_code=404, detail="Game Plan not found")
    return {"success": True, "game_plan": plan}

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
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "trading_app")
        client = MongoClient(mongo_url)
        db = client[db_name]
        
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


@router.post("/playbooks/save-generated")
async def save_generated_playbook(playbook_data: dict):
    """Save an AI-generated playbook"""
    playbook_svc, _, _ = get_services()
    try:
        playbook = await playbook_svc.create_playbook(playbook_data)
        return {"success": True, "playbook": playbook}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

