"""
v19.34.323 (patch_v336) — SHORT-FADE eligibility gate + R-winsorization.

Forensic basis (diag_v333/v334, READ-ONLY, 120d genuine bot-own trades):
  • ~$26k EXCESS lost BEYOND the stop, ~90% SHORTS, ~88% vwap_fade_short —
    shorting strength on low-priced / illiquid names with sub-1% stops that
    any squeeze gaps straight through (WTI 2.84/2c, PRCT 26.67/4c, USO 0.03%).
  • The stop/IB-execution engines are SOUND (GTC market stops fired); the loss
    is gap slippage on a no-edge entry. Fix = never enter the danger profile.

Two changes, both fail-OPEN + env-reversible:
  1. OpportunityEvaluator short-fade entry gate (low price / tight stop %).
  2. Winsorize realized-R (±R_WINSOR_CLAMP) in EV + learning-loop edge stats
     so a single -261R artifact can't poison the meta-labeler.
"""
import asyncio
import os
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
    """Force the upstream F-gate to pass so we isolate the short-fade gate."""
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


# ── 1. low-priced short fade ($2.84 WTI-class) is blocked ─────────────────
def test_short_fade_low_price_blocked():
    bot = _FakeBot(_db())
    # atr/price = 0.30/2.84 = 10.5% → clears v194 floor; price < $5 → blocked.
    alert = {"symbol": "WTI", "setup_type": "vwap_fade_short",
             "direction": "short", "price": 2.84, "atr": 0.30,
             "stop_loss": 2.86}
    out = _run(alert, bot)
    assert out is None
    assert "short_fade_low_price" in _reasons(bot)


# ── 2. tight-stop short fade (PRCT 26.67 / 4c = 0.15%) is blocked ─────────
def test_short_fade_tight_stop_blocked():
    bot = _FakeBot(_db())
    alert = {"symbol": "PRCT", "setup_type": "vwap_fade_short",
             "direction": "short", "price": 26.67, "atr": 1.0,
             "stop_loss": 26.71}  # 0.15% stop < 1.0% floor
    out = _run(alert, bot)
    assert out is None
    assert "short_fade_stop_too_tight" in _reasons(bot)


# ── 3. observe mode logs but does NOT block ───────────────────────────────
def test_short_fade_observe_does_not_block(monkeypatch):
    monkeypatch.setenv("SHORT_FADE_GATE_POLICY", "observe")
    bot = _FakeBot(_db())
    alert = {"symbol": "WTI", "setup_type": "vwap_fade_short",
             "direction": "short", "price": 2.84, "atr": 0.30,
             "stop_loss": 2.86}
    _run(alert, bot)
    assert "short_fade_low_price" not in _reasons(bot)
    assert "short_fade_stop_too_tight" not in _reasons(bot)


# ── 4. off mode disables the gate entirely ────────────────────────────────
def test_short_fade_off_disables(monkeypatch):
    monkeypatch.setenv("SHORT_FADE_GATE_POLICY", "off")
    bot = _FakeBot(_db())
    alert = {"symbol": "WTI", "setup_type": "vwap_fade_short",
             "direction": "short", "price": 2.84, "atr": 0.30,
             "stop_loss": 2.86}
    _run(alert, bot)
    assert "short_fade_low_price" not in _reasons(bot)


# ── 5. healthy short fade (price>$5, wide stop) is NOT blocked by the gate ─
def test_healthy_short_fade_passes():
    bot = _FakeBot(_db())
    # price 50, stop 51 = 2% > 1% floor; price > $5.
    alert = {"symbol": "AMD", "setup_type": "vwap_fade_short",
             "direction": "short", "price": 50.0, "atr": 1.5,
             "stop_loss": 51.0}
    _run(alert, bot)  # may be rejected later for other reasons — that's fine
    assert "short_fade_low_price" not in _reasons(bot)
    assert "short_fade_stop_too_tight" not in _reasons(bot)


# ── 6. LONG fade is NOT touched (gate is short-only) ──────────────────────
def test_long_fade_not_blocked():
    bot = _FakeBot(_db())
    alert = {"symbol": "WTI", "setup_type": "vwap_fade_long",
             "direction": "long", "price": 2.84, "atr": 0.30,
             "stop_loss": 2.82}
    _run(alert, bot)
    assert "short_fade_low_price" not in _reasons(bot)
    assert "short_fade_stop_too_tight" not in _reasons(bot)


# ── 7. non-fade short (no keyword match) is NOT touched ───────────────────
def test_non_fade_short_not_blocked():
    bot = _FakeBot(_db())
    alert = {"symbol": "WTI", "setup_type": "hod_breakout",
             "direction": "short", "price": 2.84, "atr": 0.30,
             "stop_loss": 2.86}
    _run(alert, bot)
    assert "short_fade_low_price" not in _reasons(bot)
    assert "short_fade_stop_too_tight" not in _reasons(bot)


# ════════════════════ R-WINSORIZATION ════════════════════════════════════

def test_ev_winsorizes_blown_r_outlier(monkeypatch):
    """A -261R artifact must NOT explode avg_loss_r / EV."""
    monkeypatch.setenv("EV_CANONICAL_ROLLUP", "false")
    monkeypatch.setenv("R_WINSOR_CLAMP", "3.0")
    from services.ev_tracking_service import EVTrackingService, EVTrackingRecord
    svc = EVTrackingService(db=None)
    rec = EVTrackingRecord(setup_type="test_setup")
    rec.r_outcomes = [-261.0, -1.0, -1.0, 2.0, 2.0]
    rec.total_trades = 5
    rec.wins = 2
    svc._ev_records["test_setup"] = rec
    svc.calculate_ev("test_setup")
    # losses winsorized to [-3,-1,-1] → avg_loss_r = 5/3 ≈ 1.667 (NOT 87.7).
    assert rec.avg_loss_r < 5.0, f"avg_loss_r not winsorized: {rec.avg_loss_r}"
    assert rec.avg_win_r == pytest.approx(2.0, abs=1e-6)
    # raw outcomes preserved (not mutated).
    assert rec.r_outcomes[0] == -261.0


def test_learning_loop_bucket_winsorizes_mean_r(monkeypatch):
    """get_multiplier_aware_stats mean_r must be winsorized to ±clamp."""
    monkeypatch.setenv("R_WINSOR_CLAMP", "3.0")
    from services.learning_loop_service import LearningLoopService

    class _FakeColl:
        def __init__(self, rows):
            self._rows = rows
        def find(self, q, proj=None):
            return list(self._rows)

    rows = [
        {"realized_r_multiple": -261.0,
         "entry_context": {"multipliers": {"stop_guard": {"snapped": True}}}},
        {"realized_r_multiple": -1.0,
         "entry_context": {"multipliers": {"stop_guard": {"snapped": True}}}},
    ]
    svc = LearningLoopService.__new__(LearningLoopService)
    svc._db = {"bot_trades": _FakeColl(rows)}
    out = asyncio.run(svc.get_multiplier_aware_stats(setup_type=None, days_back=120))
    fired = out["stop_guard"]["fired"]
    assert fired is not None and fired["n"] == 2
    # winsorized: mean of [-3, -1] = -2.0 (NOT -131.0).
    assert fired["mean_r"] == pytest.approx(-2.0, abs=1e-6)
