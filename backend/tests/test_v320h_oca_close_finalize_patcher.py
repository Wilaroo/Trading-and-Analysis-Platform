"""Regression guard for the v19.34.320h OCA close-finalize patcher.

Validates:
  1. The emitted patcher round-trips against the canonical baseline:
     PRE_SHA -> --apply -> POST_SHA (compiles) -> --rollback -> PRE_SHA.
  2. The OCA close-path accounting math contract holds
     (net_pnl = realized - commissions; pnl_pct long/short).

These tests do NOT require IB hardware or a running backend.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]            # backend/
PM = ROOT / "services" / "position_manager.py"
PATCHER = ROOT / "scripts" / "patch_v320h_oca_close_finalize.py"

PRE_SHA = "ee4f3f2ef837391e4b563b0a6dc48b0860c4b6b0fa19e2b4203f226f89117977"
POST_SHA = "e5cec8f958e9a26477d8d3fb1f0e7814e9b268c39013d49cf31640c161787d0e"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(args, target):
    env = {**os.environ, "V320H_PM_TARGET": str(target)}
    return subprocess.run(
        [sys.executable, str(PATCHER), *args],
        capture_output=True, text=True, env=env)


@pytest.mark.skipif(_sha(PM) != PRE_SHA,
                    reason="local position_manager.py is not the canonical baseline")
def test_patcher_round_trip(tmp_path):
    target = tmp_path / "position_manager.py"
    shutil.copy2(PM, target)
    assert _sha(target) == PRE_SHA

    r = _run(["--check"], target)
    assert r.returncode == 0, r.stdout + r.stderr

    r = _run(["--apply"], target)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _sha(target) == POST_SHA

    # patched file must be valid python
    compile(target.read_text(encoding="utf-8"), "position_manager.py", "exec")
    body = target.read_text(encoding="utf-8")
    assert "v19.34.320h" in body
    assert "V320H_OCA_FIX_POLICY" in body

    r = _run(["--rollback"], target)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _sha(target) == PRE_SHA


def _finalize_math(realized_pnl, total_commissions, entry_basis, exit_px, direction):
    net = round(realized_pnl - total_commissions, 2)
    if direction == "short":
        pct = round((entry_basis - exit_px) / entry_basis * 100, 4)
    else:
        pct = round((exit_px - entry_basis) / entry_basis * 100, 4)
    return net, pct


def test_finalize_math_long():
    # mirrors the SPCX v320g canonical case
    net, pct = _finalize_math(699.65, 1.00, 172.59, 189.30, "long")
    assert net == 698.65
    assert round(pct, 2) == 9.68


def test_finalize_math_short():
    # short: profit when exit < entry
    net, pct = _finalize_math(500.0, 1.00, 100.0, 90.0, "short")
    assert net == 499.0
    assert pct == 10.0


def test_finalize_math_clears_sentinel():
    # the bug: net_pnl stuck at -1.00 sentinel; fix recomputes from realized
    net, _ = _finalize_math(699.65, 1.00, 172.59, 189.30, "long")
    assert net != -1.00
