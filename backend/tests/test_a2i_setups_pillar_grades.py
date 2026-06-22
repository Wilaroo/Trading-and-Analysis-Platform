"""v19.34.282 (A2i) — /api/sentcom/setups (get_setups_watching Source 1) must
surface tqs_pillar_grades / tqs_grade / tqs_score from the live alert objects so
the Provenance Ring renders on EVAL scanner cards."""
import asyncio
import types

import services.enhanced_scanner as es
import services.sentcom_service as ss


class _Prio:
    value = "high"


class _FakeAlert:
    symbol = "MAR"
    setup_type = "day_2_continuation"
    strategy_name = None
    trigger_price = 100.0
    current_price = 101.0
    stop_loss = 98.0
    target = 110.0
    risk_reward = 2.0
    tqs_score = 57
    trade_grade = "C"
    tqs_grade = "C"
    trigger_probability = 0.57
    headline = "MAR day 2 continuation"
    id = "alert-mar-1"
    created_at = None
    priority = _Prio()
    tqs_pillar_grades = {
        "setup": "C", "technical": "B", "fundamental": "C",
        "context": "B", "execution": "C",
    }


class _FakeScanner:
    def get_live_alerts(self, *a, **k):
        return [_FakeAlert()]
    # intentionally no get_recent_alerts -> Source 4 skipped by hasattr guard


def test_setups_watching_emits_pillar_grades(monkeypatch):
    monkeypatch.setattr(es, "get_enhanced_scanner", lambda: _FakeScanner())

    svc = ss.SentComService.__new__(ss.SentComService)  # skip __init__ (DB)
    svc._get_trading_bot = lambda: None

    async def _no_pos():
        return []
    svc.get_our_positions = _no_pos

    setups = asyncio.run(svc.get_setups_watching())
    mar = next(s for s in setups if s["symbol"] == "MAR")
    assert mar["tqs_pillar_grades"] == _FakeAlert.tqs_pillar_grades
    assert mar["tqs_grade"] == "C"
    assert mar["tqs_score"] == 57


if __name__ == "__main__":
    class _MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)
    test_setups_watching_emits_pillar_grades(_MP())
    print("PASS — get_setups_watching Source 1 emits tqs_pillar_grades/tqs_grade/tqs_score")
