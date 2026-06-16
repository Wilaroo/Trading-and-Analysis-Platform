#!/usr/bin/env python3
"""patch_v320_daily_bar_premarket_gate.py  —  v19.34.320 patcher  (2026-06-16)

Inserts a pre-RTH daily-bar setup gate at the top of
`OpportunityEvaluator.evaluate_opportunity()` — immediately BEFORE the
existing v19.34.173 F-gate block. Suppresses entries that consume
today's (immature) daily bar before the configured ET cutoff.

GATING LOGIC:
  if  now_ET.time < V320_DAILY_BAR_CUTOFF_ET  AND
      ( setup_type in V320_DAILY_BAR_SETUPS  OR
        trade_style in V320_DAILY_BAR_STYLES ) :
      → policy = block / observe / off
      → block: record_rejection(reason="v320_daily_bar_premarket_gate"),
                return None
      → observe: log only, allow through
      → off: skip the gate

ENV KNOBS (all optional; safe defaults):
  V320_DAILY_BAR_GATE_POLICY   default "block"   (values: block|observe|off)
  V320_DAILY_BAR_CUTOFF_ET     default "10:00"   (HH:MM in America/New_York)
  V320_DAILY_BAR_STYLES        default "multi_day,swing,position,investment"
  V320_DAILY_BAR_SETUPS        default "daily_breakout,rs_leader_break,
                                         stage_2_breakout,power_trend_stack,
                                         pocket_pivot,three_week_tight,
                                         accumulation_entry,daily_squeeze"

SAFETY:
  • Anchored edit (no full-file SHA — file is too large/active to hash).
    Asserts the v19.34.173 F-gate comment line exists at a unique
    location BEFORE writing.
  • Self-SHA256 stored in /tmp/v320_gate.applied for idempotency.
  • --check    asserts anchor, prints projected insert.
  • --apply    inserts the gate block + writes a .bak side-file.
  • --rollback removes the gate block by anchor.
  • --status   prints whether gate is present in the file.
"""
from __future__ import annotations
import argparse
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path.home() / "Trading-and-Analysis-Platform"
TARGET = REPO_ROOT / "backend" / "services" / "opportunity_evaluator.py"
MARKER_OPEN = "# ── v19.34.320 — Daily-bar premarket gate ── BEGIN ────────"
MARKER_CLOSE = "# ── v19.34.320 — Daily-bar premarket gate ── END ──────────"
ANCHOR = "# ── v19.34.173 — Setup-grade F-gate ──────────────────────"
APPLIED_STAMP = "/tmp/v320_gate.applied"


GATE_BLOCK = f'''            {MARKER_OPEN}
            # Suppress daily-bar-consuming setups before the cutoff ET
            # time. Today's daily bar isn't mature until the first 30
            # min of RTH have passed (~10:00 ET). Setups whose
            # trade_style ∈ multi_day/swing/position/investment OR
            # setup_type ∈ {{daily_breakout, rs_leader_break, ...}}
            # read TODAY's daily OHLCV → pre-cutoff fires consume
            # incomplete/whippy data.
            #
            # Trades dropped here land in `trade_drops` with reason
            # code `v320_daily_bar_premarket_gate`.
            try:
                import os as _os_v320
                _v320_policy = (_os_v320.environ.get(
                    "V320_DAILY_BAR_GATE_POLICY", "block")
                    or "block").lower().strip()
                if _v320_policy not in ("block", "observe", "off"):
                    _v320_policy = "block"
                if _v320_policy != "off":
                    from zoneinfo import ZoneInfo as _ZI_v320
                    _v320_cutoff = (_os_v320.environ.get(
                        "V320_DAILY_BAR_CUTOFF_ET", "10:00") or "10:00")
                    _h, _m = _v320_cutoff.split(":")
                    _cutoff_min = int(_h) * 60 + int(_m)
                    _now_et = datetime.now(_ZI_v320("America/New_York"))
                    _now_min = _now_et.hour * 60 + _now_et.minute
                    if _now_min < _cutoff_min:
                        _styles_env = _os_v320.environ.get(
                            "V320_DAILY_BAR_STYLES",
                            "multi_day,swing,position,investment")
                        _setups_env = _os_v320.environ.get(
                            "V320_DAILY_BAR_SETUPS",
                            "daily_breakout,rs_leader_break,"
                            "stage_2_breakout,power_trend_stack,"
                            "pocket_pivot,three_week_tight,"
                            "accumulation_entry,daily_squeeze")
                        _v320_styles = {{s.strip().lower() for s in _styles_env.split(",") if s.strip()}}
                        _v320_setups = {{s.strip().lower() for s in _setups_env.split(",") if s.strip()}}
                        _alert_style = (alert.get("trade_style") or "").lower().strip()
                        _alert_setup = (setup_type or "").lower().strip()
                        _hit_style = _alert_style in _v320_styles
                        _hit_setup = _alert_setup in _v320_setups
                        if _hit_style or _hit_setup:
                            if _v320_policy == "block":
                                try:
                                    bot.record_rejection(
                                        symbol=symbol, setup_type=setup_type,
                                        direction=direction_str,
                                        reason_code="v320_daily_bar_premarket_gate",
                                        context={{
                                            "policy": "v19.34.320_premarket_gate",
                                            "cutoff_et": _v320_cutoff,
                                            "now_et": _now_et.strftime("%H:%M"),
                                            "matched_style": _hit_style and _alert_style or None,
                                            "matched_setup": _hit_setup and _alert_setup or None,
                                        }},
                                    )
                                except Exception:
                                    pass
                                logger.info(
                                    "🚫 [v19.34.320] daily-bar gate BLOCK "
                                    "%s/%s (style=%s, setup=%s, now=%s ET, cutoff=%s ET)",
                                    symbol, setup_type, _alert_style or "-",
                                    _alert_setup or "-",
                                    _now_et.strftime("%H:%M"), _v320_cutoff,
                                )
                                return None
                            elif _v320_policy == "observe":
                                logger.info(
                                    "👁️ [v19.34.320 OBSERVE] daily-bar gate would BLOCK "
                                    "%s/%s (style=%s, setup=%s, now=%s ET)",
                                    symbol, setup_type, _alert_style or "-",
                                    _alert_setup or "-", _now_et.strftime("%H:%M"),
                                )
            except Exception as _v320_err:
                logger.debug("v320 daily-bar gate threw (allowing through): %s", _v320_err)
            {MARKER_CLOSE}

'''


