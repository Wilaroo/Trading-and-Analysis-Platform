"""v401 — horizon-aware tape (B1) + JIT tape-confirm bias (C) sanity tests."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.tqs.setup_quality import get_setup_quality_service  # noqa: E402
from services.tape_confirm_service import get_tape_confirmation, jit_confirm_enabled  # noqa: E402


def _score(trade_style, tape_score=8.0):
    svc = get_setup_quality_service()
    return asyncio.get_event_loop().run_until_complete(
        svc.calculate_score(
            setup_type="bull_flag", symbol="TEST", trade_style=trade_style,
            tape_score=tape_score, tape_confirmation=(tape_score >= 7),
        )
    )


def test_tape_dropped_for_swing_position():
    for style in ("swing", "position"):
        r = _score(style, tape_score=9.0)
        d = r.to_dict()
        assert d["display"]["tape"]["verdict"] == "No data", f"{style}: tape should be dropped"


def test_tape_kept_for_scalp_intraday():
    for style in ("scalp", "intraday"):
        r = _score(style, tape_score=9.0)
        d = r.to_dict()
        assert d["display"]["tape"]["verdict"] != "No data", f"{style}: tape should count"


def test_jit_confirm_default_off():
    # Ships dormant — no env set means the master switch is off.
    os.environ.pop("TAPE_JIT_CONFIRM", None)
    assert jit_confirm_enabled() is False


def test_jit_no_pusher_returns_none():
    # No pusher configured in the test env → fail-open None, never raises.
    assert get_tape_confirmation("AAPL", "long") is None


if __name__ == "__main__":
    test_tape_dropped_for_swing_position()
    test_tape_kept_for_scalp_intraday()
    test_jit_confirm_default_off()
    test_jit_no_pusher_returns_none()
    print("PASS: all v401 horizon-aware tape + JIT tape-confirm tests")
