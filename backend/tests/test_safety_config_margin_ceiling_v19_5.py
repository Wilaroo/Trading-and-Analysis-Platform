"""
v19.5 — Safety config Pydantic ceiling raised for margin accounts.

The `PUT /api/safety/config` endpoint had `le=100` on
`max_total_exposure_pct`. That's correct for cash accounts but
rejects margin operators where 80% of buying power == 320% of
equity is normal. Operator's curl returned 422 with `Input should
be less than or equal to 100`.

This test pins the new ceiling at 1000 (effectively unlimited for
realistic Reg-T margin) and guards against a future contributor
re-tightening it.
"""
from __future__ import annotations

import pytest


def test_safety_config_patch_accepts_margin_exposure_pct():
    """Margin operators (4× buying power) need >100% of equity."""
    from routers.safety_router import SafetyConfigPatch
    # 320% — operator's actual margin-account target
    patch = SafetyConfigPatch(max_total_exposure_pct=320)
    assert patch.max_total_exposure_pct == 320

    # Edge: just under the new ceiling
    patch_high = SafetyConfigPatch(max_total_exposure_pct=999)
    assert patch_high.max_total_exposure_pct == 999


def test_safety_config_patch_still_rejects_negative_or_zero():
    """The lower bound (>0) must still hold so a typo can't disable
    the safety cap entirely."""
    from pydantic import ValidationError
    from routers.safety_router import SafetyConfigPatch
    with pytest.raises(ValidationError):
        SafetyConfigPatch(max_total_exposure_pct=0)
    with pytest.raises(ValidationError):
        SafetyConfigPatch(max_total_exposure_pct=-50)


def test_safety_config_patch_rejects_absurd_exposure():
    """1000% is the new ceiling — anything beyond is almost certainly
    a typo (operators don't run >10× leverage)."""
    from pydantic import ValidationError
    from routers.safety_router import SafetyConfigPatch
    with pytest.raises(ValidationError):
        SafetyConfigPatch(max_total_exposure_pct=10001)


def test_other_safety_fields_unchanged():
    """Sanity check: bumping the exposure ceiling didn't loosen the
    other validators."""
    from pydantic import ValidationError
    from routers.safety_router import SafetyConfigPatch

    # max_daily_loss_pct still <100
    with pytest.raises(ValidationError):
        SafetyConfigPatch(max_daily_loss_pct=150)

    # max_positions still ≤100
    with pytest.raises(ValidationError):
        SafetyConfigPatch(max_positions=500)

    # max_quote_age_seconds still <300
    with pytest.raises(ValidationError):
        SafetyConfigPatch(max_quote_age_seconds=600)
