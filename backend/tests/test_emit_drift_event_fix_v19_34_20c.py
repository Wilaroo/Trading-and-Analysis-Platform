"""
v19.34.20c — Verify zombie cleanup path uses real emit method.

Pre-fix bug: v19.34.19's zombie-resolve branch
(`position_reconciler.py:reconcile_share_drift`, around L1319-1322)
called `self._emit_drift_event(...)`, but no such method exists on
`PositionReconciler`. Every successful zombie heal raised
`AttributeError` post-resolve, which the outer try/except caught
and dumped into `report["errors"]` — making the operator-facing
response confusing (zombies were closed, slice was spawned, yet the
JSON had `error: AttributeError ...` for the same drift_record).

Operator-confirmed 2026-05-06 production heal:
- 3 zombies CLOSED ✓
- 2 reconciled_excess_slice spawned ✓
- but `errors` had both records with the AttributeError message ✗

This test pins the contract: after the fix, the zombie-resolve path
must NOT call any `_emit_*` helper that doesn't exist, and must
swallow stream-emit exceptions silently (mirrors the pattern in
`_close_drift_trades_zero`).
"""
import os


def test_emit_drift_event_stub_removed_v19_34_20c():
    """Static guard: the missing-method call should be gone."""
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "position_reconciler.py"
    )
    with open(os.path.abspath(src_path), "r") as f:
        src = f.read()
    assert "await self._emit_drift_event" not in src, (
        "v19.34.20c regression: `await self._emit_drift_event` call "
        "must be removed (it was never defined and raised AttributeError "
        "on every zombie heal)."
    )
    assert "v19.34.20c" in src, "v19.34.20c marker missing — patch reverted?"


def test_zombie_resolve_uses_emit_stream_event_v19_34_20c():
    """The replacement path must use emit_stream_event with kind=warning."""
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "position_reconciler.py"
    )
    with open(os.path.abspath(src_path), "r") as f:
        src = f.read()
    # Locate the v19.34.20c block and verify shape.
    anchor = src.find("v19.34.20c")
    assert anchor > 0
    window = src[anchor: anchor + 2500]
    assert 'from services.sentcom_service import emit_stream_event' in window
    assert '"event": "zombie_trade_drift_v19_34_19"' in window
    assert '"kind": "warning"' in window


def test_emit_method_exists_or_only_stream_used_v19_34_20c():
    """Belt-and-suspenders: PositionReconciler should NOT have a
    `_emit_drift_event` method (we didn't add a stub — we removed the
    caller). Confirms the chosen approach was 'replace the call', not
    'add a stub method'."""
    from services.position_reconciler import PositionReconciler
    # Should NOT exist (we removed the caller, didn't add a stub).
    assert not hasattr(PositionReconciler, "_emit_drift_event"), (
        "Unexpected: PositionReconciler now has _emit_drift_event. "
        "Either the test is stale or someone added a stub method, "
        "in which case the caller in reconcile_share_drift should be "
        "wired through it."
    )
    # The persist counterpart MUST still exist (it's called too).
    assert hasattr(PositionReconciler, "_persist_drift_event")
