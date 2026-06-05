#!/usr/bin/env python3
"""
apply_ib_direct_marketable_limit.py  (SentCom v19.34.283)

Idempotent applier for the "Alert-to-Trade Conversion Leak" fix in
backend/services/ib_direct_service.py :: _place_bracket_two_step.

WHAT IT DOES
  Hunk 1 — Marketable-limit entry:
    Anchors the parent LimitOrder to the LIVE market price pushed THROUGH the
    book by IB_ENTRY_MARKETABLE_SLIP_PCT (default 0.25%) instead of the passive
    alert trigger, so fast/breakout setups actually fill. Falls back to the
    trigger price when live is unavailable. The existing staleness band still
    skips genuinely blown setups.

  Hunk 2 — R-preserve bracket re-anchor:
    After the parent fills, translates the stop + ALL targets by
    (avg_fill - trigger) so the original $risk / R-multiple and every
    multi-target scale-out distance stay intact.

SAFETY
  - Fully idempotent: re-running is a no-op once 'v19.34.283' markers exist.
  - Refuses to write unless BOTH hunks match their exact pre-patch anchors.
  - Writes a timestamped .bak before modifying.
  - py_compile-validates the result; auto-restores the backup on failure.

USAGE
  python3 apply_ib_direct_marketable_limit.py            # default path
  python3 apply_ib_direct_marketable_limit.py --file /path/to/ib_direct_service.py
  python3 apply_ib_direct_marketable_limit.py --dry-run  # show plan, write nothing
"""
import argparse
import os
import py_compile
import shutil
import sys
import time

DEFAULT_FILE = "/app/backend/services/ib_direct_service.py"
MARKER = "v19.34.283"

# ── Hunk 1 ────────────────────────────────────────────────────────────────
H1_OLD = """            # v19.34.42 -- round entry to IB minTick.
            _mt_p = await self._resolve_min_tick(contract)
            parent_order = LimitOrder(parent_action, qty,
                                      self._round_to_tick(entry_price, _mt_p))
"""

H1_NEW = """            # v19.34.42 -- round entry to IB minTick.
            _mt_p = await self._resolve_min_tick(contract)
            # v19.34.283 — marketable-limit entry: anchor to LIVE price + a small
            # offset THROUGH the market (instead of the passive alert trigger) so
            # fast/breakout setups actually fill. Capped by IB_ENTRY_MARKETABLE_
            # SLIP_PCT (default 0.25%) so a bad print can't fill arbitrarily far.
            # Falls back to the trigger price if live is unavailable. The staleness
            # band above still skips genuinely blown setups.
            _entry_px = entry_price
            try:
                _slip = float(_os39.environ.get('IB_ENTRY_MARKETABLE_SLIP_PCT', '0.25')) / 100.0
            except Exception:
                _slip = 0.0025
            if _live_px > 0 and _slip > 0:
                _entry_px = _live_px * (1.0 + _slip) if parent_action == "BUY" else _live_px * (1.0 - _slip)
                logger.warning(
                    "[v19.34.283 marketable] %s %s marketable-limit @ %.4f (live %.4f +/- %.2f%%, trigger was %.4f)",
                    symbol, parent_action, _entry_px, _live_px, _slip * 100.0, entry_price,
                )
            parent_order = LimitOrder(parent_action, qty,
                                      self._round_to_tick(_entry_px, _mt_p))
"""

# ── Hunk 2 ────────────────────────────────────────────────────────────────
H2_OLD = """            _orig_shares = trade.shares
            trade.shares = filled_qty
            try:
                oca_result = await self.place_oca_stop_target(
"""

H2_NEW = """            _orig_shares = trade.shares
            trade.shares = filled_qty
            # v19.34.283 — preserve original $risk / R: shift stop + all targets by
            # the fill-vs-trigger delta (pure translation keeps every risk/reward
            # distance intact, multi-target scale-outs included).
            try:
                if avg_fill and avg_fill > 0 and entry_price and entry_price > 0:
                    _delta = avg_fill - entry_price
                    if abs(_delta) > 1e-9:
                        if getattr(trade, "stop_price", None):
                            trade.stop_price = round(float(trade.stop_price) + _delta, 4)
                        _tps = getattr(trade, "target_prices", None) or []
                        if _tps:
                            trade.target_prices = [round(float(t) + _delta, 4) for t in _tps]
                        logger.warning(
                            "[v19.34.283 R-preserve] %s fill=%.4f trigger=%.4f delta=%.4f -> stop=%s targets=%s",
                            symbol, avg_fill, entry_price, _delta,
                            getattr(trade, "stop_price", None), getattr(trade, "target_prices", None),
                        )
            except Exception as _ra_err:
                logger.warning("[v19.34.283 R-preserve] %s skipped: %s", symbol, _ra_err)
            try:
                oca_result = await self.place_oca_stop_target(
"""

HUNKS = [("Hunk 1 (marketable-limit entry)", H1_OLD, H1_NEW),
         ("Hunk 2 (R-preserve re-anchor)", H2_OLD, H2_NEW)]


def log(msg):
    print(f"[v283-applier] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = args.file
    if not os.path.isfile(path):
        log(f"ERROR: file not found: {path}")
        return 2

    with open(path, "r", encoding="utf-8") as fh:
        content = original = fh.read()

    # ── Idempotency ──
    if MARKER in content:
        log(f"Already applied — '{MARKER}' markers present. No changes made.")
        return 0

    # ── Validate every anchor BEFORE touching anything ──
    for name, old, _new in HUNKS:
        n = content.count(old)
        if n != 1:
            log(f"ERROR: {name} anchor matched {n} times (expected exactly 1).")
            log("       File differs from expected pre-patch state. Aborting — nothing written.")
            return 3

    # ── Apply in memory ──
    for name, old, new in HUNKS:
        content = content.replace(old, new, 1)
        log(f"staged: {name}")

    if content.count(MARKER) < 2:
        log("ERROR: post-apply marker count unexpectedly low. Aborting.")
        return 4

    if args.dry_run:
        log("DRY-RUN: both hunks matched and would apply cleanly. No file written.")
        return 0

    # ── Backup + write ──
    bak = f"{path}.bak.v283.{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, bak)
    log(f"backup written: {bak}")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    log("file written.")

    # ── Validate syntax; auto-restore on failure ──
    try:
        py_compile.compile(path, doraise=True)
        log("py_compile OK.")
    except py_compile.PyCompileError as e:
        log(f"ERROR: py_compile failed: {e}")
        shutil.copy2(bak, path)
        log("restored original from backup. No net change.")
        return 5

    log("SUCCESS — v19.34.283 marketable-limit + R-preserve applied.")
    log("Restart the backend service to activate (e.g. your supervisor/systemd unit).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
