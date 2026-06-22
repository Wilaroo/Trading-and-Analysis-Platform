#!/usr/bin/env python3
"""
patch_a7_scanloop_dma.py  —  2026-06-22  (SentCom / DGX Spark)

Two surgical, drift-guarded edits to backend/services/enhanced_scanner.py:

  EDIT 1 — SCAN-LOOP LIVENESS FIX (P0)
    Root cause: EnhancedBackgroundScanner.start() awaited the (blocking
    pymongo) carry-forward hydrate BEFORE setting `_running=True` and
    creating the `_scan_task`. At server boot start() is wrapped in
    `asyncio.wait_for(..., timeout=5.0)`; a slow hydrate let wait_for
    cancel start() mid-hydrate, so the loop task was never created and the
    scanner stayed permanently dead (running=False, scan_count=0) while
    still showing the alerts the hydrate had already loaded.
    Fix: flip `_running` and spawn `_scan_task` FIRST; the hydrate runs
    after the loop is already live, so its fate can't strand the scanner.

  EDIT 2 — DMA DIRECTIONAL FILTER SOFTENING (P1)
    The hard binary "reject any swing/position LONG whose last price is
    even $0.01 below EMA50 (position longs below SMA200)" killed textbook
    buy-the-dip / basing entries inside healthy uptrends. Softened on:
      1. Proximity buffer  (DMA_LONG_BUFFER_PCT, default 2%)
      2. Structure-aware   (never reject a long while EMA50 > SMA200)
      3. Pullback-setup exemption (setups whose thesis IS a pullback to
         the MA are not gated by that MA)

SAFE BY CONSTRUCTION:
  * Each edit is located by UNIQUE start/end anchors and the extracted
    span's sha256 is verified against an expected value. ANY drift in the
    targeted code -> the script ABORTS without writing.
  * Idempotent: re-running after a successful apply is a no-op.
  * Writes a .bak alongside the file and AST-compiles the result before
    committing. If compilation fails, the original is restored.

Run from the repo root:
    PYTHONPATH=backend .venv/bin/python scripts/patch_a7_scanloop_dma.py
"""
import hashlib
import os
import sys
import ast
import shutil

CANDIDATE_PATHS = [
    "backend/services/enhanced_scanner.py",
    "services/enhanced_scanner.py",
    os.path.join(os.path.dirname(__file__), "..", "backend", "services", "enhanced_scanner.py"),
]

# ---- EDIT 1: start() ---------------------------------------------------
START_BEGIN = "    async def start(self):"
START_END = '        logger.info(f"🚀 Enhanced scanner started - {len(self._watchlist)} symbols, {len(self._enabled_setups)} strategies")'
START_PRE_SHA = "6869042d76f752a3f215ed1d841b1858585eb80e79022f55a1f00ff24f926c41"
START_IDEMPOTENT_MARKER = "A7 SCAN-LOOP LIVENESS FIX"

NEW_START = '''    async def start(self):
        """Start the background scanner"""
        if self._running:
            logger.warning("Enhanced scanner already running")
            return

        # 2026-06-22 A7 SCAN-LOOP LIVENESS FIX — flip _running and SPAWN the
        # scan-loop task FIRST, *before* the carry-forward hydrate. Previously
        # start() awaited the (blocking pymongo) hydrate before setting
        # _running / creating _scan_task. At server boot start() is wrapped in
        # `asyncio.wait_for(..., timeout=5.0)`; a slow hydrate (Atlas latency /
        # cold cache) let wait_for cancel start() mid-hydrate, so _running was
        # never set and the loop task never created — the scanner stayed
        # permanently dead (running=False, scan_count=0) while still showing
        # the alerts the hydrate had already loaded. Creating the loop task
        # first makes the loop independent of (and immune to) the hydrate.
        self._running = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info(f"🚀 Enhanced scanner started - {len(self._watchlist)} symbols, {len(self._enabled_setups)} strategies")

        # 2026-05-05 v19.34.6 — Re-hydrate carry-forward gameplan alerts from
        # Mongo so the morning operator workflow has yesterday's after-hours
        # plan in `_live_alerts`. Now runs AFTER the loop is live; if it is
        # slow or cancelled the scan loop keeps running unaffected.
        try:
            await self._hydrate_carry_forward_alerts_from_mongo()
        except Exception as _hydrate_err:
            logger.debug(f"v19.34.6 carry-forward hydrate skipped: {_hydrate_err}")'''

# ---- EDIT 2: DMA directional filter -----------------------------------
DMA_BEGIN = "        # === DMA DIRECTIONAL FILTER ==="
DMA_END = '            logger.debug(f"DMA filter check: {e}")'
DMA_PRE_SHA = "6df9cbf31481761c27ceb6b520d46106c8881f34ddd95ef0400044bd8bee7b3b"
DMA_IDEMPOTENT_MARKER = "A7 SOFTENED"

