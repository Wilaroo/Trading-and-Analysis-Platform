"""
v19.34.194 — volatility-floor + cash-equivalent blocklist gate.

Stops ultra-low-volatility tickers (e.g. $BIL and other T-bill / ultra-short
ETFs) from becoming trades. They clear the ADV liquidity floor but have ~0
daily range, so detectors fire on noise and the R:R ladder produces absurd
targets. Two env-tunable hard gates in OpportunityEvaluator.evaluate_opportunity
(both fail-open):
  1. CASH_EQUIVALENT_BLOCKLIST  → reason_code "cash_equivalent_blocklist"
  2. MIN_TRADE_ATR_PCT (daily ATR% floor, fraction) → "atr_floor_too_low"

These tests confirm the gate blocks junk, passes legit movers (incl. index
ETFs that sit just above the floor), and never raises.
"""
import asyncio
import mongomock
import pytest

from services.opportunity_evaluator import OpportunityEvaluator


class _FakeBot:
    def __init__(self, db):
        self._db = db
        self.rejections = []

    def record_rejection(self, **kwargs):
        self.rejections.append(kwargs)


@pytest.fixture(autouse=True)
def _pass_f_gate(monkeypatch):
    """Force the upstream F-gate to pass so we isolate the v194 gate."""
    class _Grader:
        def get_grade_warning(self, setup_type):
            return None
    monkeypatch.setattr(
        "services.setup_grading_service.get_setup_grading_service",
        lambda: _Grader(), raising=False,
    )


def _db():
    return mongomock.MongoClient().db


def _run(alert, bot):
    return asyncio.run(OpportunityEvaluator().evaluate_opportunity(alert, bot))


def _reasons(bot):
    return [r.get("reason_code") for r in bot.rejections]


# ── 1. blocklist symbol ($BIL) is rejected ────────────────────────────────
def test_cash_equivalent_blocklist_rejects_bil():
    bot = _FakeBot(_db())
    alert = {"symbol": "BIL", "setup_type": "vwap_reclaim_long",
             "direction": "long", "price": 91.5, "atr": 0.05}
    out = _run(alert, bot)
    assert out is None
    assert "cash_equivalent_blocklist" in _reasons(bot)


# ── 2. low daily ATR% (from alert atr/price) is rejected ──────────────────
def test_atr_floor_rejects_low_vol_from_alert():
    bot = _FakeBot(_db())
    # atr/price = 0.10/100 = 0.001 = 0.1% < 0.3% floor
    alert = {"symbol": "QUIET", "setup_type": "vwap_reclaim_long",
             "direction": "long", "price": 100.0, "atr": 0.10}
    out = _run(alert, bot)
    assert out is None
    assert "atr_floor_too_low" in _reasons(bot)


# ── 3. low ATR% sourced from symbol_adv_cache fallback ────────────────────
def test_atr_floor_uses_adv_cache_fallback():
    db = _db()
    db["symbol_adv_cache"].insert_one({"symbol": "DEADV", "atr_pct": 0.0008})
    bot = _FakeBot(db)
    alert = {"symbol": "DEADV", "setup_type": "vwap_reclaim_long",
             "direction": "long"}  # no atr/price in alert → cache fallback
    out = _run(alert, bot)
    assert out is None
    assert "atr_floor_too_low" in _reasons(bot)


# ── 4. healthy-vol non-blocklist symbol is NOT rejected by v194 ───────────
def test_healthy_vol_not_blocked_by_v194():
    db = _db()
    db["symbol_adv_cache"].insert_one({"symbol": "AMD", "atr_pct": 0.03})
    bot = _FakeBot(db)
    # atr/price = 2.0/160 = 1.25% — well above the 0.3% floor.
    alert = {"symbol": "AMD", "setup_type": "vwap_reclaim_long",
             "direction": "long", "price": 160.0, "atr": 2.0}
    _run(alert, bot)  # may be rejected later for other reasons — that's fine
    # Critically: NOT rejected by either v194 reason.
    assert "atr_floor_too_low" not in _reasons(bot)
    assert "cash_equivalent_blocklist" not in _reasons(bot)


# ── 5. index ETF just above the floor (SPY ~0.7%) passes the gate ─────────
def test_index_etf_above_floor_passes_gate():
    db = _db()
    db["symbol_adv_cache"].insert_one({"symbol": "SPY", "atr_pct": 0.007})
    bot = _FakeBot(db)
    alert = {"symbol": "SPY", "setup_type": "vwap_reclaim_long",
             "direction": "long"}
    _run(alert, bot)
    assert "atr_floor_too_low" not in _reasons(bot)
    assert "cash_equivalent_blocklist" not in _reasons(bot)


# ── 6. no measurement available → fail-open (no v194 rejection) ───────────
def test_no_measurement_fails_open():
    bot = _FakeBot(_db())  # empty cache, no atr/price in alert
    alert = {"symbol": "UNKNOWNXYZ", "setup_type": "vwap_reclaim_long",
             "direction": "long"}
    _run(alert, bot)
    assert "atr_floor_too_low" not in _reasons(bot)
