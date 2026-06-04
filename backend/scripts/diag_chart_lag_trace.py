#!/usr/bin/env python3
"""
diag_chart_lag_trace.py  (read-only)
====================================
Quantify the "charts laggy / cache-frozen" symptom by measuring the THREE
links in the serving chain for each active symbol + timeframe:

  1. live_bar_cache   — freshest IB bars (pusher RPC).   [source of truth]
  2. chart_response_cache — the full /chart payload the /chart-tail poll
     slices from. On a cache HIT, /chart-tail does NOT consult live_bar_cache,
     so the served chart can only be as fresh as THIS entry.
  3. wall clock.

The lag the operator sees ≈ (live_bar_cache latest bar) − (chart_response_cache
latest bar). If that gap is large while live_bar_cache is fresh, the freeze is
in the SERVING layer (full-cache TTL binding), not the data feed.

Read-only. MONGO_URL + DB_NAME from backend/.env.
Usage:  curl -s <url> | python3 - [--symbols SPY,IBM] [--tfs 1min,5min]
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime, timezone
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


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        sys.exit(1)
    print(f"[db] {name} @ {url.split('@')[-1]}")
    return MongoClient(url)[name]


def _to_epoch(v):
    """Coerce a bar timestamp (epoch seconds, ms, or ISO string) -> epoch s."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if v > 1e12 else float(v)
    if isinstance(v, datetime):
        return v.timestamp()
    s = str(v)
    try:
        return float(s)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _age(now_e, e):
    return None if e is None else round(now_e - e, 1)


def _fmt_age(a):
    if a is None:
        return "  n/a"
    if a < 90:
        return f"{a:5.0f}s"
    return f"{a/60:5.1f}m"


_TF_TO_BARSIZE = {"1min": "1 min", "5min": "5 mins", "15min": "15 mins",
                  "1hour": "1 hour", "1day": "1 day"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tfs", default="1min,5min")
    args = ap.parse_args()
    _load_env()
    db = _db()
    now_e = datetime.now(timezone.utc).timestamp()
    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not syms:
        # auto: symbols the operator is actively viewing, else open positions
        av = db["live_bar_cache"].distinct("symbol", {"active_view": True})
        syms = sorted(set(av))[:12]
        if not syms:
            syms = sorted({(t.get("symbol") or "").upper()
                           for t in db["bot_trades"].find(
                               {"status": {"$in": ["open", "OPEN"]}},
                               {"symbol": 1})})[:12]
    if not syms:
        print("No symbols (none active_view, none open). Pass --symbols.")
        return

    print(f"\nnow={datetime.now(timezone.utc).isoformat()[:19]}Z  "
          f"symbols={','.join(syms)}\n")
    hdr = (f"{'SYM':<6} {'TF':<6} {'lbc_bars':>8} {'lbc_latest_age':>14} "
           f"{'lbc_fetch_age':>13} {'crc_latest_age':>14} {'crc_entry_age':>13} "
           f"{'SERVE_GAP':>10}  view")
    print(hdr)
    print("-" * len(hdr))

    for sym in syms:
        for tf in tfs:
            bs = _TF_TO_BARSIZE.get(tf, tf)
            lbc = db["live_bar_cache"].find_one({"symbol": sym, "bar_size": bs})
            lbc_n = lbc_latest = lbc_fetch = None
            active = "-"
            if lbc:
                bars = lbc.get("bars") or []
                lbc_n = len(bars)
                if bars:
                    lbc_latest = _to_epoch(bars[-1].get("date") or bars[-1].get("time"))
                lbc_fetch = _to_epoch(lbc.get("fetched_at"))
                active = "Y" if lbc.get("active_view") else "-"

            # freshest chart_response_cache entry for this sym+tf
            crc = list(db["chart_response_cache"].find(
                {"symbol": sym, "timeframe": tf}).sort("cached_at", -1).limit(1))
            crc_latest = crc_entry = None
            if crc:
                doc = crc[0]
                resp = doc.get("response") or {}
                rbars = resp.get("bars") or []
                if rbars:
                    crc_latest = _to_epoch(rbars[-1].get("time") or rbars[-1].get("date"))
                crc_entry = _to_epoch(doc.get("cached_at"))

            serve_gap = (None if (lbc_latest is None or crc_latest is None)
                         else round(lbc_latest - crc_latest, 1))
            print(f"{sym:<6} {tf:<6} {(lbc_n if lbc_n is not None else '-'):>8} "
                  f"{_fmt_age(_age(now_e, lbc_latest)):>14} "
                  f"{_fmt_age(_age(now_e, lbc_fetch)):>13} "
                  f"{_fmt_age(_age(now_e, crc_latest)):>14} "
                  f"{_fmt_age(_age(now_e, crc_entry)):>13} "
                  f"{_fmt_age(serve_gap):>10}  {active}")

    print("\nLEGEND:")
    print("  lbc_latest_age  = age of newest bar in live_bar_cache (data feed)")
    print("  crc_latest_age  = age of newest bar in the served /chart payload")
    print("  SERVE_GAP       = lbc_latest − crc_latest  → how far the SERVED")
    print("                    chart trails the live feed (the visible lag)")
    print("  A large SERVE_GAP with a small lbc_latest_age = serving-layer")
    print("  freeze (full-cache TTL binding), NOT a data-feed problem.")
    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
