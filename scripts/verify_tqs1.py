#!/usr/bin/env python3
"""verify_tqs1.py — prove the AI-model sub-score is HONEST now (READ-ONLY).
Run from repo root:  .venv/bin/python verify_tqs1.py
Exercises the Context pillar directly (ai_model sub-score depends ONLY on the
ai_model_* params the enrich passes — no services/DB needed for it).
"""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
from services.tqs.context_quality import get_context_quality_service

async def main():
    svc = get_context_quality_service()
    # POST-PATCH: an absent AI signal is now passed as None/None/None
    r_new = await svc.calculate_score("AAPL", "long",
        ai_model_direction=None, ai_model_confidence=None, ai_model_agrees=None)
    # PRE-PATCH: the LiveAlert dataclass defaults that USED to be passed
    r_old = await svc.calculate_score("AAPL", "long",
        ai_model_direction="", ai_model_confidence=0.0, ai_model_agrees=False)
    # A real, confirming forecast must still score 90 (unchanged)
    r_real = await svc.calculate_score("AAPL", "long",
        ai_model_direction="up", ai_model_confidence=0.66, ai_model_agrees=True)
    print(f"  absent AI (post-patch None,None,None) -> ai_model = {r_new.ai_score}   (HONEST: expect 50)")
    print(f"  old defaults  ('', 0.0, False)        -> ai_model = {r_old.ai_score}   (the OLD lie: 35)")
    print(f"  real confirm  ('up', 0.66, True)      -> ai_model = {r_real.ai_score}   (unchanged: expect 90)")
    ok = (r_new.ai_score == 50 and r_old.ai_score == 35 and r_real.ai_score == 90)
    print("\n  ✅ PASS — absent now scores honest 50" if ok else "\n  ❌ unexpected values")

asyncio.run(main())
