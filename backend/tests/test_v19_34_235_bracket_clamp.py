"""
v19.34.235 (Part B) — bracket-size clamp tests.

`clamp_protective_qty` guards every protective/closing-order (re)issue: it may
only SHRINK an order to a confirmed, smaller live IB position, never grow it,
and never act on an unknown (None) live size. This is what stops a stale
`trade.shares` (SOXX 43) from arming a closing order larger than the position
holds (17) and flipping it on fill.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ib_direct_service import clamp_protective_qty  # noqa: E402


def test_shrinks_oversized_to_live():
    # The SOXX incident: requested 43, IB holds 17 -> clamp to 17.
    assert clamp_protective_qty(43, 17) == (17, True)


def test_no_clamp_when_request_matches_live():
    assert clamp_protective_qty(17, 17) == (17, False)


def test_no_clamp_when_live_larger_than_request():
    # Never grow: requested 17, IB holds 43 -> leave 17.
    assert clamp_protective_qty(17, 43) == (17, False)


def test_unknown_live_is_fail_open():
    # live_abs=None (couldn't read / snapshot gap) -> never clamp.
    assert clamp_protective_qty(43, None) == (43, False)


def test_live_zero_is_not_clamped():
    # live==0 is treated as "don't shrink to nothing" (kept out of scope of the
    # minimal Part B clamp; behaviour identical to today).
    assert clamp_protective_qty(43, 0) == (43, False)


def test_handles_negative_and_messy_inputs():
    # Signed/abs robustness — clamp works on magnitudes.
    assert clamp_protective_qty(-43, -17) == (17, True)
    assert clamp_protective_qty(0, 17) == (0, False)
    assert clamp_protective_qty(None, 17) == (0, False)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
