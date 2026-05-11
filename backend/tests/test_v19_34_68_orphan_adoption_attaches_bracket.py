"""
Regression test for v19.34.68 — `reconcile_orphan_positions` must submit
OCA stop+target legs to IB after adopting an orphan position.

Bug history
-----------
On 2026-05-11 the bot adopted two orphan positions during a live session:
  - CEG +161 long  @ $298.62 (~$48K)
  - FIG -2,496 short @ $20.78 (~$52K)
Combined ~$100K exposure on a $237K account (42%) sitting NAKED at IB —
the bot recorded `stop_price`/`target_prices` in `bot_trades` but never
submitted the corresponding STP/LMT orders to IB.

Root cause: `_spawn_excess_slice` (share-drift Case 1) had a call to
`executor.attach_oca_stop_target` added in v19.34.28. The sister method
`reconcile_orphan_positions` (IB-only orphan path) was never updated
with the same call. Adopted-from-pure-orphan positions were silently
unprotected from v19.34.28 → v19.34.67.

These tests are structural — they read the source of position_reconciler
and assert the call site + report fields are wired correctly. We avoid
end-to-end mocking because the full reconcile_orphan_positions path has
many real dependencies (account_guard, pusher RPC, prior-verdict lookups)
and a wiring-fix regression is much better tested by direct inspection
than by recreating those dependencies in fixtures.
"""
import ast
import inspect

from services.position_reconciler import PositionReconciler


def _get_method_source(method) -> str:
    return inspect.getsource(method)


def test_reconcile_orphan_calls_attach_oca_stop_target():
    """The method must invoke `executor.attach_oca_stop_target(trade)` at
    least once. If this assertion fails, the v19.34.28-era post-fill
    bracket attach has been removed or renamed."""
    src = _get_method_source(PositionReconciler.reconcile_orphan_positions)
    assert "attach_oca_stop_target" in src, (
        "v19.34.68 regression: `attach_oca_stop_target` no longer called "
        "from reconcile_orphan_positions. Adopted positions will be NAKED at IB."
    )


def test_attach_call_happens_after_persist():
    """The OCA attach must run AFTER `bot._persist_trade(trade)` so that
    if the attach itself raises, the trade is already recorded (we never
    want a fill at IB with no DB trail). Verify positional ordering in
    the source."""
    src = _get_method_source(PositionReconciler.reconcile_orphan_positions)
    # The first persist is wrapped in asyncio.to_thread:
    #   `await asyncio.to_thread(bot._persist_trade, trade)`
    persist_pos = src.find("asyncio.to_thread(bot._persist_trade, trade)")
    attach_pos = src.find("attach_oca_stop_target")
    assert persist_pos > 0, "persist call not found — source structure changed"
    assert attach_pos > 0, "attach_oca_stop_target call not found"
    assert attach_pos > persist_pos, (
        "v19.34.68 ordering violation: attach_oca_stop_target must run AFTER "
        "bot._persist_trade. Otherwise a failed attach can leave a fill "
        "at IB with no matching bot_trades row."
    )


def test_failure_path_emits_NAKED_log():
    """When attach fails, the source must log [RECONCILE NAKED] so the
    operator and any log scrapers can detect unprotected adoptions."""
    src = _get_method_source(PositionReconciler.reconcile_orphan_positions)
    assert "[RECONCILE NAKED]" in src, (
        "v19.34.68: when attach_oca_stop_target fails, log line must "
        "include '[RECONCILE NAKED]' so operators detect unprotected "
        "positions in logs."
    )


def test_report_surfaces_bracket_attached_field():
    """The per-symbol entry in `report['reconciled']` MUST include
    `bracket_attached: bool` so callers (API, UI, tests) can tell
    whether the adopted position is actually protected at IB without
    a second round-trip."""
    src = _get_method_source(PositionReconciler.reconcile_orphan_positions)
    assert '"bracket_attached"' in src, (
        "report shape regression: v19.34.68 added a 'bracket_attached' "
        "field to each entry in report['reconciled']. Removing it breaks "
        "any UI/operator script that checks adoption safety."
    )
    assert '"bracket_attach_error"' in src, (
        "report shape regression: 'bracket_attach_error' field missing. "
        "Operators need the failure reason to remediate (often it's "
        "stop-below-market or short-locate-failure)."
    )
    assert '"stop_order_id"' in src and '"target_order_id"' in src, (
        "report shape regression: stop_order_id/target_order_id fields "
        "missing — they're needed for downstream bracket lifecycle tracking."
    )


def test_attach_outcome_persists_back_to_trade():
    """When the attach succeeds, the returned order IDs must be written
    back onto the Trade object and re-persisted so subsequent reads of
    bot_trades show the live IB order ids (needed by the bracket manager
    and the orphan-GTC reconciler at next sweep)."""
    src = _get_method_source(PositionReconciler.reconcile_orphan_positions)
    # Look for the re-persist after a successful attach
    success_block_idx = src.find('if oca_result and oca_result.get("success"):')
    assert success_block_idx > 0, "Success branch not found after attach call"
    # Check that within the success branch (next ~1200 chars) we re-persist
    success_chunk = src[success_block_idx:success_block_idx + 1200]
    assert "trade.stop_order_id" in success_chunk
    assert "trade.target_order_id" in success_chunk
    assert "bot._persist_trade" in success_chunk, (
        "v19.34.68: on successful attach, must re-persist trade so the "
        "stop_order_id and target_order_id land in bot_trades. Without "
        "the re-persist, a backend restart would lose the linkage."
    )


def test_module_keymap_unchanged_in_audit_service():
    """Cross-check: the audit service still reads the four canonical
    entry_context keys we write from v19.34.67. If THIS test fails,
    the audit's source-of-truth key list changed and v19.34.67's
    mapping needs an update."""
    from services.ai_decision_audit_service import _build_audit_row  # noqa
    audit_src = inspect.getsource(_build_audit_row)
    for ec_key in ("debate", "risk_manager", "institutional_flow", "time_series"):
        assert ec_key in audit_src, (
            f"audit service no longer reads '{ec_key}' — v19.34.67 "
            f"_build_ai_modules_ctx mapping must be updated to match."
        )


def test_source_is_syntactically_valid():
    """Sanity: after our edits the module still parses. Catches the
    case where the edit dropped a brace / mis-indented a block."""
    import services.position_reconciler as pr
    # If the import worked, syntax is valid. Verify the AST parses too
    # so we catch any silent partial-file issue.
    src = inspect.getsource(pr)
    ast.parse(src)
