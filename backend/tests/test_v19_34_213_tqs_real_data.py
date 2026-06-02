"""
v19.34.213 — TQS un-flooring + tape scale fix.

Validates:
 1. tape_score is normalized at emission from raw -1..+1 -> canonical 0..10.
 2. The Setup pillar uses the alert's win_rate / EV overrides instead of the
    learning_loop 0.5/0.0 default (the floor that pinned the pillar at ~43).
 3. With real win_rate + EV + a confirmed 0-10 tape, the Setup pillar score
    lifts materially above the all-default baseline.
"""
import asyncio
import pytest

from services.tqs.setup_quality import get_setup_quality_service


def _tape_emit(raw):
    """Mirror the scanner emission transform in enhanced_scanner.py:3218."""
    return round((raw + 1.0) * 5.0, 2)


def test_tape_scale_mapping():
    # -1 -> 0, 0 -> 5, +1 -> 10, +0.2 (tight-spread-only) -> 6.0
    assert _tape_emit(-1.0) == 0.0
    assert _tape_emit(0.0) == 5.0
    assert _tape_emit(1.0) == 10.0
    assert _tape_emit(0.2) == 6.0
    # max bullish must now beat neutral (the pre-fix inversion is gone)
    assert _tape_emit(0.5) > _tape_emit(0.0)


def test_setup_pillar_uses_overrides_not_default():
    svc = get_setup_quality_service()
    svc.set_services(learning_loop=None, scanner=None)

    async def run():
        # Baseline: no overrides, no learning loop -> win_rate defaults to 0.5,
        # EV to 0.0 (the empirically-confirmed floor).
        base = await svc.calculate_score(
            setup_type="bull_flag", symbol="TEST",
            tape_score=_tape_emit(0.2), tape_confirmation=False,
            smb_grade="B", smb_5var_score=25, risk_reward=2.0,
        )
        # With a real win_rate + EV threaded in from the alert.
        rich = await svc.calculate_score(
            setup_type="bull_flag", symbol="TEST",
            tape_score=_tape_emit(0.6), tape_confirmation=True,
            smb_grade="B", smb_5var_score=25, risk_reward=2.0,
            win_rate_override=0.66, ev_r_override=0.8,
        )
        return base, rich

    base, rich = asyncio.get_event_loop().run_until_complete(run())

    # Override must be reflected in the raw value (not the 0.5 default).
    assert abs(rich.win_rate - 0.66) < 1e-9
    assert abs(rich.expected_value_r - 0.8) < 1e-9
    assert abs(base.win_rate - 0.5) < 1e-9          # baseline still defaults
    # win-rate sub-score must rise above the 50 default for a 66% rate.
    assert rich.win_rate_score > base.win_rate_score
    # overall setup pillar must lift materially (un-flooring).
    assert rich.score > base.score + 5


def test_tape_component_not_pinned_after_fix():
    """A confirmed, strongly-bullish 0-10 tape must produce a high tape pillar,
    not the <=30 the raw -1..1 scale produced."""
    svc = get_setup_quality_service()
    svc.set_services(learning_loop=None, scanner=None)

    async def run():
        return await svc.calculate_score(
            setup_type="orb", symbol="TEST",
            tape_score=_tape_emit(0.6), tape_confirmation=True,
            smb_grade="B", smb_5var_score=25, risk_reward=2.0,
            win_rate_override=0.6, ev_r_override=0.5,
        )

    res = asyncio.get_event_loop().run_until_complete(run())
    assert res.tape_score >= 60  # confirmed tape clamps to >=80 internally


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