def _self_sha256():
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_target():
    if not TARGET.exists():
        print(f"ERROR: target missing: {TARGET}")
        sys.exit(1)
    return TARGET.read_text(encoding="utf-8")


def cmd_check():
    body = _read_target()
    print(f"  target: {TARGET}")
    print(f"  size:   {len(body):,} chars")

    if MARKER_OPEN in body:
        print("  ❌ ALREADY APPLIED — gate marker present. Use --rollback to remove.")
        sys.exit(0)
    if ANCHOR not in body:
        print(f"  ❌ ANCHOR NOT FOUND: {ANCHOR!r}")
        print("     (The v19.34.173 F-gate comment line is the canonical anchor.")
        print("      File may have drifted from /app expectation.)")
        sys.exit(2)
    anchor_count = body.count(ANCHOR)
    if anchor_count != 1:
        print(f"  ❌ ANCHOR NOT UNIQUE: found {anchor_count}× — refusing to write.")
        sys.exit(3)
    idx = body.index(ANCHOR)
    print(f"  ✓ anchor found at char offset {idx:,}")
    print(f"  ✓ will INSERT {len(GATE_BLOCK):,} chars immediately before anchor.")
    # Show 6 lines of context
    pre = body[max(0, idx-200):idx]
    post = body[idx:idx+200]
    print("\n  --- context before insert ---")
    for ln in pre.splitlines()[-3:]:
        print(f"     {ln}")
    print(f"     {'>>>>>>>>>>>>>>>>> INSERT HERE <<<<<<<<<<<<<<<<<'}")
    for ln in post.splitlines()[:3]:
        print(f"     {ln}")
    print("\n  re-run with --apply to write.")


def cmd_apply():
    body = _read_target()
    if MARKER_OPEN in body:
        print("  ALREADY APPLIED. No-op.")
        return
    if ANCHOR not in body or body.count(ANCHOR) != 1:
        print("  ABORT: anchor missing or not unique. Run --check for detail.")
        sys.exit(2)
    new = body.replace(ANCHOR, GATE_BLOCK + "            " + ANCHOR, 1)
    bak = TARGET.with_suffix(
        TARGET.suffix + ".bak." +
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new, encoding="utf-8")
    Path(APPLIED_STAMP).write_text(
        f"sha256={_self_sha256()}\napplied_at={_now_iso()}\nbackup={bak}\n")
    print(f"  ✓ wrote {TARGET} ({len(new):,} chars)")
    print(f"  ✓ backup at {bak.name}")
    print(f"  ✓ stamp at {APPLIED_STAMP}")
    print("\n  NEXT STEPS:")
    print("    1) restart backend so hot-reload picks up:")
    print("       sudo supervisorctl restart backend")
    print("    2) verify gate live: tail backend logs for `[v19.34.320]`")
    print("    3) if anything looks off → --rollback")


def cmd_rollback():
    body = _read_target()
    if MARKER_OPEN not in body or MARKER_CLOSE not in body:
        print("  no gate markers found — nothing to roll back.")
        return
    pattern = re.compile(
        r"            " + re.escape(MARKER_OPEN) +
        r".*?" + re.escape(MARKER_CLOSE) + r"\n\n",
        re.DOTALL,
    )
    new = pattern.sub("", body, count=1)
    if new == body:
        print("  WARNING: pattern didn't match; markers present but bracket malformed.")
        sys.exit(2)
    bak = TARGET.with_suffix(
        TARGET.suffix + ".bak_rollback." +
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new, encoding="utf-8")
    try:
        os.remove(APPLIED_STAMP)
    except FileNotFoundError:
        pass
    print(f"  ✓ rolled back. backup of patched version at {bak.name}")


def cmd_status():
    body = _read_target()
    present = MARKER_OPEN in body
    print(f"  v320 gate present in file: {present}")
    if os.path.exists(APPLIED_STAMP):
        print(f"  stamp:\n{Path(APPLIED_STAMP).read_text()}")
    if present:
        idx = body.index(MARKER_OPEN)
        block_end = body.index(MARKER_CLOSE) + len(MARKER_CLOSE)
        print(f"  gate block spans char {idx:,} → {block_end:,} "
              f"({block_end - idx:,} chars)")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.check:
        cmd_check()
    elif args.apply:
        cmd_apply()
    elif args.rollback:
        cmd_rollback()
    elif args.status:
        cmd_status()


if __name__ == "__main__":
    main()
