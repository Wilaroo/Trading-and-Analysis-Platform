"""Regression tests for the v19.34.320m PATCH-L2a event-loop-spam patcher.

Validates the §2.2 patcher round-trips (check -> apply -> idempotent ->
rollback) on a throwaway copy of ib_direct_service.py and that the patched
get_open_orders() no longer threads the SYNC reqAllOpenOrders() but instead
awaits the native reqAllOpenOrdersAsync() coroutine.

Build the patcher first:  .venv/bin/python scripts/_build_v320m_patcher.py
"""
import os
import shutil
import subprocess
import sys

import pytest

REPO_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(REPO_BACKEND, "services", "ib_direct_service.py")
PATCHER = "/tmp/patch_v320m.py"


def _ensure_patcher():
    if not os.path.isfile(PATCHER):
        subprocess.run(
            [sys.executable, os.path.join(REPO_BACKEND, "scripts", "_build_v320m_patcher.py")],
            check=True,
        )
    return os.path.isfile(PATCHER)


@pytest.fixture()
def sandbox(tmp_path):
    if not _ensure_patcher():
        pytest.skip("patcher not built")
    work = tmp_path / "backend" / "services"
    work.mkdir(parents=True)
    dst = work / "ib_direct_service.py"
    shutil.copy(TARGET, dst)
    env = dict(os.environ, V320M_TARGET=str(dst))
    return str(dst), env


def _run(mode, env):
    return subprocess.run(
        [sys.executable, PATCHER, mode],
        env=env, capture_output=True, text=True,
    )


def test_pre_state_unpatched(sandbox):
    dst, env = sandbox
    src = open(dst).read()
    assert "await asyncio.to_thread(self._ib.reqAllOpenOrders)" in src
    assert "reqAllOpenOrdersAsync" not in src


def test_check_passes(sandbox):
    _, env = sandbox
    r = _run("--check", env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CHECK OK" in r.stdout


def test_apply_then_idempotent_then_rollback(sandbox):
    dst, env = sandbox

    r = _run("--apply", env)
    assert r.returncode == 0, r.stdout + r.stderr
    patched = open(dst).read()
    # threaded sync call gone; native async coroutine awaited
    assert "asyncio.to_thread(self._ib.reqAllOpenOrders)" not in patched
    assert 'getattr(self._ib, "reqAllOpenOrdersAsync"' in patched
    assert "await _req_async()" in patched
    # still compiles
    import py_compile
    py_compile.compile(dst, doraise=True)

    # idempotent
    r2 = _run("--apply", env)
    assert r2.returncode == 0
    assert "ALREADY PATCHED" in r2.stdout

    # rollback restores byte-exact original
    r3 = _run("--rollback", env)
    assert r3.returncode == 0, r3.stdout + r3.stderr
    restored = open(dst).read()
    assert "await asyncio.to_thread(self._ib.reqAllOpenOrders)" in restored
    assert "reqAllOpenOrdersAsync" not in restored


def test_drift_aborts(sandbox):
    dst, env = sandbox
    with open(dst, "a") as f:
        f.write("\n# drift\n")
    r = _run("--check", env)
    assert r.returncode == 3
    assert "PRE_SHA256 mismatch" in r.stdout
