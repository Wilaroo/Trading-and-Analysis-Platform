#!/usr/bin/env python3
"""
diag_v392_blind_subscores.py  —  READ-ONLY TQS blind sub-score coverage diag

Measures, across the persisted `live_alerts` book, how often each "blind"
sub-score is sitting on its DEFAULT value vs. a real measured value:

  • Expected Value — R:R proxy (raw expected_value_r == 0) vs. live expectancy
  • Tape           — else-30 path (alert.tape_score == 0) vs. a real tape read
  • Sector         — sector == 'unknown' / rank 6 default vs. real sector context
  • RVOL           — technical rvol == 1.00 default vs. real relative volume
  • Pattern        — setup_type whose canonical base is NOT in SETUP_BASE_SCORES
                     (→ pattern pinned to 50)

NO WRITES. NO IB CONNECTION. Reads Mongo only. Run from repo root:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v392_blind_subscores.py
"""
import os
import sys
from collections import Counter

sys.path.insert(0, "backend")

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
EPS = 1e-6


def _verdict(blind_pct):
    if blind_pct >= 50:
        return "RED  systemic blind"
    if blind_pct >= 20:
        return "AMBER partial"
    return "GREEN mostly covered"


def main():
    if not MONGO_URL:
        print("MONGO_URL not set in env."); sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=4000)[DB_NAME]

    # canonical taxonomy — reuse the EXACT logic the Setup pillar uses
    try:
        from services.tqs.setup_quality import SetupQualityService, _canonical_base_setup
        BASE = SetupQualityService.SETUP_BASE_SCORES
        canon = _canonical_base_setup
    except Exception as e:
        print(f"[warn] could not import setup taxonomy ({e}); pattern check degraded")
        BASE, canon = {}, (lambda s: (s or "").lower())

    cur = db["live_alerts"].find(
        {"tqs_breakdown": {"$exists": True, "$ne": {}}},
        {"_id": 0, "setup_type": 1, "tape_score": 1, "direction": 1,
         "created_at": 1, "tqs_breakdown": 1},
    ).limit(50000)

    n = 0
    ev_proxy = tape_blind = sector_blind = rvol_default = 0
    setup_counter = Counter()
    pattern_pinned50 = 0
    oldest = newest = None

    for d in cur:
        bd = d.get("tqs_breakdown") or {}
        setup = bd.get("setup") or {}
        tech = bd.get("technical") or {}
        ctx = bd.get("context") or {}
        sraw = setup.get("raw_values") or {}
        traw = tech.get("raw_values") or {}
        craw = ctx.get("raw_values") or {}
        scomp = setup.get("components") or {}
        if not setup and not tech and not ctx:
            continue
        n += 1
        ca = d.get("created_at")
        if ca:
            oldest = ca if oldest is None or ca < oldest else oldest
            newest = ca if newest is None or ca > newest else newest

        # EV proxy
        evr = sraw.get("expected_value_r")
        if evr is None or abs(float(evr)) < EPS:
            ev_proxy += 1
        # Tape (else-30) — alert.tape_score==0 OR component pinned to 30 w/o confirm
        ts = d.get("tape_score")
        if (ts is None or float(ts) <= 0) or (
                scomp.get("tape") == 30 and not sraw.get("tape_confirmation")):
            tape_blind += 1
        # Sector default
        if (craw.get("sector") in (None, "", "unknown")) or craw.get("sector_rank") == 6:
            sector_blind += 1
        # RVOL default
        rv = traw.get("rvol")
        if rv is not None and abs(float(rv) - 1.0) < 1e-3:
            rvol_default += 1
        # Pattern taxonomy
        st = d.get("setup_type") or ""
        setup_counter[st] += 1
        base = canon(st)
        if base not in BASE:
            pattern_pinned50 += 1

    print("=" * 64)
    print("TQS BLIND SUB-SCORE COVERAGE DIAG  (v392, READ-ONLY)")
    print("=" * 64)
    print(f"DB: {DB_NAME}   collection: live_alerts")
    print(f"Alerts with TQS breakdown analyzed: {n}")
    if oldest and newest:
        print(f"Window: {oldest}  →  {newest}")
    if n == 0:
        print("\nNo scored alerts in the book yet — run again after a scan cycle.")
        return

    def row(label, blind, note):
        bp = 100.0 * blind / n
        print(f"  {label:<16} real {100-bp:5.1f}%   blind {bp:5.1f}%  {note:<22} [{_verdict(bp)}]")

    print("\nSUB-SCORE         COVERAGE                                       VERDICT")
    row("Expected Value", ev_proxy,   "(R:R proxy, no live EV)")
    row("Tape",           tape_blind, "(tape_score=0 → 30)")
    row("Sector",         sector_blind, "(sector unknown/rank6)")
    row("RVOL",           rvol_default, "(rvol == 1.00 default)")
    row("Pattern",        pattern_pinned50, "(unmapped → pinned 50)")

    # Pattern taxonomy detail
    print("\nPATTERN TAXONOMY  (setup_type → canonical base → mapped?)")
    mapped, unmapped = [], []
    for st, c in setup_counter.most_common():
        base = canon(st)
        if base in BASE:
            mapped.append((st, base, BASE[base], c))
        else:
            unmapped.append((st, base, c))
    if mapped:
        print("  MAPPED:")
        for st, base, sc, c in mapped:
            print(f"    {st:<26} → {base:<22} base={sc:<3} n={c}")
    if unmapped:
        print("  UNMAPPED  (pattern pinned to flat 50 — taxonomy gap):")
        for st, base, c in unmapped:
            print(f"    {st:<26} → {base:<22} n={c}   <-- ADD TO SETUP_BASE_SCORES")
        up = 100.0 * pattern_pinned50 / n
        print(f"  Unmapped share of alerts: {up:.1f}%  ({pattern_pinned50}/{n})")
    else:
        print("  All live setup_types are mapped. No taxonomy gap.")

    print("\nLegend: RED >=50% blind · AMBER 20-49% · GREEN <20%")
    print("Read-only — nothing was modified.")


if __name__ == "__main__":
    main()
