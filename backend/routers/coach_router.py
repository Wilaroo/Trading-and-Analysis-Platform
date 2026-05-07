"""v19.34.41 — Proactive Coach REST router.

Single endpoint that surfaces the latest coachable-state suggestions
for the operator UI / chat AI to render.
"""
from fastapi import APIRouter

from services.proactive_coach_service import get_proactive_coach

router = APIRouter(prefix="/api/coach", tags=["coach"])


@router.get("/proactive-suggestions")
async def proactive_suggestions():
    """Returns active suggestions (one per coachable state per open trade).

    Shape:
    {
      "success": true,
      "count": 2,
      "last_scan_at": 1714086421.32,
      "suggestions": [
        {
          "id": "TID-1::move_stop_to_breakeven",
          "trade_id": "TID-1",
          "symbol": "DDOG",
          "suggestion_type": "move_stop_to_breakeven",
          "severity": "suggest",
          "headline": "DDOG up 1.2R — move stop to breakeven?",
          "rationale": "Position is 1.2R in profit. Moving stop from ...",
          "proposed_action": {
            "endpoint": "/api/trading-bot/adjust-trade",
            "payload": {
              "trade_id": "TID-1",
              "new_stop": 200.00,
              "reason": "coach_breakeven_1.2R"
            }
          },
          "created_at": 1714086421.32
        }
      ]
    }
    """
    coach = get_proactive_coach()
    suggestions = coach.all()
    return {
        "success": True,
        "count": len(suggestions),
        "last_scan_at": coach._last_scan_at,
        "suggestions": suggestions,
    }
