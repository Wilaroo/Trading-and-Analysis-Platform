"""
v19.20 — GamePlan narrative card tests.

Covers the per-symbol trader-style briefing card introduced alongside the
Phase-1 feed-noise fixes. The narrative service must:

  1. Render deterministic bullets from stock_in_play data even when the
     technical snapshot is unavailable (pre-market / weekends / fork env).
  2. Surface snapshot-derived live levels when the snapshot IS available.
  3. Cache results per (symbol, gameplan_date) with a TTL so the morning
     briefing UI doesn't hammer the LLM on every refresh.
  4. Extract $TICKER references from the narrative for frontend chip
     rendering.
"""
import os
import sys
import asyncio
import pytest
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.gameplan_narrative_service import GamePlanNarrativeService  # noqa: E402


# --------------------------------------------------------------------------- #
# 1. Bullets render without a snapshot
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_bullets_render_without_snapshot():
    svc = GamePlanNarrativeService(technical_service=None)
    stock = {
        "symbol": "KO", "setup_type": "squeeze", "direction": "long",
        "key_levels": {"entry": 65.20, "stop": 64.80, "target_1": 66.00, "target_2": 66.50},
    }
    card = await svc.build_card(
        symbol="KO", stock_in_play=stock, gameplan_date="2026-05-01",
        use_llm=False,
    )
    assert card["symbol"] == "KO"
    assert card["direction"] == "long"
    # 4 bullets: setup, plan, trigger, invalidate. No context line (no snapshot).
    assert len(card["bullets"]) == 4
    joined = " ".join(card["bullets"])
    assert "Squeeze" in joined or "squeeze" in joined.lower()
    assert "$65.20" in joined  # entry
    assert "$64.80" in joined  # stop
    assert "$66.00" in joined  # T1
    assert card["llm_used"] is False
    # referenced_symbols always includes the primary symbol.
    assert card["referenced_symbols"] == ["KO"]


# --------------------------------------------------------------------------- #
# 2. Snapshot-derived levels flow into bullets
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_bullets_enrich_with_live_snapshot():
    class _FakeTech:
        async def get_technical_snapshot(self, symbol: str):
            return SimpleNamespace(
                current_price=65.35, open=65.10, high=65.50, low=64.90,
                prev_close=64.95, vwap=65.15, ema_9=65.20,
                high_of_day=65.50, low_of_day=64.90,
                or_high=65.45, or_low=65.05,
                support=64.80, resistance=65.70, atr=0.42, rsi_14=58,
                above_vwap=True, gap_pct=0.23,
            )

    svc = GamePlanNarrativeService(technical_service=_FakeTech())
    stock = {
        "symbol": "KO", "setup_type": "vwap_bounce", "direction": "long",
        "key_levels": {"entry": 65.15, "stop": 64.85, "target_1": 65.80},
    }
    card = await svc.build_card(
        symbol="KO", stock_in_play=stock, gameplan_date="2026-05-01",
        use_llm=False,
    )
    # Context line (with VWAP / price / OR / HOD / LOD) should appear.
    ctx_line = next((b for b in card["bullets"] if b.startswith("Context:")), None)
    assert ctx_line is not None, f"No context bullet in: {card['bullets']}"
    assert "VWAP $65.15" in ctx_line
    assert "OR $65.05–$65.45" in ctx_line
    assert "HOD $65.50" in ctx_line
    # levels dict includes the live snapshot fields
    assert card["levels"]["vwap"] == 65.15
    assert card["levels"]["or_high"] == 65.45
    assert card["levels"]["above_vwap"] is True


# --------------------------------------------------------------------------- #
# 3. Cache hits second call
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cache_returns_same_payload_second_call():
    svc = GamePlanNarrativeService(technical_service=None)
    stock = {"symbol": "WULF", "setup_type": "orb_long", "direction": "long",
             "key_levels": {"entry": 6.0, "stop": 5.9, "target_1": 6.3}}
    card1 = await svc.build_card(
        symbol="WULF", stock_in_play=stock, gameplan_date="2026-05-01",
        use_llm=False,
    )
    card2 = await svc.build_card(
        symbol="WULF", stock_in_play=stock, gameplan_date="2026-05-01",
        use_llm=False,
    )
    # Same cache entry → same generated_at timestamp.
    assert card1["generated_at"] == card2["generated_at"]


# --------------------------------------------------------------------------- #
# 4. $TICKER extraction
# --------------------------------------------------------------------------- #
def test_ticker_extraction_preserves_order_and_dedupes():
    svc = GamePlanNarrativeService()
    text = "Watching $NVDA leadership; if $SPY holds VWAP, $NVDA could extend. $SPY pivot."
    refs = svc._extract_referenced_symbols(text, primary="NVDA")
    assert refs[0] == "NVDA"           # primary first
    assert "SPY" in refs
    # No duplicates (NVDA mentioned twice in text).
    assert len([r for r in refs if r == "NVDA"]) == 1


# --------------------------------------------------------------------------- #
# 5. Bouncy Ball & The 3:30 trade get their setup descriptions
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_playbook_setups_have_descriptions():
    svc = GamePlanNarrativeService(technical_service=None)
    for setup in ["bouncy_ball", "the_3_30_trade", "vwap_continuation",
                  "premarket_high_break"]:
        stock = {"symbol": "AAPL", "setup_type": setup, "direction": "long",
                 "key_levels": {"entry": 200.0, "stop": 198.5, "target_1": 203.0}}
        card = await svc.build_card(
            symbol="AAPL", stock_in_play=stock,
            gameplan_date=f"2026-05-01-{setup}", use_llm=False,
        )
        assert card["setup_description"], f"Missing description for {setup}"


# --------------------------------------------------------------------------- #
# 6. LLM is offline → narrative blank, llm_used False, bullets still work
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_llm_offline_falls_back_to_bullets():
    """In this sandbox the Ollama HTTP proxy isn't connected; narrative must
    degrade gracefully to empty string + llm_used=False."""
    svc = GamePlanNarrativeService(technical_service=None)
    stock = {"symbol": "TSLA", "setup_type": "squeeze", "direction": "long",
             "key_levels": {"entry": 250.0, "stop": 247.5, "target_1": 255.0}}
    card = await svc.build_card(
        symbol="TSLA", stock_in_play=stock, gameplan_date="2026-05-01",
        use_llm=True,
    )
    assert card["llm_used"] is False
    assert card["narrative"] == ""
    assert len(card["bullets"]) >= 3  # still have deterministic content
