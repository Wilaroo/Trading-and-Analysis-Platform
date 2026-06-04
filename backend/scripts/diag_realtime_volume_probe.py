#!/usr/bin/env python3
"""
diag_realtime_volume_probe.py  (read-only, MARKET-HOURS)
========================================================
Answers point E: does the bot see TRUE realtime volume when it fires
scalp/intraday entries?

The bot's live volume comes from the Windows IB pusher: one global
`last_update` per push batch + per-symbol cumulative day `volume`.
This probe takes TWO snapshots of /api/ib/pushed-data `--gap` seconds
apart and checks:

  1. PUSH CADENCE — did `last_update` advance between reads? how old is
     the data? (stale/slow pusher => stale volume at entry).
  2. VOLUME ADVANCE — for each symbol, did cumulative `volume` increase?
  3. SMOKING GUN — symbols whose PRICE moved but whose VOLUME stayed
     FROZEN. If trades printed (price moved) the cumulative volume MUST
     rise; if it doesn't, the volume field is a stale snapshot, NOT
     true realtime -> the bot is sizing scalps on bad volume/RVol.
  4. live_bar_cache freshness (the 5-min bars feeding charts/RVol).

Read-only HTTP to the local backend. Run on the DGX DURING MARKET HOURS.

Usage:  python3 diag_realtime_volume_probe.py --gap 20
   or:  curl -s <url> | python3 - --gap 20
"""
from __future__ import annotations
import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=15) as r:
        return json.loads(r.read().decode())


def _age(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


def _vol(q):
    try:
        return int(q.get("volume") or 0)
    except (TypeError, ValueError):
        return 0


def _price(q):
    return float(q.get("price") or q.get("last") or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--gap", type=int, default=20, help="seconds between snapshots")
    ap.add_argument("--examples", type=int, default=12)
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("=" * 70)
    print("REALTIME VOLUME PROBE  (run during market hours)")
    print("=" * 70)

    # pusher health
    try:
        ph = _get(base, "/api/ib/pusher-health")
        print("\n[pusher-health]")
        for k in ("connected", "stale", "last_update", "push_age_s",
                  "pushes_per_min", "consecutive_failures"):
            if k in ph:
                print(f"   {k:<20} {ph[k]}")
    except Exception as e:
        print("  pusher-health read failed:", e)

    # snapshot 1
    d1 = _get(base, "/api/ib/pushed-data")
    q1 = d1.get("quotes") or {}
    lu1 = d1.get("last_update")
    print(f"\n[snapshot 1] quotes={len(q1)}  last_update={lu1}  age={_age(lu1)}")
    if not q1:
        print("  NO QUOTES in pusher — market closed, pusher down, or not connected. Stop.")
        return

    print(f"  ...waiting {args.gap}s for the next push batch...")
    time.sleep(args.gap)

    # snapshot 2
    d2 = _get(base, "/api/ib/pushed-data")
    q2 = d2.get("quotes") or {}
    lu2 = d2.get("last_update")
    print(f"[snapshot 2] quotes={len(q2)}  last_update={lu2}  age={_age(lu2)}")

    # 1. cadence
    print("\n" + "-" * 70)
    print("1) PUSH CADENCE")
    print("-" * 70)
    if lu1 == lu2:
        print(f"  !! last_update DID NOT CHANGE in {args.gap}s — no fresh push arrived.")
        print("     => the pusher is slow/stuck; the bot is acting on STALE data.")
    else:
        print(f"  OK — new push arrived ({lu1} -> {lu2}). Pusher is live.")

    # 2/3. volume advance + smoking gun
    common = [s for s in q2 if s in q1]
    vol_adv = vol_frozen = price_moved = 0
    smoking = []  # price moved but volume frozen
    for s in common:
        dv = _vol(q2[s]) - _vol(q1[s])
        dp = _price(q2[s]) - _price(q1[s])
        if dv > 0:
            vol_adv += 1
        elif dv == 0:
            vol_frozen += 1
        if abs(dp) > 1e-9:
            price_moved += 1
            if dv == 0:
                smoking.append((s, _price(q1[s]), _price(q2[s]), _vol(q2[s])))

    print("\n" + "-" * 70)
    print(f"2) VOLUME ADVANCE  (symbols compared: {len(common)})")
    print("-" * 70)
    if common:
        print(f"   volume ADVANCED : {vol_adv:>4}  ({vol_adv/len(common)*100:.0f}%)")
        print(f"   volume FROZEN   : {vol_frozen:>4}  ({vol_frozen/len(common)*100:.0f}%)")
        print(f"   price MOVED     : {price_moved:>4}  ({price_moved/len(common)*100:.0f}%)")

    print("\n" + "-" * 70)
    print(f"3) SMOKING GUN — price MOVED but volume FROZEN: {len(smoking)}")
    print("-" * 70)
    if smoking:
        print("   (these prove the volume field is a stale snapshot, not realtime)")
        for s, p1, p2, v in smoking[:args.examples]:
            print(f"     {s:<6} price {p1:.2f}->{p2:.2f}   volume stuck at {v:,}")
        print("\n   VERDICT: volume is NOT fully realtime for these names —")
        print("            scalp RVol/size decisions on them are on stale volume.")
    else:
        print("   none — where price moved, volume advanced too. Volume looks realtime. ✅")

    # 4. live bar cache
    try:
        h = _get(base, "/api/system/health")
        for sub in h.get("subsystems", []):
            if sub.get("name") == "live_bar_cache":
                print("\n" + "-" * 70)
                print("4) live_bar_cache (5-min bars feeding charts + RVol)")
                print("-" * 70)
                m = sub.get("metrics", {})
                print(f"   fresh/total: {m.get('fresh')}/{m.get('total')}   detail: {sub.get('detail')}")
                if m.get("total") and (m.get("fresh", 0) / m["total"]) < 0.5:
                    print("   => majority STALE; charts cold-fetch (lag) and RVol baseline may be stale.")
    except Exception:
        pass

    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
