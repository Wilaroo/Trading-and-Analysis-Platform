"""
v19.34.230 — TQS pillar de-compression regression tests.

A1: Setup EV-from-R:R when no live EV data (env-gated, reversible).
A2: Missing/uninformative SMB → neutral 50 (not punitive C/35).
B3: Execution history_score per-setup_type with sample-size shrinkage toward 60.

All behaviour is gated by TQS_SETUP_DECOMPRESS / TQS_EXEC_DECOMPRESS so the
legacy path is fully recoverable.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.tqs.setup_quality import SetupQualityService  # noqa: E402
from services.tqs import execution_quality as eq  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────── A1 — EV from R:R ────────────────────────────
@pytest.mark.parametrize("rr,expected", [
    (2.0, 47.0),   # 25 + (2-1)*22
    (3.0, 69.0),   # 25 + (3-1)*22
    (4.0, 91.0),   # 25 + (4-1)*22 = 91  (<=95 cap)
    (1.5, 36.0),   # 25 + 0.5*22
])
def test_a1_ev_from_rr_when_no_data(monkeypatch, rr, expected):
    monkeypatch.setenv("TQS_SETUP_DECOMPRESS", "1")
    svc = SetupQualityService()
    res = _run(svc.calculate_score(
        setup_type="breakout", symbol="TEST",
        risk_reward=rr, win_rate_override=None, ev_r_override=None,
    ))
    assert abs(res.ev_score - expected) < 0.5, f"RR={rr}: ev_score={res.ev_score} want {expected}"


def test_a1_legacy_pins_ev_at_30_when_flag_off(monkeypatch):
    monkeypatch.setenv("TQS_SETUP_DECOMPRESS", "0")
    svc = SetupQualityService()
    res = _run(svc.calculate_score(
        setup_type="breakout", symbol="TEST",
        risk_reward=2.0, win_rate_override=None, ev_r_override=None,
    ))
    # Legacy: ev_r=0 → 30, R:R 2.0 applies no bonus → stays 30
    assert abs(res.ev_score - 30.0) < 0.01, res.ev_score


def test_a1_real_ev_data_not_overridden(monkeypatch):
    monkeypatch.setenv("TQS_SETUP_DECOMPRESS", "1")
    svc = SetupQualityService()
    res = _run(svc.calculate_score(
        setup_type="breakout", symbol="TEST", risk_reward=2.0,
        win_rate_override=0.6, ev_r_override=1.2,  # real EV present
    ))
    # ev_r >= 1.0 → absolute mapping = 100 (decompress path skipped)
    assert res.ev_score == 100, res.ev_score


def test_a1_decompress_widens_vs_legacy(monkeypatch):
    """A high-R:R setup must score the EV pillar higher under decompress."""
    svc = SetupQualityService()
    monkeypatch.setenv("TQS_SETUP_DECOMPRESS", "0")
    legacy = _run(svc.calculate_score(setup_type="orb", symbol="T", risk_reward=3.5,
                                      win_rate_override=None, ev_r_override=None))
    monkeypatch.setenv("TQS_SETUP_DECOMPRESS", "1")
    new = _run(svc.calculate_score(setup_type="orb", symbol="T", risk_reward=3.5,
                                   win_rate_override=None, ev_r_override=None))
    assert new.ev_score > legacy.ev_score
    assert new.score > legacy.score  # overall setup pillar lifts


# ─────────────────────────── A2 — SMB neutral ────────────────────────────
def test_a2_uninformative_smb_neutral_50(monkeypatch):
    monkeypatch.setenv("TQS_SETUP_DECOMPRESS", "1")
    svc = SetupQualityService()
    res = _run(svc.calculate_score(
        setup_type="breakout", symbol="T", smb_grade="C", smb_5var_score=25,
    ))
    assert abs(res.smb_score - 50.0) < 0.01, res.smb_score


def test_a2_legacy_smb_c_is_35_when_flag_off(monkeypatch):
    monkeypatch.setenv("TQS_SETUP_DECOMPRESS", "0")
    svc = SetupQualityService()
    res = _run(svc.calculate_score(
        setup_type="breakout", symbol="T", smb_grade="C", smb_5var_score=25,
    ))
    assert abs(res.smb_score - 35.0) < 0.01, res.smb_score


def test_a2_real_grade_unchanged(monkeypatch):
    monkeypatch.setenv("TQS_SETUP_DECOMPRESS", "1")
    svc = SetupQualityService()
    res = _run(svc.calculate_score(
        setup_type="breakout", symbol="T", smb_grade="A", smb_5var_score=25,
    ))
    assert res.smb_score == 95, res.smb_score


def test_a2_weak_5var_still_penalized(monkeypatch):
    """C with a genuinely weak 5-var (<20) is NOT 'uninformative' → stays low."""
    monkeypatch.setenv("TQS_SETUP_DECOMPRESS", "1")
    svc = SetupQualityService()
    res = _run(svc.calculate_score(
        setup_type="breakout", symbol="T", smb_grade="C", smb_5var_score=10,
    ))
    # else branch (35) then 5var<20 → -15 → 20
    assert abs(res.smb_score - 20.0) < 0.01, res.smb_score


# ─────────────────────── B3 — per-setup exec history ─────────────────────
def test_b3_history_shrinks_toward_60(monkeypatch):
    monkeypatch.setenv("TQS_EXEC_DECOMPRESS", "1")
    monkeypatch.setenv("TQS_EXEC_HIST_SHRINK_K", "10")
    # fake per-setup map + neutralize the live-state reader
    monkeypatch.setattr(eq, "_setup_history_map",
                        lambda: {"breakout": {"n": 40, "score": 90.0}})
    monkeypatch.setattr(eq, "_recent_trade_outcomes", lambda limit=30: [])
    svc = eq.ExecutionQualityService()
    res = _run(svc.calculate_score(symbol="T", setup_type="breakout_long"))
    # 60 + (90-60)*(40/50) = 84
    assert abs(res.history_score - 84.0) < 0.5, res.history_score


def test_b3_small_sample_barely_moves(monkeypatch):
    monkeypatch.setenv("TQS_EXEC_DECOMPRESS", "1")
    monkeypatch.setenv("TQS_EXEC_HIST_SHRINK_K", "10")
    monkeypatch.setattr(eq, "_setup_history_map",
                        lambda: {"squeeze": {"n": 2, "score": 90.0}})
    monkeypatch.setattr(eq, "_recent_trade_outcomes", lambda limit=30: [])
    svc = eq.ExecutionQualityService()
    res = _run(svc.calculate_score(symbol="T", setup_type="squeeze"))
    # 60 + 30*(2/12) = 65
    assert abs(res.history_score - 65.0) < 0.5, res.history_score


def test_b3_flag_off_keeps_pinned_60(monkeypatch):
    monkeypatch.setenv("TQS_EXEC_DECOMPRESS", "0")
    monkeypatch.setattr(eq, "_setup_history_map",
                        lambda: {"breakout": {"n": 40, "score": 90.0}})
    monkeypatch.setattr(eq, "_recent_trade_outcomes", lambda limit=30: [])
    svc = eq.ExecutionQualityService()
    res = _run(svc.calculate_score(symbol="T", setup_type="breakout"))
    assert abs(res.history_score - 60.0) < 0.01, res.history_score


def test_b3_unknown_setup_falls_back_to_60(monkeypatch):
    monkeypatch.setenv("TQS_EXEC_DECOMPRESS", "1")
    monkeypatch.setattr(eq, "_setup_history_map",
                        lambda: {"breakout": {"n": 40, "score": 90.0}})
    monkeypatch.setattr(eq, "_recent_trade_outcomes", lambda limit=30: [])
    svc = eq.ExecutionQualityService()
    res = _run(svc.calculate_score(symbol="T", setup_type="something_unseen"))
    assert abs(res.history_score - 60.0) < 0.01, res.history_score


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
