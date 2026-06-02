"""
test_v19_34_217_execution_pillar_live_state.py

Validates the v19.34.217 Execution-pillar live-state fallback:
  - _derive_live_execution_state computes recent_win_rate + trailing
    consecutive-losses + tilt severity from a newest-first outcome list.
  - calculate_score uses the live fallback (de-pinning the 48.80 constant)
    when the persisted trader profile is empty, and yields a DIFFERENT score
    for a hot book vs a cold/tilted book.
"""
import asyncio
import importlib

eq = importlib.import_module("services.tqs.execution_quality")


class _Exec:
    def __init__(self, rc=0.0):
        self.r_capture_percent = rc
        self.execution_quality_score = 0.6


class _Outcome:
    def __init__(self, outcome, rc=0.0):
        self.outcome = outcome
        self.execution = _Exec(rc)


# ── pure derivation ───────────────────────────────────────────────────────
def test_derive_win_rate_and_streak():
    # newest-first: 3 trailing losses, then wins
    outs = [_Outcome("lost"), _Outcome("lost"), _Outcome("lost"),
            _Outcome("won"), _Outcome("won")]
    s = eq._derive_live_execution_state(outs)
    assert s["sample"] == 5
    assert s["recent_win_rate"] == 0.4   # 2 wins / 5
    assert s["consecutive_losses"] == 3
    assert s["tilt_severity"] == "moderate"
    assert s["is_tilted"] is True


def test_derive_no_streak_when_newest_is_win():
    outs = [_Outcome("won"), _Outcome("lost"), _Outcome("lost")]
    s = eq._derive_live_execution_state(outs)
    assert s["consecutive_losses"] == 0
    assert s["is_tilted"] is False
    assert s["tilt_severity"] == "none"


def test_derive_empty_is_neutral():
    s = eq._derive_live_execution_state([])
    assert s["sample"] == 0
    assert s["recent_win_rate"] == 0.5
    assert s["consecutive_losses"] == 0


def test_derive_avg_r_capture():
    outs = [_Outcome("won", rc=80.0), _Outcome("won", rc=60.0), _Outcome("lost")]
    s = eq._derive_live_execution_state(outs)
    assert s["avg_r_capture_pct"] == 70.0


# ── fake learning loop (no persisted profile → triggers live fallback) ────
class _EmptyProfile:
    total_trades = 0


class _FakeLoop:
    def __init__(self, outcomes):
        self._o = outcomes

    async def get_trader_profile(self):
        return _EmptyProfile()

    async def get_recent_outcomes(self, limit=20, setup_type=None):
        return self._o[:limit]


def _score(outcomes):
    svc = eq.ExecutionQualityService()
    svc.set_services(learning_loop=_FakeLoop(outcomes))
    return asyncio.get_event_loop().run_until_complete(
        svc.calculate_score("AAA", "squeeze")
    )


def test_pillar_depins_hot_vs_cold():
    hot = [_Outcome("won")] * 9 + [_Outcome("lost")]      # 90% win, no streak
    cold = [_Outcome("lost")] * 5 + [_Outcome("won")] * 2  # 5-loss streak, 29% win
    hot_score = _score(hot)
    cold_score = _score(cold)
    # The pillar must now DISCRIMINATE (was a flat 48.80 constant pre-v217).
    assert hot_score.score != cold_score.score
    assert hot_score.score > cold_score.score
    assert cold_score.consecutive_losses == 5
    assert cold_score.tilt_severity == "severe"
    assert round(hot_score.recent_win_rate, 2) == 0.90
