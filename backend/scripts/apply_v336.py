#!/usr/bin/env python3
"""
apply_v336.py — IB BOOT PROBE: AUTO-RECOVERY OF THE RED HEALTH LATCH
=====================================================================
EVIDENCE (2026-06-12): a mid-session backend restart beat the deferred
IB connect; the boot probe failed its 30s grace, latched `ib_boot_probe`
RED and kept /api/system/health overall=red + "1 CRITICAL" for the REST
OF THE SESSION — while ib_gateway itself was green and the bot traded
normally. The probe never re-checked.

FIX:
  1. After a boot-grace FAIL the probe keeps re-probing every 30s in the
     background; once the execution feed verifies live the HEALTH status
     self-clears to green ("recovered: ...").
  2. The KILL-SWITCH latch is NOT touched — resetting it stays a manual
     operator action (the silent-start hard-block rationale is intact).
  3. Grace window env-tunable: IB_BOOT_PROBE_GRACE_S (default 30).

NOTE: the probe TRIPS the kill-switch on fail by design — after applying,
check Safety panel / kill-switch state and reset manually if needed.

SAFE TO RUN MULTIPLE TIMES (idempotent). No DB phase.
Run from repo root:   .venv/bin/python /tmp/apply_v336.py
Then: git add -A && git commit -m "v336: ib_boot_probe auto-recovery + env grace" && git push
Then RESTART the backend.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHUNKS = [
    ('backend/services/ib_boot_probe.py',
     '_STATE: Dict[str, Any] = {\n    "status": "pending",\n    "detail": "probe not yet run",\n    "order_path": None,\n    "checked_at": None,\n    "tripped_kill_switch": False,\n}\n',
     '_STATE: Dict[str, Any] = {\n    "status": "pending",\n    "detail": "probe not yet run",\n    "order_path": None,\n    "checked_at": None,\n    "tripped_kill_switch": False,\n    "recovered_at": None,\n}\n'),
    ('backend/services/ib_boot_probe.py',
     'async def run_ib_boot_probe(grace_s: float = 30.0, poll_s: float = 2.0) -> Dict[str, Any]:\n    """Poll the IB execution feed for up to `grace_s` seconds. On success,\n    mark the subsystem green. On persistent failure, trip the kill-switch\n    (HARD BLOCK) and mark the subsystem red. Never raises."""\n',
     'async def run_ib_boot_probe(grace_s: float = 30.0, poll_s: float = 2.0,\n                            recovery_poll_s: float = 30.0) -> Dict[str, Any]:\n    """Poll the IB execution feed for up to `grace_s` seconds. On success,\n    mark the subsystem green. On persistent failure, trip the kill-switch\n    (HARD BLOCK), mark the subsystem red, and keep re-probing in the\n    background so the HEALTH status self-clears once the feed verifies\n    live (the kill-switch latch stays manual-reset). Never raises."""\n'),
    ('backend/services/ib_boot_probe.py',
     '    except Exception as exc:\n        logger.error("[IB-BOOT-PROBE] FAILED TO TRIP KILL-SWITCH: %s", exc)\n        print(f"[STARTUP] v19.34.308 — CRITICAL: could not trip kill-switch: {exc}")\n    return get_boot_probe_state()\n',
     '    except Exception as exc:\n        logger.error("[IB-BOOT-PROBE] FAILED TO TRIP KILL-SWITCH: %s", exc)\n        print(f"[STARTUP] v19.34.308 — CRITICAL: could not trip kill-switch: {exc}")\n\n    # v336 — RECOVERY RE-PROBE. The red latch previously persisted for\n    # the rest of the session even after IB came up seconds later\n    # (observed 2026-06-12: a mid-session restart beat the deferred IB\n    # connect, so overall health stayed red + "1 CRITICAL" all day while\n    # ib_gateway itself was green). Keep checking in the background and\n    # clear the HEALTH status once the execution feed verifies live.\n    # The KILL-SWITCH latch is intentionally NOT touched — resetting it\n    # stays a manual operator action (silent-start rationale above).\n    if recovery_poll_s and recovery_poll_s > 0:\n        try:\n            asyncio.create_task(_recovery_reprobe(recovery_poll_s))\n        except RuntimeError:\n            pass  # no running loop — skip background recovery\n    return get_boot_probe_state()\n\n\nasync def _recovery_reprobe(poll_s: float) -> None:\n    """v336 — after a boot-probe FAIL, re-check the execution feed every\n    `poll_s` seconds and flip the health status green once it verifies\n    live. Exits on success. Never raises."""\n    while _STATE["status"] == "red":\n        try:\n            await asyncio.sleep(poll_s)\n            ok, detail = await asyncio.to_thread(_probe_once)\n            if ok:\n                now = time.time()\n                _STATE["status"] = "green"\n                _STATE["recovered_at"] = now\n                _STATE["checked_at"] = now\n                _STATE["detail"] = (\n                    f"recovered: {detail} — boot probe had failed; "\n                    "kill-switch latch unchanged (reset manually if tripped)"\n                )\n                logger.warning("[IB-BOOT-PROBE] RECOVERED — %s", detail)\n                print(f"[IB-BOOT-PROBE] v336 — RECOVERED: {detail}")\n                return\n        except asyncio.CancelledError:\n            return\n        except Exception as exc:\n            logger.debug("[IB-BOOT-PROBE] recovery probe error: %s", exc)\n'),
    ('backend/server.py',
     '    try:\n        from services.ib_boot_probe import run_ib_boot_probe\n        asyncio.create_task(run_ib_boot_probe(grace_s=30.0, poll_s=2.0))\n        print("[STARTUP] v19.34.308 — IB-Gateway boot probe scheduled (30s grace, hard-block on fail).")\n',
     '    try:\n        from services.ib_boot_probe import run_ib_boot_probe\n        # v336 — grace env-tunable (mid-session restarts can beat the\n        # deferred IB connect at 30s); probe self-clears health on\n        # recovery, kill-switch latch stays manual.\n        _probe_grace = float(os.environ.get("IB_BOOT_PROBE_GRACE_S", "30"))\n        asyncio.create_task(run_ib_boot_probe(grace_s=_probe_grace, poll_s=2.0))\n        print(f"[STARTUP] v19.34.308 — IB-Gateway boot probe scheduled ({_probe_grace:.0f}s grace, hard-block on fail, v336 auto-recovery).")\n'),
]

TEST_REL = 'backend/tests/test_v336_boot_probe_recovery.py'
TEST_CONTENT = '"""v336 — ib_boot_probe no longer latches RED forever: after a boot-grace\nFAIL it keeps re-probing in the background and clears the HEALTH status\nonce the execution feed verifies live. The kill-switch latch stays\nmanual-reset (silent-start rationale untouched).\n\nProbe evidence (2026-06-12): mid-session restart beat the deferred IB\nconnect; ib_boot_probe latched red + "1 CRITICAL" for the whole session\nwhile ib_gateway itself was green.\n"""\nimport asyncio\nfrom pathlib import Path\nimport sys\n\n\ndef _repo_root():\n    for c in Path(__file__).resolve().parents:\n        if (c / "backend" / "services" / "ib_boot_probe.py").exists():\n            return c\n    raise AssertionError("repo root not found")\n\n\nROOT = _repo_root()\nsys.path.insert(0, str(ROOT / "backend"))\n\nfrom services import ib_boot_probe as bp  # noqa: E402\n\n\ndef _reset_state():\n    bp._STATE.update({\n        "status": "pending", "detail": "probe not yet run",\n        "order_path": None, "checked_at": None,\n        "tripped_kill_switch": False, "recovered_at": None,\n    })\n\n\nclass _FakeGuard:\n    def __init__(self):\n        self.tripped = []\n        self.resets = []\n\n    def trip_kill_switch(self, reason):\n        self.tripped.append(reason)\n\n    def reset_kill_switch(self, *a, **kw):\n        self.resets.append(a)\n\n\ndef test_fail_then_recovery_clears_health(monkeypatch):\n    _reset_state()\n    feed = {"ok": False}\n    monkeypatch.setattr(bp, "_probe_once",\n                        lambda: (feed["ok"], "ib_direct connected (execution feed live)"\n                                 if feed["ok"] else "ib_direct_service NOT connected"))\n    guard = _FakeGuard()\n    import services.safety_guardrails as sg\n    monkeypatch.setattr(sg, "get_safety_guardrails", lambda: guard)\n\n    async def _scenario():\n        out = await bp.run_ib_boot_probe(grace_s=0.0, poll_s=0.01,\n                                         recovery_poll_s=0.01)\n        assert out["status"] == "red"\n        assert out["tripped_kill_switch"] is True\n        # feed comes alive a moment later → health must self-clear\n        feed["ok"] = True\n        for _ in range(100):\n            await asyncio.sleep(0.02)\n            if bp.get_boot_probe_state()["status"] == "green":\n                break\n        st = bp.get_boot_probe_state()\n        assert st["status"] == "green", st\n        assert "recovered" in st["detail"]\n        assert st["recovered_at"] is not None\n\n    asyncio.run(_scenario())\n    # kill-switch latch must stay MANUAL: tripped once, never auto-reset\n    assert len(guard.tripped) == 1\n    assert guard.resets == []\n\n\ndef test_recovery_keeps_probing_until_live(monkeypatch):\n    _reset_state()\n    calls = {"n": 0}\n\n    def _probe():\n        calls["n"] += 1\n        return (calls["n"] >= 4, "detail")\n    monkeypatch.setattr(bp, "_probe_once", _probe)\n    guard = _FakeGuard()\n    import services.safety_guardrails as sg\n    monkeypatch.setattr(sg, "get_safety_guardrails", lambda: guard)\n\n    async def _scenario():\n        out = await bp.run_ib_boot_probe(grace_s=0.0, poll_s=0.01,\n                                         recovery_poll_s=0.01)\n        assert out["status"] == "red"\n        for _ in range(200):\n            await asyncio.sleep(0.02)\n            if bp.get_boot_probe_state()["status"] == "green":\n                return\n        raise AssertionError("recovery never flipped green")\n\n    asyncio.run(_scenario())\n    assert calls["n"] >= 4\n\n\ndef test_pass_path_unchanged(monkeypatch):\n    _reset_state()\n    monkeypatch.setattr(bp, "_probe_once", lambda: (True, "live"))\n\n    async def _scenario():\n        out = await bp.run_ib_boot_probe(grace_s=0.0, poll_s=0.01)\n        assert out["status"] == "green"\n        assert out["tripped_kill_switch"] is False\n        assert out["recovered_at"] is None\n\n    asyncio.run(_scenario())\n\n\ndef test_server_grace_env_tunable():\n    src = (ROOT / "backend/server.py").read_text()\n    assert "IB_BOOT_PROBE_GRACE_S" in src\n'


def find_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / "backend" / "services" / "ib_boot_probe.py").exists():
            return cand
    print("FATAL: run from repo root")
    sys.exit(1)


def main():
    root = find_root()
    print(f"repo root: {root}")
    if not CHUNKS:
        print("[FATAL] CHUNKS is empty — refusing to run an empty patcher (v334 lesson).")
        sys.exit(9)

    applied = 0
    for i, (rel, old, new) in enumerate(CHUNKS, 1):
        path = root / rel
        text = path.read_text()
        if new in text:
            print(f"[SKIP] {rel} chunk {i} — already applied")
            continue
        n = text.count(old)
        if n != 1:
            print(f"[FAIL] {rel} chunk {i} — anchor found {n}x. ABORTING.")
            sys.exit(2)
        path.write_text(text.replace(old, new, 1))
        applied += 1
        print(f"[OK]   {rel} chunk {i} — applied")
    tp = root / TEST_REL
    if not (tp.exists() and tp.read_text() == TEST_CONTENT):
        tp.write_text(TEST_CONTENT)
        applied += 1
        print(f"[OK]   {TEST_REL} — written")
    else:
        print(f"[SKIP] {TEST_REL} — already present")

    print()
    print("── self-test: pytest ──")
    tests = ["tests/test_v336_boot_probe_recovery.py",
             "tests/test_v308_ib_boot_probe.py",
             "tests/test_v335_eod_policy_consumers.py",
             "tests/test_v334_policy_resolution.py",
             "tests/test_eod_naked_flatten_guard_v301.py",
             "tests/test_eod_force_flatten_bracketed_v302.py",
             "tests/test_v332_regime_demotion.py"]
    existing = [t for t in tests if (root / "backend" / t).exists()]
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", *existing],
                       cwd=str(root / "backend"),
                       capture_output=True, text=True, timeout=300)
    for line in (r.stdout or "").strip().splitlines()[-3:]:
        print("   " + line)
    if r.returncode != 0:
        print("[FAIL] self-test failed — NOT safe to restart.")
        print((r.stdout or "")[-2000:])
        sys.exit(3)
    print("[OK]   self-test PASSED")
    print()
    print(f"v336 done — {applied} item(s) newly applied.")
    print("  git add -A && git commit -m 'v336: ib_boot_probe auto-recovery + env grace' && git push")
    print("  RESTART the backend. Then check kill-switch state (boot-probe fail trips it by design).")


if __name__ == "__main__":
    main()
