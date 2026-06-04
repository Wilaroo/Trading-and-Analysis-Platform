#!/usr/bin/env python3
"""
diag_chart_data_integrity.py  (read-only)
=========================================
Find the corrupt bar(s) wrecking a symbol's chart (the CEG "POC 38.74 /
X exit @ 36.02 / candles squashed" symptom).

A single bad bar in `ib_historical_data` (absurd low/high or a giant volume
spike) poisons the Volume-Profile range in smart_levels_service
(`lo=min(low)`, `hi=max(high)`), parking the POC on the garbage price and
forcing the chart's autoscale down to it. This probe:

  1. Loads `ib_historical_data` bars per (symbol, bar_size) and flags OUTLIERS
     vs the median close (price >X% away) and vs median volume (>Nx).
  2. Reproduces compute_smart_levels() POC so you can see the bad POC.
  3. Dumps bot_trades entry/exit prices and flags any far from median (the
     `36.02` exit marker source).

Read-only. MONGO_URL + DB_NAME from backend/.env. Run from repo root:
    curl -s <url> | python3 - --symbols CEG --tfs 1min,5min
"""
from __future__ import annotations
import argparse
import os
import statistics
import sys
from pathlib import Path


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env",
                 Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _backend_on_path():
    root = Path.cwd()
    backend = root / "backend"
    if not backend.is_dir():
        backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        sys.exit(1)
    print(f"[db] {name} @ {url.split('@')[-1]}")
    return MongoClient(url)[name]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_TF_TO_BARSIZE = {"1min": "1 min", "5min": "5 mins", "15min": "15 mins",
                  "1hour": "1 hour", "1day": "1 day"}
PRICE_DEV_PCT = 20.0   # flag bars whose O/H/L/C is >20% from median close
VOL_MULT = 50.0        # flag bars whose volume is >50x median volume


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="CEG")
    ap.add_argument("--tfs", default="1min,5min")
    ap.add_argument("--limit", type=int, default=600)
    args = ap.parse_args()
    _load_env()
    _backend_on_path()
    db = _db()
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]

    try:
        from services.smart_levels_service import compute_smart_levels
    except Exception as e:
        compute_smart_levels = None
        print(f"(note: smart_levels import failed, POC reproduce skipped: {e})")

    for sym in syms:
        print("\n" + "=" * 76)
        print(f"SYMBOL {sym}")
        print("=" * 76)

        for tf in tfs:
            bs = _TF_TO_BARSIZE.get(tf, tf)
            rows = list(db["ib_historical_data"].find(
                {"symbol": sym, "bar_size": bs},
                {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1,
                 "close": 1, "volume": 1}).sort("date", -1).limit(args.limit))
            rows.reverse()
            print(f"\n── {tf} ({bs})  bars={len(rows)}")
            if not rows:
                print("    (no bars)")
                continue
            closes = [c for c in (_f(r.get("close")) for r in rows) if c]
            vols = [v for v in (_f(r.get("volume")) for r in rows) if v and v > 0]
            if not closes:
                print("    (no usable closes)")
                continue
            med = statistics.median(closes)
            medvol = statistics.median(vols) if vols else 0
            lo_all = min(_f(r.get("low")) for r in rows if _f(r.get("low")))
            hi_all = max(_f(r.get("high")) for r in rows if _f(r.get("high")))
            print(f"    median close={med:.2f}  range low={lo_all:.2f} high={hi_all:.2f}"
                  f"  median vol={medvol:,.0f}")

            flagged = []
            for r in rows:
                o, h, lw, c = (_f(r.get("open")), _f(r.get("high")),
                               _f(r.get("low")), _f(r.get("close")))
                v = _f(r.get("volume")) or 0
                price_bad = any(
                    p is not None and abs(p - med) / med * 100 > PRICE_DEV_PCT
                    for p in (o, h, lw, c))
                vol_bad = medvol > 0 and v > medvol * VOL_MULT
                if price_bad or vol_bad:
                    flagged.append((r, price_bad, vol_bad))
            if flagged:
                print(f"    🚨 {len(flagged)} CORRUPT/OUTLIER bar(s):")
                for r, pb, vb in flagged[:15]:
                    tags = []
                    if pb:
                        tags.append("PRICE")
                    if vb:
                        tags.append("VOLUME")
                    print(f"        {str(r.get('date'))[:19]}  "
                          f"O={_f(r.get('open'))} H={_f(r.get('high'))} "
                          f"L={_f(r.get('low'))} C={_f(r.get('close'))} "
                          f"V={_f(r.get('volume')):,.0f}  [{'+'.join(tags)}]")
            else:
                print("    ✓ no outlier bars by price/volume thresholds")

            if compute_smart_levels:
                try:
                    sl = compute_smart_levels(db, sym, tf)
                    print(f"    smart_levels POC={sl.get('poc_price')}  "
                          f"HVN={sl.get('hvn_prices')}")
                except Exception as e:
                    print(f"    smart_levels compute failed: {e}")

        # ── trade markers (the 36.02 exit) ──
        med_t = statistics.median(closes) if closes else None
        bts = list(db["bot_trades"].find(
            {"symbol": sym},
            {"_id": 0, "id": 1, "status": 1, "entry_price": 1, "exit_price": 1,
             "stop_price": 1, "fill_price": 1, "close_reason": 1, "closed_at": 1}))
        bad_t = []
        for t in bts:
            for fld in ("entry_price", "exit_price", "stop_price", "fill_price"):
                p = _f(t.get(fld))
                if p is not None and med_t and abs(p - med_t) / med_t * 100 > PRICE_DEV_PCT:
                    bad_t.append((t, fld, p))
        print(f"\n  bot_trades price-outliers (>{PRICE_DEV_PCT:.0f}% from "
              f"median {med_t}): {len(bad_t)}")
        for t, fld, p in bad_t[:15]:
            print(f"    • id={str(t.get('id'))[:8]} status={t.get('status')} "
                  f"{fld}={p}  close_reason={t.get('close_reason')} "
                  f"closed={str(t.get('closed_at'))[:19]}")

    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
