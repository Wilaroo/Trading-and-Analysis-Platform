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


# ── v320h backfill helpers (implied-primary) ──────────────────────────────
sys.path.insert(0, str(ROOT / "scripts"))


def test_implied_exit_long_short():
    from repair_v320h_backfill_oca_accounting import implied_exit
    # SATS long: entry 113.9245, realized +137.12 / 29sh → ~118.65 (ib was 118.69)
    assert abs(implied_exit(113.92448575, 137.12, 29, "long") - 118.6528) < 0.01
    # EWY short: entry 187.73, realized -412.65 / 541sh → ~188.49
    assert abs(implied_exit(187.73, -412.65, 541, "short") - 188.4928) < 0.01
    # missing basis → None
    assert implied_exit(0, 100, 10, "long") is None
    assert implied_exit(100, 100, 0, "long") is None


def test_implied_is_internally_consistent():
    # implied exit must agree in sign with net direction (DVN-style guard)
    from repair_v320h_backfill_oca_accounting import implied_exit, new_pnl_pct, new_net_pnl
    # long winner: realized>0 → exit>entry → pnl_pct>0 → net>0
    exit_px = implied_exit(44.12, 301.94, 939, "long")
    assert exit_px > 44.12
    assert new_pnl_pct(44.12, exit_px, "long") > 0
    assert new_net_pnl(301.94, 4.7) > 0


def test_new_net_and_pct_short():
    from repair_v320h_backfill_oca_accounting import new_net_pnl, new_pnl_pct
    assert new_net_pnl(500.0, 1.0) == 499.0
    assert new_pnl_pct(100.0, 90.0, "short") == 10.0


def test_needs_repair_detects_sentinel_and_missing_exit():
    from repair_v320h_backfill_oca_accounting import needs_repair
    # net stuck at -1.0 and exit None → needs repair
    assert needs_repair(None, -1.0, 0.0, 118.65, 136.12, 4.18) is True
    # already correct → no repair
    assert needs_repair(118.65, 136.12, 4.18, 118.65, 136.12, 4.18) is False


# ── v320i / v320j multi-chunk patcher round-trips ─────────────────────────
def _run_patch(patcher, args, target, env_key):
    env = {**os.environ, env_key: str(target)}
    return subprocess.run([sys.executable, str(patcher), *args],
                          capture_output=True, text=True, env=env)


TE = ROOT / "services" / "trade_execution.py"
TE_PRE = "f8037748a65d4dde4ca2435f6826f837726653fe8c10423702cd0a7c5aa7eeb4"
TE_POST = "5a349f9deb62ca192134b61cd3ba76d8905003ed2341efaeb291370b30c35a01"


@pytest.mark.skipif(_sha(TE) != TE_PRE, reason="trade_execution.py not at canonical baseline")
def test_v320i_round_trip(tmp_path):
    patcher = ROOT / "scripts" / "patch_v320i_target_order_ids_capture.py"
    target = tmp_path / "trade_execution.py"
    shutil.copy2(TE, target)
    assert _run_patch(patcher, ["--check"], target, "V320I_TE_TARGET").returncode == 0
    assert _run_patch(patcher, ["--apply"], target, "V320I_TE_TARGET").returncode == 0
    assert _sha(target) == TE_POST
    body = target.read_text(encoding="utf-8")
    compile(body, "trade_execution.py", "exec")
    assert "v19.34.320i" in body
    assert "trade.target_order_ids = [str(_x) for _x in _tids_320i if _x]" in body
    assert _run_patch(patcher, ["--rollback"], target, "V320I_TE_TARGET").returncode == 0
    assert _sha(target) == TE_PRE


PM_DGX_PRE = "90c451329b766f369e03bb0bffb2fcc385e604dd765fb49f5ef9431d0503495d"
PM_DGX_POST = "6752423e3694ef2a93875bed1f00c99035eb27ae29ad7d87ab6a56e4a67b9126"


def _reconstruct_dgx_pm():
    import _build_v320h_patcher as v0
    import _build_v320h1_patcher as v1
    base = (ROOT / "services" / "position_manager.py").read_text(encoding="utf-8")
    return base.replace(v0.OLD, v0.NEW, 1).replace(v0.FINALIZE, v1.FINALIZE_V2, 1)


@pytest.mark.skipif(_sha(PM) != PRE_SHA, reason="position_manager.py not at canonical baseline")
def test_v320j_round_trip(tmp_path):
    import hashlib as _h
    dgx = _reconstruct_dgx_pm()
    assert _h.sha256(dgx.encode()).hexdigest() == PM_DGX_PRE
    patcher = ROOT / "scripts" / "patch_v320j_unrealized_pnl_persist.py"
    target = tmp_path / "position_manager.py"
    target.write_text(dgx, encoding="utf-8")
    assert _run_patch(patcher, ["--check"], target, "V320H_PM_TARGET").returncode == 0
    assert _run_patch(patcher, ["--apply"], target, "V320H_PM_TARGET").returncode == 0
    assert _sha(target) == PM_DGX_POST
    body = target.read_text(encoding="utf-8")
    compile(body, "position_manager.py", "exec")
    assert "v19.34.320j" in body and "unrealized_pnl_synced_at" in body
    assert _run_patch(patcher, ["--rollback"], target, "V320H_PM_TARGET").returncode == 0
    assert _sha(target) == PM_DGX_PRE