NEW_DMA = '''        # === DMA DIRECTIONAL FILTER (2026-06-22 A7 SOFTENED) ===
        # Longer-horizon holds (swing / multi-day / position) prefer trend
        # alignment, but the original gate HARD-rejected any long whose last
        # price sat even $0.01 below EMA50 (and position longs below SMA200),
        # killing textbook buy-the-dip / basing entries in healthy uptrends.
        # Softened on three axes:
        #   1. PROXIMITY BUFFER — only reject when price is MORE than
        #      DMA_LONG_BUFFER_PCT below the MA (default 2%).
        #   2. STRUCTURE-AWARE — never reject a LONG while the daily structure
        #      is constructive (EMA50 > SMA200 = pullback within an uptrend,
        #      not a falling knife). Mirror for shorts (EMA50 < SMA200).
        #   3. PULLBACK-SETUP EXEMPTION — setups whose entry thesis IS a
        #      pullback/reclaim to the MA are never gated by that same MA.
        try:
            trade_style = alert.trade_style or "intraday"
            direction = getattr(alert, 'direction_bias', 'long')

            if trade_style in ("swing", "multi_day", "position"):
                try:
                    _dma_buf = float(os.environ.get("DMA_LONG_BUFFER_PCT", "2.0")) / 100.0
                except (TypeError, ValueError):
                    _dma_buf = 0.02
                _dma_pullback_exempt = {
                    "accumulation_entry", "three_week_tight", "vwap_bounce",
                    "second_chance", "rubber_band", "backside", "mean_reversion",
                    "first_vwap_pullback", "pullback",
                }
                _setup_exempt = alert.setup_type in _dma_pullback_exempt

                snapshot = await self.technical_service.get_technical_snapshot(alert.symbol)
                if snapshot and hasattr(snapshot, 'ema_50') and snapshot.ema_50 > 0:
                    price = snapshot.last or alert.trigger_price
                    _sma200 = getattr(snapshot, 'sma_200', 0) or 0
                    _struct_up = _sma200 > 0 and snapshot.ema_50 > _sma200
                    _struct_dn = _sma200 > 0 and snapshot.ema_50 < _sma200
                    _long_floor = snapshot.ema_50 * (1.0 - _dma_buf)
                    _short_ceil = snapshot.ema_50 * (1.0 + _dma_buf)
                    _bufpct = _dma_buf * 100.0
                    if (direction == "long" and price < _long_floor
                            and not _struct_up and not _setup_exempt):
                        msg = f"DMA Filter: Skipping {alert.symbol} {alert.setup_type} LONG swing — price ${price:.2f} >{_bufpct:.1f}% below EMA50 ${snapshot.ema_50:.2f} (no uptrend structure)"
                        logger.info(msg)
                        await self._emit_scanner_thought(
                            symbol=alert.symbol, kind="reject",
                            text=f"🚫 LONG {alert.setup_type} skipped — ${price:.2f} >{_bufpct:.1f}% below EMA50 ${snapshot.ema_50:.2f}",
                            setup_type=alert.setup_type, direction="long",
                            filter="dma_ema50_long_swing",
                            price=price, ema_50=snapshot.ema_50,
                        )
                        return
                    elif (direction == "short" and price > _short_ceil
                            and not _struct_dn and not _setup_exempt):
                        msg = f"DMA Filter: Skipping {alert.symbol} {alert.setup_type} SHORT swing — price ${price:.2f} >{_bufpct:.1f}% above EMA50 ${snapshot.ema_50:.2f} (no downtrend structure)"
                        logger.info(msg)
                        await self._emit_scanner_thought(
                            symbol=alert.symbol, kind="reject",
                            text=f"🚫 SHORT {alert.setup_type} skipped — ${price:.2f} >{_bufpct:.1f}% above EMA50 ${snapshot.ema_50:.2f}",
                            setup_type=alert.setup_type, direction="short",
                            filter="dma_ema50_short_swing",
                            price=price, ema_50=snapshot.ema_50,
                        )
                        return

                # Position/investment: SMA200 gate (same buffer + exemption).
                if trade_style == "position":
                    if snapshot and hasattr(snapshot, 'sma_200') and snapshot.sma_200 > 0:
                        price = snapshot.last or alert.trigger_price
                        _bufpct = _dma_buf * 100.0
                        _p_floor = snapshot.sma_200 * (1.0 - _dma_buf)
                        _p_ceil = snapshot.sma_200 * (1.0 + _dma_buf)
                        if (direction == "long" and price < _p_floor
                                and not _setup_exempt):
                            msg = f"DMA Filter: Skipping {alert.symbol} {alert.setup_type} LONG investment — price ${price:.2f} >{_bufpct:.1f}% below SMA200 ${snapshot.sma_200:.2f}"
                            logger.info(msg)
                            await self._emit_scanner_thought(
                                symbol=alert.symbol, kind="reject",
                                text=f"🚫 LONG investment skipped — ${price:.2f} >{_bufpct:.1f}% below SMA200 ${snapshot.sma_200:.2f}",
                                setup_type=alert.setup_type, direction="long",
                                filter="dma_sma200_long_investment",
                                price=price, sma_200=snapshot.sma_200,
                            )
                            return
                        elif (direction == "short" and price > _p_ceil
                                and not _setup_exempt):
                            msg = f"DMA Filter: Skipping {alert.symbol} {alert.setup_type} SHORT investment — price ${price:.2f} >{_bufpct:.1f}% above SMA200 ${snapshot.sma_200:.2f}"
                            logger.info(msg)
                            await self._emit_scanner_thought(
                                symbol=alert.symbol, kind="reject",
                                text=f"🚫 SHORT investment skipped — ${price:.2f} >{_bufpct:.1f}% above SMA200 ${snapshot.sma_200:.2f}",
                                setup_type=alert.setup_type, direction="short",
                                filter="dma_sma200_short_investment",
                                price=price, sma_200=snapshot.sma_200,
                            )
                            return
        except Exception as e:
            logger.debug(f"DMA filter check: {e}")'''


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _locate_span(content: str, begin: str, end: str):
    i = content.find(begin)
    if i == -1:
        return None
    j = content.find(end, i)
    if j == -1:
        return None
    j_end = j + len(end)
    return i, j_end, content[i:j_end]


