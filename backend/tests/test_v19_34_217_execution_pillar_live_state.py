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


class _TiltState:
    is_tilted = False
    tilt_severity = "none"
    consecutive_losses = 0


class _PopulatedBrokenProfile:
    """Mirrors the live DGX bug: profile HAS trades (in-memory mutated) but the
    win-rate aggregation came out 0 and the tilt counter reset — so the pillar
    must STILL override recent_win_rate + consecutive_losses from the live tape."""
    total_trades = 42
    overall_win_rate = 0.0
    avg_entry_slippage_percent = 0.0
    tends_to_chase = False
    avg_r_capture_percent = 70.0
    tends_to_exit_early = False
    trades_today = 0
    pnl_today = 0.0
    current_tilt_state = _TiltState()


class _FakeLoop:
    def __init__(self, outcomes, profile=None):
        self._o = outcomes
        self._profile = profile or _EmptyProfile()

    async def get_trader_profile(self):
        return self._profile

    async def get_recent_outcomes(self, limit=20, setup_type=None):
        return self._o[:limit]


def _score(outcomes, profile=None):
    svc = eq.ExecutionQualityService()
    svc.set_services(learning_loop=_FakeLoop(outcomes, profile))
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


def test_live_override_when_profile_has_data_but_broken():
    # v19.34.218 — profile HAS trades but overall_win_rate=0 / consec=0 (DGX bug).
    # The live tape (5-loss streak, 29% win) must STILL override the profile.
    cold = [_Outcome("lost")] * 5 + [_Outcome("won")] * 2
    r = _score(cold, profile=_PopulatedBrokenProfile())
    assert r.consecutive_losses == 5          # from tape, NOT profile's 0
    assert r.tilt_severity == "severe"
    assert round(r.recent_win_rate, 2) == 0.29  # from tape, NOT profile's 0.5 default
    # and the score reflects the cold streak instead of pinning high
    assert r.score < 60
