#!/usr/bin/env python3
"""
diag_setup_inventory.py  (READ-ONLY)
====================================
Full census of every setup the bot defines vs what's actually firing vs how
it's categorized — to surface DORMANT detectors, ORPHAN/mislabeled labels,
STYLE-UNMAPPED setups, and VARIANT SPLITS (base name enabled but trades stored
under _long/_short variants → fragmented stats).

Cross-references three sources:
  • CODE   — enhanced_scanner `_enabled_setups` (the 38 active detectors)
  • DB     — distinct setup_type in live_alerts (30d) + bot_trades (90d)
  • STYLE  — trade_style_classifier.SETUP_TO_STYLE (+ resolve_trade_style)

Mongo only. Run from repo root + venv:
    .venv/bin/python backend/scripts/diag_setup_inventory.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# enhanced_scanner._enabled_setups (line ~950) — the ACTIVE detector set.
# Hardcoded because importing the scanner spins up IB/heavy deps.
ENABLED = {
    "first_vwap_pullback", "first_move_up", "first_move_down", "bella_fade",
    "back_through_open", "up_through_open", "opening_drive",
    "orb", "hitchhiker", "gap_give_go", "gap_pick_roll",
    "spencer_scalp", "second_chance", "backside", "off_sides", "fashionably_late",
    "rubber_band", "vwap_bounce", "vwap_fade", "tidal_wave", "mean_reversion",
    "big_dog", "puppy_dog", "9_ema_scalp", "abc_scalp", "squeeze",
    "hod_breakout", "time_of_day_fade",
    "breaking_news", "volume_capitulation", "range_break", "breakout",
    "gap_fade", "chart_pattern", "vwap_continuation", "premarket_high_break",
    "bouncy_ball", "the_3_30_trade",
}
_SUFFIXES = ("_scalp_long", "_scalp_short", "_long", "_short", "_scalp",
             "_confirmed", "_intraday")


def _base(name):
    for s in _SUFFIXES:
        if name.endswith(s):
            return name[: -len(s)]
    return name


def _load_env():
    cands = [Path.cwd() / "backend" / ".env", Path.cwd() / ".env"]
    try:
        cands.append(Path(__file__).resolve().parents[1] / ".env")
    except NameError:
        pass
    for c in cands:
        if c.exists():
            for line in c.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)[os.environ["DB_NAME"]]


def _bootstrap_path():
    for cand in (Path.cwd() / "backend", Path.cwd()):
        if (cand / "services" / "trade_style_classifier.py").exists():
            sys.path.insert(0, str(cand)); return


def main():
    _bootstrap_path(); _load_env()
    try:
        from services.trade_style_classifier import SETUP_TO_STYLE
    except Exception:
        SETUP_TO_STYLE = {}
    db = _db()
    a30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    t90 = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    print(f"\n{'#'*104}\n#  SETUP INVENTORY — code vs DB vs style-map\n{'#'*104}")
    print(f"enabled detectors (code): {len(ENABLED)}   |   style-map entries: {len(SETUP_TO_STYLE)}")

    # DB census
    al = defaultdict(lambda: [0, None])   # setup -> [count, last]
    for r in db["live_alerts"].find({"created_at": {"$gte": a30}},
                                    {"_id": 0, "setup_type": 1, "created_at": 1}):
        st = r.get("setup_type")
        if st:
            al[st][0] += 1
            al[st][1] = max(al[st][1] or "", str(r.get("created_at") or ""))
    tr = defaultdict(lambda: [0, 0, None])  # setup -> [count, legit_bot_fired, last]
    for r in db["bot_trades"].find({"closed_at": {"$gte": t90}},
                                   {"_id": 0, "setup_type": 1, "entered_by": 1, "closed_at": 1}):
        st = r.get("setup_type")
        if st:
            tr[st][0] += 1
            if str(r.get("entered_by") or "").lower() == "bot_fired":
                tr[st][1] += 1
            tr[st][2] = max(tr[st][2] or "", str(r.get("closed_at") or ""))

    allnames = set(ENABLED) | set(al) | set(tr) | set(SETUP_TO_STYLE)

    def style_of(name):
        if name in SETUP_TO_STYLE:
            return SETUP_TO_STYLE[name]
        b = _base(name)
        return SETUP_TO_STYLE.get(b, "UNMAPPED→unknown")

    # ── A. enabled & firing ─────────────────────────────────────────────
    print(f"\n[A] ENABLED detectors — firing status (alerts 30d / trades 90d)")
    print(f"    {'setup':<24}{'alerts30d':>10}{'trades90d':>10}{'legit':>7}{'style':>14}  last_trade")
    dormant = []
    for name in sorted(ENABLED):
        a = al.get(name, [0, None]); t = tr.get(name, [0, 0, None])
        if a[0] == 0 and t[0] == 0:
            dormant.append(name)
            continue
        print(f"    {name:<24}{a[0]:>10}{t[0]:>10}{t[1]:>7}{style_of(name):>14}  {str(t[2] or '-')[:10]}")
    print(f"\n    ⚠ ENABLED but DORMANT (no alerts AND no trades in window) — {len(dormant)}:")
    print("      " + (", ".join(dormant) if dormant else "(none)"))

    # ── B. firing but NOT enabled ───────────────────────────────────────
    print(f"\n[B] FIRING but NOT in _enabled_setups (orphan labels / variants / mislabeled)")
    print(f"    {'setup':<28}{'alerts30d':>10}{'trades90d':>10}{'legit':>7}{'base→enabled?':>15}{'style':>14}")
    orphans = sorted((set(al) | set(tr)) - ENABLED)
    for name in orphans:
        a = al.get(name, [0, None]); t = tr.get(name, [0, 0, None])
        b = _base(name)
        tag = f"{b}✓" if (b != name and b in ENABLED) else ("—" if b == name else f"{b}✗")
        print(f"    {name:<28}{a[0]:>10}{t[0]:>10}{t[1]:>7}{tag:>15}{style_of(name):>14}")

    # ── C. variant splits ───────────────────────────────────────────────
    print(f"\n[C] VARIANT SPLITS — one base detector, multiple stored variants (fragmented stats)")
    by_base = defaultdict(set)
    for name in (set(al) | set(tr)):
        by_base[_base(name)].add(name)
    found = False
    for base, variants in sorted(by_base.items()):
        if len(variants) > 1:
            found = True
            tot_tr = sum(tr.get(v, [0, 0, None])[0] for v in variants)
            print(f"    base '{base}' (enabled={base in ENABLED}) split across {len(variants)}: "
                  f"{sorted(variants)}  → {tot_tr} trades graded separately")
    if not found:
        print("    (none)")

    # ── D. style-unmapped firing setups ─────────────────────────────────
    print(f"\n[D] STYLE-UNMAPPED firing setups (fall to 'unknown' → wrong horizon/bracket/grade)")
    unmapped = []
    for name in sorted(set(al) | set(tr)):
        if name not in SETUP_TO_STYLE and _base(name) not in SETUP_TO_STYLE:
            unmapped.append((name, al.get(name, [0])[0], tr.get(name, [0])[0]))
    if unmapped:
        for name, a, t in unmapped:
            print(f"    {name:<30} alerts30d={a:<6} trades90d={t}")
    else:
        print("    (none — every firing setup resolves to a style)")

    print(f"\n{'='*104}\nTAKEAWAYS\n{'='*104}")
    print(f"• [A]-dormant = detectors enabled but producing nothing → dead code or broken triggers.")
    print(f"• [B] base→enabled '✓' = a directional/scalp variant whose base IS enabled → the detector")
    print(f"      stores a variant name; stats/grades/style-map keyed on the base will mismatch.")
    print(f"• [C] variant splits fragment sample size (e.g. vwap_fade_long + _short graded as two).")
    print(f"• [D] unmapped → resolve_trade_style returns 'unknown' → default horizon/bracket/sizing.")
    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
