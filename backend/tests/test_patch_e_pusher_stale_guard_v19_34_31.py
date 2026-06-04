"""v19.34.31 Patch E regression test — pusher-stale no-panic guard."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
F_BOT = REPO / "backend/services/trading_bot_service.py"


def test_patch_e_naked_sweep_guard_present():
    assert F_BOT.exists(), f"missing: {F_BOT}"
    txt = F_BOT.read_text()
    assert "v19_34_31_PATCH_E_pusher_stale_guard" in txt, "Patch E marker missing"
    assert "PUSHER_STALE_THRESHOLD_SEC" in txt, "Patch E threshold missing"
    assert "pusher_snapshot_stale" in txt, "Patch E skip-reason signal missing"
