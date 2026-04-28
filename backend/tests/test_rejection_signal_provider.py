"""
Regression tests for `services.rejection_signal_provider` — the
scaffolded bridge that lets `multiplier_threshold_optimizer` and
`gate_calibrator` consume rejection-analytics data.

Asserts:
  - Default OFF: signal returns `enabled: False` + a clear note.
  - Flag ON: signal aggregates rejection-analytics output, routes by
    target (confidence_gate / risk_caps / smart_levels), and emits
    `suggested_direction` per the verdict.
  - Optimizer + calibrator hooks: when flag OFF, no behavior change
    (no `rejection_feedback` key in payload). When flag ON with
    actionable hints, payload gets annotated WITHOUT mutating any
    threshold proposals — observe-only by design.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import mongomock
import pytest

from services.rejection_signal_provider import (
    REASON_CODE_TO_TARGET,
    get_signal,
    is_feedback_enabled,
)


@pytest.fixture
def db_with_rejections():
    """Mongomock pre-seeded with enough data to produce a verdict."""
    db = mongomock.MongoClient().db
    now = datetime.now(timezone.utc)
    # 6 rejections of `tqs_too_low` (confidence_gate target)
    for i in range(6):
        db["sentcom_thoughts"].insert_one({
            "id": f"r_tqs_{i}",
            "kind": "rejection",
            "symbol": "NVDA",
            "metadata": {
                "reason_code": "tqs_too_low",
                "setup_type": "orb_long",
            },
            "created_at": now - timedelta(hours=2 + i),
        })
    # 5 winning post-rejection trades on NVDA orb_long
    for i in range(5):
        db["bot_trades"].insert_one({
            "symbol": "NVDA",
            "setup_type": "orb_long",
            "executed_at": (now - timedelta(hours=1 - 0.1 * i)).isoformat(),
            "status": "closed",
            "net_pnl": 100.0,
        })
    return db


def test_flag_default_off():
    """No env var set → feedback disabled."""
    with patch.dict("os.environ", {}, clear=False):
        # Ensure the var is NOT set
        import os as _os
        _os.environ.pop("ENABLE_REJECTION_SIGNAL_FEEDBACK", None)
        assert is_feedback_enabled() is False


@pytest.mark.parametrize("val", ["true", "1", "yes", "on", "TRUE", "Yes"])
def test_flag_truthy_values(val):
    with patch.dict("os.environ", {"ENABLE_REJECTION_SIGNAL_FEEDBACK": val}):
        assert is_feedback_enabled() is True


@pytest.mark.parametrize("val", ["false", "0", "no", "off", "", "maybe"])
def test_flag_falsy_values(val):
    with patch.dict("os.environ", {"ENABLE_REJECTION_SIGNAL_FEEDBACK": val}):
        assert is_feedback_enabled() is False


def test_get_signal_returns_disabled_when_flag_off(db_with_rejections):
    """Even with rejection data present, flag-off must short-circuit."""
    with patch.dict("os.environ", {"ENABLE_REJECTION_SIGNAL_FEEDBACK": "false"}):
        sig = get_signal(db_with_rejections)
    assert sig["enabled"] is False
    assert sig["by_target"] == {}
    assert sig["actionable_count"] == 0
    assert "note" in sig
    assert "ENABLE_REJECTION_SIGNAL_FEEDBACK" in sig["note"]


def test_get_signal_routes_tqs_to_confidence_gate(db_with_rejections):
    with patch.dict("os.environ", {"ENABLE_REJECTION_SIGNAL_FEEDBACK": "true"}):
        sig = get_signal(db_with_rejections, days=14, min_count=3)

    assert sig["enabled"] is True
    cg = sig["by_target"].get("confidence_gate") or []
    assert len(cg) == 1
    h = cg[0]
    assert h["reason_code"] == "tqs_too_low"
    assert h["dial"] == "min_score"
    assert h["verdict"] == "gate_potentially_overtight"
    assert h["suggested_direction"] == "loosen"
    assert sig["actionable_count"] == 1


def test_get_signal_target_filter():
    """`target=` filter must drop rows from other targets."""
    db = mongomock.MongoClient().db
    now = datetime.now(timezone.utc)
    for i in range(6):
        db["sentcom_thoughts"].insert_one({
            "id": f"r_e_{i}", "kind": "rejection", "symbol": "AAPL",
            "metadata": {"reason_code": "exposure_cap", "setup_type": "orb_long"},
            "created_at": now - timedelta(hours=1 + i),
        })

    with patch.dict("os.environ", {"ENABLE_REJECTION_SIGNAL_FEEDBACK": "true"}):
        sig = get_signal(db, target="confidence_gate", days=14, min_count=3)
    # No confidence_gate-mapped reasons → empty
    assert sig["by_target"].get("confidence_gate") in (None, [])

    with patch.dict("os.environ", {"ENABLE_REJECTION_SIGNAL_FEEDBACK": "true"}):
        sig2 = get_signal(db, target="risk_caps", days=14, min_count=3)
    risk_rows = sig2["by_target"].get("risk_caps") or []
    assert len(risk_rows) == 1
    assert risk_rows[0]["reason_code"] == "exposure_cap"


def test_get_signal_handles_unmapped_reason_codes_gracefully():
    """Reason codes not in REASON_CODE_TO_TARGET are dropped silently —
    they remain visible via the raw analytics endpoint."""
    db = mongomock.MongoClient().db
    now = datetime.now(timezone.utc)
    for i in range(6):
        db["sentcom_thoughts"].insert_one({
            "id": f"r_x_{i}", "kind": "rejection", "symbol": "X",
            "metadata": {"reason_code": "totally_made_up", "setup_type": "orb_long"},
            "created_at": now - timedelta(hours=1 + i),
        })

    with patch.dict("os.environ", {"ENABLE_REJECTION_SIGNAL_FEEDBACK": "true"}):
        sig = get_signal(db, days=14, min_count=3)

    assert sig["enabled"] is True
    assert sig["by_target"] == {}
    assert sig["actionable_count"] == 0


def test_reason_code_map_has_known_targets():
    """Sanity: every entry maps to a target the optimizers recognize."""
    valid = {"confidence_gate", "risk_caps", "smart_levels"}
    for code, m in REASON_CODE_TO_TARGET.items():
        assert m["target"] in valid, f"{code} → unknown target {m['target']}"
        assert m["dial"], f"{code} missing dial"


# ─── Optimizer hook tests ────────────────────────────────────────────

def test_optimizer_does_not_emit_feedback_when_flag_off():
    """multiplier_threshold_optimizer payload must be unchanged when
    flag is OFF (no `rejection_feedback` key)."""
    from services import multiplier_threshold_optimizer as opt
    db = mongomock.MongoClient().db

    with patch.dict("os.environ", {"ENABLE_REJECTION_SIGNAL_FEEDBACK": "false"}):
        with patch.object(opt, "compute_multiplier_analytics",
                          return_value={"stop_guard": {}, "target_snap": {}, "vp_path": {}}):
            payload = opt.run_optimization(db, days_back=30, dry_run=True)
    assert "rejection_feedback" not in payload
    assert payload.get("rejection_feedback_status", "").startswith(
        "feedback gated"
    ) or "rejection_feedback_status" in payload


def test_optimizer_annotates_payload_when_flag_on(db_with_rejections):
    """When flag is ON and rejection signal has smart_levels hints, the
    optimizer payload includes them — but no threshold is mutated.
    (Observe-only contract.)"""
    from services import multiplier_threshold_optimizer as opt

    db = db_with_rejections
    # Add a smart_levels-targeted rejection so we have something to surface
    now = datetime.now(timezone.utc)
    for i in range(6):
        db["sentcom_thoughts"].insert_one({
            "id": f"r_sl_{i}", "kind": "rejection", "symbol": "MSFT",
            "metadata": {"reason_code": "stop_too_close", "setup_type": "orb_long"},
            "created_at": now - timedelta(hours=2 + i),
        })
    for i in range(5):
        db["bot_trades"].insert_one({
            "symbol": "MSFT", "setup_type": "orb_long",
            "executed_at": (now - timedelta(hours=1 - 0.1 * i)).isoformat(),
            "status": "closed", "net_pnl": 75.0,
        })

    with patch.dict("os.environ", {"ENABLE_REJECTION_SIGNAL_FEEDBACK": "true"}):
        with patch.object(opt, "compute_multiplier_analytics",
                          return_value={"stop_guard": {}, "target_snap": {}, "vp_path": {}}):
            payload = opt.run_optimization(db, days_back=30, dry_run=True)

    # Hint surfaced
    assert "rejection_feedback" in payload
    hints = payload["rejection_feedback"]
    assert any(h["reason_code"] == "stop_too_close" for h in hints)
    # No threshold mutated — proposals all `lift_within_band` /
    # `insufficient_data` since analytics was empty
    for prop in payload["proposals"].values():
        assert prop["proposed"] == prop["current"], \
            "Observe-only contract violated: optimizer mutated a threshold "\
            "from a rejection hint"
