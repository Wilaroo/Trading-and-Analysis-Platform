"""Regression tests for the v19.34.320p A+→multi_day horizon-hijack fix patcher.

Validates the §2.2 patcher round-trips and that the patched A+ branch only
promotes carry-natured setups to multi_day (intraday/scalp keep their horizon).

Build first:  python3 scripts/_build_v320p_patcher.py
"""
import os
import shutil
import subprocess
import sys

import pytest

REPO_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(REPO_BACKEND, "services", "enhanced_scanner.py")
PATCHER = "/tmp/patch_v320p.py"


def _ensure():
    if not os.path.isfile(PATCHER):
        subprocess.run([sys.executable, os.path.join(REPO_BACKEND, "scripts", "_build_v320p_patcher.py")], check=True)
    return os.path.isfile(PATCHER)


@pytest.fixture()
def sandbox(tmp_path):
    if not _ensure():
        pytest.skip("patcher not built")
    work = tmp_path / "backend" / "services"
    work.mkdir(parents=True)
    dst = work / "enhanced_scanner.py"
    shutil.copy(TARGET, dst)
    return str(dst), dict(os.environ, V320P_TARGET=str(dst))


def _run(mode, env):
    return subprocess.run([sys.executable, PATCHER, mode], env=env, capture_output=True, text=True)


def test_pre_unpatched(sandbox):
    dst, _ = sandbox
    src = open(dst).read()
    assert 'if smb_score.is_a_plus:\n                        self.trade_style = "multi_day"' in src


def test_check(sandbox):
    _, env = sandbox
    r = _run("--check", env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CHECK OK" in r.stdout


def test_apply_idempotent_rollback(sandbox):
    dst, env = sandbox
    r = _run("--apply", env)
    assert r.returncode == 0, r.stdout + r.stderr
    p = open(dst).read()
    # carry guard present; multi_day promotion now conditional
    assert '_natural_style = (self.trade_style or "").strip().lower()' in p
    assert 'if _natural_style in ("multi_day", "swing", "position", "investment"):' in p
    # the unconditional override line is gone (multi_day assignment is now indented under the guard)
    assert 'is_a_plus:\n                        self.trade_style = "multi_day"' not in p
    import py_compile
    py_compile.compile(dst, doraise=True)

    assert "ALREADY PATCHED" in _run("--apply", env).stdout
    r3 = _run("--rollback", env)
    assert r3.returncode == 0
    assert 'if smb_score.is_a_plus:\n                        self.trade_style = "multi_day"' in open(dst).read()


def test_drift_aborts(sandbox):
    dst, env = sandbox
    with open(dst, "a") as f:
        f.write("\n# drift\n")
    r = _run("--check", env)
    assert r.returncode == 3
    assert "PRE_SHA256 mismatch" in r.stdout
