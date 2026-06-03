"""
v19.34.231 — Premarket scanner repair + TQS grading regression tests.

- _make_premarket_alert builds a SCHEMA-VALID LiveAlert (the old inline
  constructors threw on a stale schema → 0 premarket alerts ever).
- risk_reward computed from stop/target; priority mapped from score;
  time_window stamped "premarket"; trigger/win prob seeded from base rate.
- grade_calibration keeps its percentile reference RTH-pure (excludes
  premarket / closed time_windows).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.enhanced_scanner import EnhancedBackgroundScanner as EnhancedScanner, LiveAlert, AlertPriority  # noqa: E402
from services.tqs import grade_calibration as gc  # noqa: E402


class _Stub:
    pass


def _factory_stub():
    s = _Stub()
    s._market_regime = None
    s._PM_BASE_RATE = EnhancedScanner._PM_BASE_RATE
    s._premarket_priority = EnhancedScanner._premarket_priority.__get__(s, _Stub)
    s._make_premarket_alert = EnhancedScanner._make_premarket_alert.__get__(s, _Stub)
    return s


# ── factory builds a valid LiveAlert (was throwing before) ────────────────
def test_factory_constructs_valid_livealert():
    s = _factory_stub()
    a = s._make_premarket_alert(
        alert_id="pm_gap_go_AAA_0840", symbol="AAA", setup_type="gap_give_go",
        direction="long", trigger_price=10.0, current_price=10.0,
        stop=9.0, target=12.0, score=80, reasoning="gap +5%",
        gap_pct=5.0, atr_percent=2.0,
    )
    assert isinstance(a, LiveAlert)
    assert a.symbol == "AAA"
    assert a.time_window == "premarket"
    assert a.stop_loss == 9.0 and a.target == 12.0
    assert a.headline and isinstance(a.reasoning, list)


def test_factory_risk_reward_math():
    s = _factory_stub()
    a = s._make_premarket_alert(
        alert_id="x", symbol="AAA", setup_type="orb", direction="long",
        trigger_price=10.0, stop=9.0, target=12.0, score=60, reasoning="r",
    )
    # risk=1, reward=2 → rr=2.0
    assert a.risk_reward == 2.0


def test_factory_zero_risk_safe():
    s = _factory_stub()
    a = s._make_premarket_alert(
        alert_id="x", symbol="AAA", setup_type="orb", direction="long",
        trigger_price=10.0, stop=10.0, target=12.0, score=60, reasoning="r",
    )
    assert a.risk_reward == 0.0  # no divide-by-zero


def test_factory_seeds_base_rate_probability():
    s = _factory_stub()
    a = s._make_premarket_alert(
        alert_id="x", symbol="AAA", setup_type="gap_give_go", direction="long",
        trigger_price=10.0, stop=9.0, target=12.0, score=70, reasoning="r",
    )
    assert a.trigger_probability == 0.55 and a.win_probability == 0.55


@pytest.mark.parametrize("score,expected", [
    (90, AlertPriority.CRITICAL),
    (85, AlertPriority.CRITICAL),
    (80, AlertPriority.HIGH),
    (75, AlertPriority.HIGH),
    (65, AlertPriority.MEDIUM),
    (60, AlertPriority.MEDIUM),
    (50, AlertPriority.LOW),
])
def test_priority_mapping(score, expected):
    s = _factory_stub()
    assert s._premarket_priority(score) == expected


def test_factory_unknown_setup_neutral_base_rate():
    s = _factory_stub()
    a = s._make_premarket_alert(
        alert_id="x", symbol="AAA", setup_type="totally_new", direction="long",
        trigger_price=10.0, stop=9.0, target=12.0, score=60, reasoning="r",
    )
    assert a.win_probability == 0.5


# ── calibration reference stays RTH-pure ──────────────────────────────────
def test_calibration_excludes_premarket_and_closed():
    from pymongo import MongoClient
    from datetime import datetime, timezone
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    name = os.environ.get("DB_NAME", "test_database")
    # grade_calibration._get_db reads these from env (no .env load under pytest)
    os.environ["MONGO_URL"] = url
    os.environ["DB_NAME"] = name
    gc._CAL_DB = None
    gc._CAL_CLIENT = None
    db = MongoClient(url, serverSelectionTimeoutMS=2500)[name]
    db["live_alerts"].delete_many({"id": {"$regex": "^v231test_"}})
    today = datetime.now(timezone.utc).isoformat()
    docs = [
        {"id": "v231test_rth1", "created_at": today, "tqs_score": 55.0, "time_window": "morning_session"},
        {"id": "v231test_rth2", "created_at": today, "tqs_score": 60.0, "time_window": "midday"},
        {"id": "v231test_rth3", "created_at": today, "tqs_score": 58.0, "time_window": "afternoon"},
        {"id": "v231test_legacy", "created_at": today, "tqs_score": 52.0},  # no time_window → included
        {"id": "v231test_pm1", "created_at": today, "tqs_score": 80.0, "time_window": "premarket"},
        {"id": "v231test_pm2", "created_at": today, "tqs_score": 85.0, "time_window": "premarket"},
        {"id": "v231test_closed", "created_at": today, "tqs_score": 90.0, "time_window": "closed"},
    ]
    db["live_alerts"].insert_many(docs)
    try:
        gc._refresh_reference()
        # only the 3 RTH + 1 legacy should count; premarket/closed excluded
        scores = gc._cache.sorted_scores
        assert 80.0 not in scores and 85.0 not in scores and 90.0 not in scores
        assert 55.0 in scores and 52.0 in scores
    finally:
        db["live_alerts"].delete_many({"id": {"$regex": "^v231test_"}})


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