def _apply_edit(content, label, begin, end, pre_sha, new_block, idem_marker):
    if idem_marker in content:
        loc = _locate_span(content, begin, end)
        # Already patched if the new marker lives inside the targeted span.
        print(f"  [{label}] idempotent marker present — already applied, skipping.")
        return content, "skipped"
    loc = _locate_span(content, begin, end)
    if loc is None:
        print(f"  [{label}] ABORT — could not locate span anchors. No changes written.")
        return None, "abort"
    i, j_end, span = loc
    actual = _sha(span)
    if actual != pre_sha:
        print(f"  [{label}] ABORT — span sha drift.\n"
              f"      expected {pre_sha}\n      actual   {actual}\n"
              f"    The live code differs from what this patcher targets. "
              f"No changes written.")
        return None, "abort"
    new_content = content[:i] + new_block + content[j_end:]
    print(f"  [{label}] span verified ({pre_sha[:12]}…) -> replaced "
          f"({len(span)}B -> {len(new_block)}B).")
    return new_content, "applied"


def main():
    path = next((p for p in CANDIDATE_PATHS if os.path.isfile(p)), None)
    if not path:
        print("ERROR: enhanced_scanner.py not found. Run from the repo root.")
        sys.exit(2)
    path = os.path.abspath(path)
    original = open(path, encoding="utf-8").read()
    pre_file_sha = _sha(original)
    print(f"Target: {path}")
    print(f"PRE  whole-file sha256: {pre_file_sha}")

    content = original
    results = {}
    content, results["start"] = _apply_edit(
        content, "EDIT-1 start()", START_BEGIN, START_END,
        START_PRE_SHA, NEW_START, START_IDEMPOTENT_MARKER)
    if content is None:
        sys.exit(1)
    content, results["dma"] = _apply_edit(
        content, "EDIT-2 DMA filter", DMA_BEGIN, DMA_END,
        DMA_PRE_SHA, NEW_DMA, DMA_IDEMPOTENT_MARKER)
    if content is None:
        sys.exit(1)

    if all(v == "skipped" for v in results.values()):
        print("Nothing to do — both edits already present. ✅")
        sys.exit(0)

    # AST compile-check before committing.
    try:
        ast.parse(content)
    except SyntaxError as e:
        print(f"ABORT — patched content failed to parse: {e}. No changes written.")
        sys.exit(1)

    bak = path + ".a7.bak"
    shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    post_file_sha = _sha(content)
    print(f"Backup written: {bak}")
    print(f"POST whole-file sha256: {post_file_sha}")
    print("✅ patch_a7 applied. Restart the backend to load the fix:")
    print("     sudo systemctl restart <your-backend-service>   # or your usual restart")
    print("   Then verify:")
    print("     curl -s http://localhost:8001/api/live-scanner/status | python3 -m json.tool")


if __name__ == "__main__":
    main()
