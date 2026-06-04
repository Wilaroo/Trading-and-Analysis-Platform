"""v19.34.31 Patches B + C regression tests."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
F_PM  = REPO / "backend/services/position_manager.py"
F_REC = REPO / "backend/services/position_reconciler.py"


def test_patch_b_present_and_uses_queue_cancellation():
    assert F_PM.exists(), f"missing: {F_PM}"
    txt = F_PM.read_text()
    assert "v19_34_31_PATCH_B_pre_close_cancel" in txt, "Patch B marker missing"
    assert "v19.34.31 Patch B" in txt, "Patch B comment missing"
    assert "queue_cancellation" in txt, "Patch B must use queue_cancellation()"
    assert "position_manager_close_trade_v19_34_31" in txt, \
        "Patch B must tag requested_by=position_manager_close_trade_v19_34_31"


def test_patch_c_present_and_uses_queue_cancellation():
    assert F_REC.exists(), f"missing: {F_REC}"
    txt = F_REC.read_text()
    assert "v19_34_31_PATCH_C_pre_attach_cancel" in txt, "Patch C marker missing"
    assert "v19.34.31 Patch C" in txt, "Patch C comment missing"
    assert "queue_cancellation" in txt, "Patch C must use queue_cancellation()"
    assert "position_reconciler_v19_34_31" in txt, \
        "Patch C must tag requested_by=position_reconciler_v19_34_31"


def test_patch_c_runs_before_attach_oca():
    """Patch C must appear textually BEFORE the attach_oca_stop_target call
    it's protecting (defensive ordering check)."""
    txt = F_REC.read_text()
    pc_pos = txt.find("v19_34_31_PATCH_C_pre_attach_cancel")
    attach_pos = txt.find("oca_result = await executor.attach_oca_stop_target(trade)")
    assert pc_pos != -1, "Patch C marker not found"
    assert attach_pos != -1, "attach_oca_stop_target call not found"
    assert pc_pos < attach_pos, \
        "Patch C must appear BEFORE the attach_oca_stop_target call"
