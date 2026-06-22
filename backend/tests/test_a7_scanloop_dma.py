"""
test_a7_scanloop_dma.py — verifies patch_a7:
  1. EnhancedBackgroundScanner.start() spawns the scan-loop task BEFORE the
     carry-forward hydrate, so a slow hydrate + outer wait_for() timeout can
     no longer strand the scanner (the P0 regression).
  2. The softened DMA directional filter truth-table (buffer / structure /
     pullback-exemption), validated against the live source tokens.

Run:  PYTHONPATH=backend python backend/tests/test_a7_scanloop_dma.py
No IB / Mongo / network required.
"""
import asyncio
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

from services.enhanced_scanner import EnhancedBackgroundScanner  # noqa: E402

PASS = "✅"
FAIL = "❌"
_failures = []


def check(name, cond):
    print(f"  {PASS if cond else FAIL} {name}")
    if not cond:
        _failures.append(name)


async def test_start_spawns_loop_before_hydrate():
    print("TEST 1 — start() launches the loop independent of a slow hydrate")
    sc = object.__new__(EnhancedBackgroundScanner)  # bypass heavy __init__
    sc._running = False
    sc._scan_task = None
    sc._watchlist = []
    sc._enabled_setups = set()

    loop_started = {"v": False}
    hydrate_started = {"v": False}
    hydrate_finished = {"v": False}

    async def fake_scan_loop():
        loop_started["v"] = True
        try:
            while sc._running:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass

    async def slow_hydrate():
        hydrate_started["v"] = True
        await asyncio.sleep(1.0)          # slower than the outer budget
        hydrate_finished["v"] = True
        return 0

    sc._scan_loop = fake_scan_loop
    sc._hydrate_carry_forward_alerts_from_mongo = slow_hydrate

    # Mirror server boot: start() under a tight wait_for budget.
    timed_out = False
    try:
        await asyncio.wait_for(sc.start(), timeout=0.2)
    except asyncio.TimeoutError:
        timed_out = True

    await asyncio.sleep(0.05)  # let the spawned loop task run a tick

    check("start() was cancelled by the wait_for budget (slow hydrate)", timed_out)
    check("scanner _running is True despite the timeout", sc._running is True)
    check("_scan_task was created", sc._scan_task is not None)
    check("scan loop actually started running", loop_started["v"] is True)
    check("hydrate had started (runs after loop launch)", hydrate_started["v"] is True)
    check("hydrate did NOT need to finish for the loop to be alive",
          hydrate_finished["v"] is False)

    # cleanup
    sc._running = False
    if sc._scan_task:
        sc._scan_task.cancel()
        try:
            await sc._scan_task
        except (asyncio.CancelledError, Exception):
            pass


def _dma_should_reject_long(price, ema50, sma200, setup_type, buf=0.02):
    """Pure mirror of the softened LONG/EMA50 gate for truth-table testing."""
    exempt = {
        "accumulation_entry", "three_week_tight", "vwap_bounce",
        "second_chance", "rubber_band", "backside", "mean_reversion",
        "first_vwap_pullback", "pullback",
    }
    struct_up = sma200 > 0 and ema50 > sma200
    long_floor = ema50 * (1.0 - buf)
    return price < long_floor and not struct_up and setup_type not in exempt


def test_dma_truth_table():
    print("TEST 2 — softened DMA directional filter (LONG / EMA50)")
    # 1.0% below EMA50, no uptrend structure, momentum setup -> ALLOW (within 2% buffer)
    check("shallow dip within 2% buffer is ALLOWED",
          _dma_should_reject_long(99.0, 100.0, 105.0, "rs_leader_break") is False)
    # 5% below EMA50, 50<200 (downtrend structure), momentum setup -> REJECT
    check("deep (>2%) below EMA50 with NO uptrend structure is REJECTED",
          _dma_should_reject_long(95.0, 100.0, 110.0, "rs_leader_break") is True)
    # 5% below EMA50 BUT 50>200 (uptrend structure) -> ALLOW (buy-the-dip)
    check("deep dip but EMA50>SMA200 (uptrend) is ALLOWED",
          _dma_should_reject_long(95.0, 100.0, 90.0, "rs_leader_break") is False)
    # 5% below EMA50, downtrend, but PULLBACK setup -> ALLOW (exempt)
    check("deep dip in downtrend but pullback-setup is ALLOWED (exempt)",
          _dma_should_reject_long(95.0, 100.0, 110.0, "accumulation_entry") is False)
    # Original-style hard reject case now allowed: 0.1% below, no structure, momentum
    check("price 0.1% below EMA50 is ALLOWED (was hard-rejected before)",
          _dma_should_reject_long(99.9, 100.0, 105.0, "rs_leader_break") is False)

    print("TEST 3 — live source contains the softening + liveness tokens")
    src = open(os.path.join(HERE, "..", "services", "enhanced_scanner.py"),
               encoding="utf-8").read()
    check("A7 liveness marker present in source", "A7 SCAN-LOOP LIVENESS FIX" in src)
    check("loop task spawned before hydrate await in start()",
          src.index("self._scan_task = asyncio.create_task(self._scan_loop())")
          < src.index("await self._hydrate_carry_forward_alerts_from_mongo()"))
    check("A7 DMA softened marker present", "A7 SOFTENED" in src)
    check("DMA buffer env knob present", "DMA_LONG_BUFFER_PCT" in src)
    check("DMA structure-aware token present", "_struct_up" in src)
    check("DMA pullback-exempt set present", "_dma_pullback_exempt" in src)


async def _main():
    await test_start_spawns_loop_before_hydrate()
    test_dma_truth_table()
    print()
    if _failures:
        print(f"{FAIL} {len(_failures)} check(s) FAILED: {_failures}")
        sys.exit(1)
    print(f"{PASS} ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(_main())
