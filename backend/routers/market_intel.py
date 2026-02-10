"""
Market Intelligence & Strategy Playbook Router
"""
from fastapi import APIRouter, HTTPException
from typing import Optional
from services.market_intel_service import MarketIntelService, REPORT_SCHEDULE

router = APIRouter(prefix="/api/market-intel", tags=["market-intel"])

_service: Optional[MarketIntelService] = None

def init_market_intel_router(service: MarketIntelService):
    global _service
    _service = service


@router.get("/current")
async def get_current_report():
    """Get the most relevant report for the current time of day"""
    report = _service.get_current_report()
    return {
        "report": report,
        "has_report": report is not None
    }


@router.get("/reports")
async def get_todays_reports():
    """Get all reports generated today"""
    reports = _service.get_todays_reports()
    return {
        "reports": reports,
        "count": len(reports)
    }


@router.get("/schedule")
async def get_schedule():
    """Get the report schedule with status for today"""
    status = _service.get_schedule_status()
    return {
        "schedule": status,
        "report_types": [s["type"] for s in REPORT_SCHEDULE]
    }


@router.get("/auto-trigger")
async def auto_trigger():
    """Check if a report should be auto-generated on app open.
    Returns the report type to generate, or null if current report exists."""
    from services.market_intel_service import applicable_report_type
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    from datetime import datetime

    now_et = datetime.now(ZoneInfo("America/New_York"))
    # Only auto-trigger on weekdays
    if now_et.weekday() >= 5:
        return {"should_generate": False, "reason": "weekend"}

    current_minutes = now_et.hour * 60 + now_et.minute
    target_type = applicable_report_type(current_minutes)

    # Before first report time (8:30), still offer premarket if after 6 AM
    if target_type is None and current_minutes >= 360:
        target_type = "premarket"

    if not target_type:
        return {"should_generate": False, "reason": "too_early"}

    existing = _service._get_todays_report(target_type)
    if existing:
        return {"should_generate": False, "reason": "already_exists", "current_type": target_type}

    return {"should_generate": True, "report_type": target_type}


@router.post("/generate/{report_type}")
async def generate_report(report_type: str, force: bool = False):
    """Manually trigger generation of a specific report type"""
    valid_types = [s["type"] for s in REPORT_SCHEDULE]
    if report_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid report type. Must be one of: {valid_types}")

    result = await _service.generate_report(report_type, force=force)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Generation failed"))

    return result
