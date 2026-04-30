"""
v19.21 — Per-setup R:R floor + verification endpoints.
"""
import os
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_global_min_rr_default_is_1_7():
    """Operator picked 1.7 globally on 2026-05-01 after the HOOD reject."""
    from services.trading_bot_service import RiskParameters
    rp = RiskParameters()
    assert rp.min_risk_reward == 1.7


def test_setup_min_rr_has_meanreversion_overrides():
    """Mean-reversion plays must default to 1.5 (bounded targets)."""
    from services.trading_bot_service import RiskParameters
    rp = RiskParameters()
    assert rp.setup_min_rr["gap_fade"] == 1.5
    assert rp.setup_min_rr["vwap_fade"] == 1.5
    assert rp.setup_min_rr["squeeze"] == 1.5
    assert rp.setup_min_rr["bouncy_ball"] == 1.5
    assert rp.setup_min_rr["mean_reversion"] == 1.5
    assert rp.setup_min_rr["rubber_band"] == 1.5


def test_setup_min_rr_keeps_breakouts_strict():
    """Trend / breakout setups must default to 2.0 (unbounded targets)."""
    from services.trading_bot_service import RiskParameters
    rp = RiskParameters()
    for s in ("breakout", "orb", "trend_continuation", "the_3_30_trade",
              "premarket_high_break", "9_ema_scalp"):
        assert rp.setup_min_rr[s] == 2.0, f"{s} should default to 2.0"


def test_effective_min_rr_resolves_overrides():
    from services.trading_bot_service import RiskParameters
    rp = RiskParameters()

    # Direct match
    assert rp.effective_min_rr("gap_fade") == 1.5
    assert rp.effective_min_rr("breakout") == 2.0

    # Long/short suffix strip
    assert rp.effective_min_rr("vwap_fade_long") == 1.5
    assert rp.effective_min_rr("orb_short") == 2.0

    # _confirmed suffix strip → resolves to enabled base
    assert rp.effective_min_rr("breakout_confirmed") == 2.0

    # Unknown setup falls back to global (1.7)
    assert rp.effective_min_rr("alien_squeeze_pop") == 1.7
    assert rp.effective_min_rr(None) == 1.7
    assert rp.effective_min_rr("") == 1.7


def test_update_risk_params_merges_setup_min_rr():
    """PUT /api/trading-bot/risk-params with `setup_min_rr` MUST merge,
    not replace, so a partial update doesn't wipe other operator entries."""
    from services.trading_bot_service import TradingBotService

    bot = TradingBotService()
    original_count = len(bot.risk_params.setup_min_rr)
    assert original_count > 5

    bot.update_risk_params(setup_min_rr={"squeeze": 1.3, "fancy_new_setup": 1.9})
    # Original entries preserved
    assert bot.risk_params.setup_min_rr["gap_fade"] == 1.5
    assert bot.risk_params.setup_min_rr["breakout"] == 2.0
    # Operator override applied
    assert bot.risk_params.setup_min_rr["squeeze"] == 1.3
    assert bot.risk_params.setup_min_rr["fancy_new_setup"] == 1.9
    # New length = original + 1 (squeeze already existed, new one added)
    assert len(bot.risk_params.setup_min_rr) == original_count + 1


def test_get_status_exposes_setup_min_rr_and_max_notional():
    """Status payload must include the new fields so the GET /risk-params
    endpoint doesn't drop them silently."""
    from services.trading_bot_service import TradingBotService
    bot = TradingBotService()
    status = bot.get_status()
    risk = status["risk_params"]
    assert "setup_min_rr" in risk
    assert "max_notional_per_trade" in risk
    assert risk["setup_min_rr"]["gap_fade"] == 1.5


def test_persistence_roundtrip_is_lossless(monkeypatch):
    """`bot_state.risk_params` save → restore must keep `setup_min_rr`."""
    from services.trading_bot_service import TradingBotService
    bot = TradingBotService()
    bot.update_risk_params(setup_min_rr={"squeeze": 1.25})
    # Simulate the persistence layer's write payload.
    risk_doc = {
        "max_risk_per_trade": bot.risk_params.max_risk_per_trade,
        "min_risk_reward": bot.risk_params.min_risk_reward,
        "setup_min_rr": dict(bot.risk_params.setup_min_rr),
    }
    # Simulate restore — operator-saved should win over code defaults.
    bot2 = TradingBotService()
    saved = risk_doc.get("setup_min_rr") or {}
    merged = dict(bot2.risk_params.setup_min_rr or {})
    for k, v in saved.items():
        merged[k] = float(v)
    bot2.risk_params.setup_min_rr = merged
    bot2.risk_params.min_risk_reward = float(risk_doc["min_risk_reward"])

    assert bot2.risk_params.setup_min_rr["squeeze"] == 1.25
    # Untouched keys still default
    assert bot2.risk_params.setup_min_rr["gap_fade"] == 1.5


def test_hood_gap_fade_wouldve_passed_at_2_05_rr():
    """The exact regression: HOOD gap_fade R:R 2.05 was rejected with the
    OLD 2.5 floor. With v19.21 per-setup override (gap_fade=1.5) it should
    pass cleanly. This asserts the gate logic, not the full evaluator."""
    from services.trading_bot_service import RiskParameters
    rp = RiskParameters()
    actual_rr = 2.05
    floor = rp.effective_min_rr("gap_fade")
    assert actual_rr >= floor, (
        f"Gap fade R:R {actual_rr} should pass the v19.21 floor {floor}. "
        f"This is the HOOD regression we shipped to fix."
    )
