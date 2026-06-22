"""
test_a8_restart_feed_guard.py — verifies patch_a8: the A8 guard in
_auto_execute_alert HOLDS auto-exec during the post-restart warm-up and when
the IB pusher feed is down, and EXECUTES once warm + feed-connected.

Run:  PYTHONPATH=backend python backend/tests/test_a8_restart_feed_guard.py
No IB / Mongo / network required.
"""
import asyncio
import os
import sys
from types import SimpleNamespace
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

os.environ["AUTO_EXEC_WARMUP_SCANS"] = "5"
os.environ["AUTO_EXEC_REQUIRE_FEED"] = "1"

import routers.ib as ibmod  # noqa: E402
from services.enhanced_scanner import EnhancedBackgroundScanner  # noqa: E402

PASS, FAIL = "✅", "❌"
_failures = []


def check(name, cond):
    print(f"  {PASS if cond else FAIL} {name}")
    if not cond:
        _failures.append(name)


def _alert():
    return SimpleNamespace(
        auto_execute_eligible=True,
        created_at=datetime.now(timezone.utc).isoformat(),
        id="alrt_x", symbol="INTC", setup_type="stage_2_breakout",
        headline="INTC stage_2_breakout", direction="long",
        current_price=140.0, stop_loss=133.0, target=0.0, priority=None,
        tqs_grade="B", tqs_score=55.0, tape_score=0.0, tape_confirmation=False,
        risk_reward=2.0, atr=2.0, atr_percent=1.5, trade_style="position", smb_grade="",
    )


async def _run(scan_count, pusher_connected):
    sc = object.__new__(EnhancedBackgroundScanner)
    sc._auto_execute_enabled = True
    sc._strategy_stats = {}
    sc._scan_count = scan_count
    submitted = {"called": False}

    async def _submit(req):
        submitted["called"] = True

    sc._trading_bot = SimpleNamespace(submit_trade_from_scanner=_submit)
    ibmod.is_pusher_connected = lambda: pusher_connected  # monkeypatch
    await sc._auto_execute_alert(_alert())
    return submitted["called"]


async def _main():
    print("TEST — A8 restart/feed guard (warm-up=5, require_feed=1)")
    # the bug case: fresh restart (scan_count low) -> HOLD even if feed up
    held_warmup = await _run(scan_count=1, pusher_connected=True)
    check("scan #1 (post-restart warm-up) HOLDS auto-exec", held_warmup is False)
    # warm but feed down -> HOLD
    held_feed = await _run(scan_count=50, pusher_connected=False)
    check("feed DOWN HOLDS auto-exec", held_feed is False)
    # warm + feed up -> EXECUTE
    executed = await _run(scan_count=50, pusher_connected=True)
    check("warm + feed UP EXECUTES", executed is True)
    # disable knobs -> execute even cold
    os.environ["AUTO_EXEC_WARMUP_SCANS"] = "0"
    os.environ["AUTO_EXEC_REQUIRE_FEED"] = "0"
    bypass = await _run(scan_count=0, pusher_connected=False)
    os.environ["AUTO_EXEC_WARMUP_SCANS"] = "5"
    os.environ["AUTO_EXEC_REQUIRE_FEED"] = "1"
    check("knobs off (warmup=0, feed=0) bypass guard", bypass is True)

    src = open(os.path.join(HERE, "..", "services", "enhanced_scanner.py"), encoding="utf-8").read()
    check("A8 marker present", "A8 RESTART/FEED GUARD" in src)
    check("warm-up knob present", "AUTO_EXEC_WARMUP_SCANS" in src)
    check("feed knob present", "AUTO_EXEC_REQUIRE_FEED" in src)
    check("guard before trade_request build",
          src.index("A8 RESTART/FEED GUARD") < src.index('"source": "scanner_auto_execute"'))

    print()
    if _failures:
        print(f"{FAIL} {len(_failures)} FAILED: {_failures}")
        sys.exit(1)
    print(f"{PASS} ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(_main())
