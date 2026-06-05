#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_marketable_entry_v283.py — IDEMPOTENT applier for v19.34.283
"marketable-limit entry + R-preserving stop/target re-anchor".

Fixes the entry-fill leak (alert_stale + parent_not_filled + reaped zombies):
  1. ib_direct_service._place_bracket_two_step: place the parent entry as a
     MARKETABLE LIMIT anchored at LIVE price +/- IB_ENTRY_MARKETABLE_SLIP_PCT
     (default 0.25%) instead of a passive limit at the stale alert trigger, so
     fast/breakout setups actually fill. Staleness band still skips blown setups.
  2. After fill, shift stop + all targets by the fill-vs-trigger delta to
     preserve the original $risk / R-multiple (multi-target safe).
  3. (cleanup) split two pre-existing semicolon statements (lint hygiene).
  4. writes backend/scripts/probe_entry_fill_health.py

Independent of v281/v282/v282b (different file). Idempotent.

RUN ON DGX (repo root):
    .venv/bin/python /tmp/apply_marketable_entry_v283.py --dry-run
    .venv/bin/python /tmp/apply_marketable_entry_v283.py
then:
    ./start_backend.sh --force
    .venv/bin/python backend/scripts/probe_entry_fill_health.py
"""
import argparse
import os
import shutil
import sys

BAK_SUFFIX = ".bak.mktentry0605"
REPO = os.getcwd()
IBD = os.path.join(REPO, "backend/services/ib_direct_service.py")
PROBE = os.path.join(REPO, "backend/scripts/probe_entry_fill_health.py")

EDITS = [
    # 1) marketable-limit entry
    ("v19.34.283 marketable",
'''            # v19.34.42 -- round entry to IB minTick.
            _mt_p = await self._resolve_min_tick(contract)
            parent_order = LimitOrder(parent_action, qty,
                                      self._round_to_tick(entry_price, _mt_p))''',
'''            # v19.34.42 -- round entry to IB minTick.
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
                                      self._round_to_tick(_entry_px, _mt_p))'''),

    # 2) R-preserving re-anchor
    ("v19.34.283 R-preserve",
'''            _orig_shares = trade.shares
            trade.shares = filled_qty
            try:
                oca_result = await self.place_oca_stop_target(''',
'''            _orig_shares = trade.shares
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
                oca_result = await self.place_oca_stop_target('''),

    # 3) lint hygiene — split semicolons
    ('''                    terminal_status = "filled"
                    break''',
'''                if status == "filled" and filled_qty > 0:
                    terminal_status = "filled"; break
                if status in ("cancelled", "apicancelled", "inactive"):
                    terminal_status = status; break
                await asyncio.sleep(0.5)''',
'''                if status == "filled" and filled_qty > 0:
                    terminal_status = "filled"
                    break
                if status in ("cancelled", "apicancelled", "inactive"):
                    terminal_status = status
                    break
                await asyncio.sleep(0.5)'''),
]


PROBE_SRC = r'''#!/usr/bin/env python3
"""
probe_entry_fill_health.py  (v19.34.283) — READ-ONLY.

Reports today's entry fill-rate health: how many auto-submitted entries filled
vs were rejected, and segments the rejects by reason. Run before/after the v283
marketable-limit fix to measure the recovery.

Usage (DGX, repo root):
    .venv/bin/python backend/scripts/probe_entry_fill_health.py
    .venv/bin/python backend/scripts/probe_entry_fill_health.py 2026-06-05
"""
import collections
import sys
from datetime import datetime, timezone

from pymongo import MongoClient


def _load_env():
    env = {}
    for line in open("backend/.env"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def _sub_reason(notes):
    n = str(notes or "")
    if "[REJECTED: " in n:
        return n.split("[REJECTED: ")[1].split("]")[0].split(":")[0]
    return None


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    env = _load_env()
    d = MongoClient(env["MONGO_URL"])[env.get("DB_NAME", "tradecommand")]
    rows = list(d["bot_trades"].find({"created_at": {"$gte": day}}))

    by_status = collections.Counter(str(r.get("status")) for r in rows)
    rejected = [r for r in rows if str(r.get("status")) == "rejected"]
    by_close = collections.Counter(str(r.get("close_reason")) for r in rejected)
    sub = collections.Counter(
        _sub_reason(r.get("notes")) or "n/a"
        for r in rejected if str(r.get("close_reason")) == "broker_rejected"
    )

    filled = by_status.get("filled", 0) + by_status.get("open", 0) + by_status.get("closed", 0) + by_status.get("partial", 0)
    submitted = filled + len(rejected)
    fill_rate = (filled / submitted * 100.0) if submitted else 0.0
    recoverable = by_close.get("stale_pending_auto_reaper", 0) + sub.get("parent_not_filled", 0)

    print(f"\n=== entry fill health — {day} ===")
    print(f"trades created today : {len(rows)}")
    print(f"by status            : {dict(by_status)}")
    print(f"fill rate            : {filled}/{submitted} = {fill_rate:.1f}%")
    print(f"rejected total       : {len(rejected)}")
    print(f"  by close_reason    : {dict(by_close)}")
    print(f"  broker_rejected ->  : {dict(sub)}")
    print(f"est. recoverable by v283 (parent_not_filled + reaped): {recoverable}")
    print("  (alert_stale stays skipped by design — genuinely blown setups)\n")


if __name__ == "__main__":
    main()
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    if not os.path.isfile(IBD):
        print(f"[FATAL] not found: {IBD}\n  -> run from repo root (~/Trading-and-Analysis-Platform)")
        sys.exit(2)

    with open(IBD, "r", encoding="utf-8") as f:
        text = f.read()
    orig = text
    applied = skipped = errors = 0
    for marker, old, new in EDITS:
        if marker in text:
            print(f"  [skip] already applied :: {marker[:46]}")
            skipped += 1
            continue
        if old not in text:
            print(f"  [ERROR] anchor not found :: {marker[:46]}")
            errors += 1
            continue
        text = text.replace(old, new, 1)
        print(f"  [apply] {marker[:46]}")
        applied += 1

    if errors:
        print(f"\ndone — applied={applied} skipped={skipped} errors={errors}")
        print("  ! anchors missing — NOTHING written.")
        sys.exit(1)

    if text != orig and not dry:
        bak = IBD + BAK_SUFFIX
        if not os.path.exists(bak):
            shutil.copy2(IBD, bak)
            print(f"  [backup] {bak}")
        with open(IBD, "w", encoding="utf-8") as f:
            f.write(text)

    cur = open(PROBE, encoding="utf-8").read() if os.path.exists(PROBE) else None
    if cur == PROBE_SRC:
        print("  [skip] probe already current")
    elif not dry:
        os.makedirs(os.path.dirname(PROBE), exist_ok=True)
        with open(PROBE, "w", encoding="utf-8") as f:
            f.write(PROBE_SRC)
        print(f"  [write] {PROBE}")
    else:
        print(f"  [would-write] {PROBE}")

    tag = "[DRY-RUN] " if dry else ""
    print(f"\n{tag}done — applied={applied} skipped={skipped} errors={errors}")
    if not dry and applied:
        print("  -> restart:  ./start_backend.sh --force")
        print("  -> monitor:  .venv/bin/python backend/scripts/probe_entry_fill_health.py")


if __name__ == "__main__":
    main()
