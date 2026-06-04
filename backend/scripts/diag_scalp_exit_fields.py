#!/usr/bin/env python3
"""
diag_scalp_exit_fields.py  (read-only)
======================================
B-step-2: decide which reclassification method is viable for external/OCA
scalp+intraday exits.

diag_scalp_exit_truth found exit_price is essentially never persisted on
external closes, so the pnl-sign-vs-price cross-check had a zero sample. This
probe answers the remaining question: on the external/OCA closes we want to
reclassify, are `stop_price` and `target_prices` populated? If yes, we can
RECONSTRUCT an implied exit from realized_pnl/shares and run a magnitude-aware
price-proximity check (tier 2). If not, we are limited to pnl-sign + scratch
tolerance.

For every external scalp/intraday close it reports:
  - field presence (exit_price / stop_price / target_prices / realized+shares)
  - for rows WITH stop+target: reconstruct exit = entry ± realized/shares,
    then verdict_price = nearer(target vs stop); verdict_sign = pnl-sign.
    Report agreement %. Disagreements are the rows where a small/large pnl
    sign would mislabel vs where the reconstructed price actually landed.
  - distribution of reconstructed realized-R buckets.

Read-only. MONGO_URL + DB_NAME from backend/.env.
Usage:  curl -s <url> | python3 - --days 30
"""
from __future__ import annotations
import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
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


HORIZONS = ("scalp", "intraday", "swing", "position", "investment")


def _enum(v):
    return getattr(v, "value", v)


def horizon(t):
    for f in ("timeframe", "trade_type", "scan_tier"):
        v = str(_enum(t.get(f)) or "").lower().strip()
        if v in HORIZONS:
            return v
    return "unknown"


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _dir(t):
    return str(_enum(t.get("direction")) or "long").lower()


def is_external(t):
    r = (t.get("close_reason") or "").lower()
    return ("oca_closed_externally" in r) or ("external" in r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    _load_env()
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    cur = db["bot_trades"].find(
        {"closed_at": {"$gte": cutoff}, "status": {"$in": ["closed", "CLOSED"]}},
        {"_id": 0, "timeframe": 1, "trade_type": 1, "scan_tier": 1,
         "close_reason": 1, "net_pnl": 1, "realized_pnl": 1, "entry_price": 1,
         "fill_price": 1, "exit_price": 1, "stop_price": 1, "stop_loss": 1,
         "target_prices": 1, "tp_price": 1, "target": 1, "shares": 1,
         "direction": 1, "symbol": 1},
    )

    rows = [t for t in cur if horizon(t) in ("scalp", "intraday") and is_external(t)]

    print("\n" + "=" * 72)
    print(f"EXTERNAL SCALP/INTRADAY CLOSES — last {args.days}d — {len(rows)} rows")
    print("=" * 72)
    if not rows:
        print("None found.")
        return

    by_h = defaultdict(list)
    for t in rows:
        by_h[horizon(t)].append(t)

    for h in ("scalp", "intraday"):
        sub = by_h.get(h, [])
        if not sub:
            continue
        n = len(sub)
        has_exit = sum(1 for t in sub if _f(t.get("exit_price")) > 0)
        has_stop = sum(1 for t in sub if (_f(t.get("stop_price")) or _f(t.get("stop_loss"))) > 0)
        has_tgt = sum(1 for t in sub if (t.get("target_prices") or t.get("tp_price") or t.get("target")))
        has_recon = sum(1 for t in sub
                        if (_f(t.get("entry_price")) or _f(t.get("fill_price"))) > 0
                        and (_f(t.get("realized_pnl")) or _f(t.get("net_pnl")))
                        and _f(t.get("shares")) > 0)
        stop_and_tgt = sum(1 for t in sub
                           if (_f(t.get("stop_price")) or _f(t.get("stop_loss"))) > 0
                           and (t.get("target_prices") or t.get("tp_price") or t.get("target")))
        print(f"\n── {h.upper()}  (n={n})  field presence:")
        print(f"     exit_price>0          {has_exit:>4} ({has_exit/n*100:3.0f}%)")
        print(f"     stop present          {has_stop:>4} ({has_stop/n*100:3.0f}%)")
        print(f"     target present        {has_tgt:>4} ({has_tgt/n*100:3.0f}%)")
        print(f"     stop AND target       {stop_and_tgt:>4} ({stop_and_tgt/n*100:3.0f}%)  <- tier-2 eligible")
        print(f"     reconstruct eligible  {has_recon:>4} ({has_recon/n*100:3.0f}%)  (entry+pnl+shares)")

        # Tier-2 viability: reconstruct exit, compare price-proximity vs pnl-sign.
        agree = Counter()
        rbuckets = Counter()
        for t in sub:
            entry = _f(t.get("entry_price")) or _f(t.get("fill_price"))
            stop = _f(t.get("stop_price")) or _f(t.get("stop_loss"))
            tps = t.get("target_prices") or []
            tgt = _f(tps[0]) if tps else (_f(t.get("tp_price")) or _f(t.get("target")))
            realized = _f(t.get("realized_pnl")) or _f(t.get("net_pnl"))
            shares = _f(t.get("shares"))
            d = _dir(t)
            if entry <= 0 or shares <= 0 or stop <= 0 or tgt <= 0:
                continue
            pps = realized / shares
            recon_exit = entry + pps if d == "long" else entry - pps
            risk = abs(entry - stop)
            if risk > 0:
                rr = pps / risk if d == "long" else (-pps) / risk
                # bucket realized-R
                if rr >= 1.0:
                    rbuckets[">=+1R"] += 1
                elif rr >= 0.25:
                    rbuckets["+0.25..1R"] += 1
                elif rr > -0.25:
                    rbuckets["scratch(-0.25..0.25R)"] += 1
                elif rr > -1.0:
                    rbuckets["-1..-0.25R"] += 1
                else:
                    rbuckets["<=-1R"] += 1
            near_target = abs(recon_exit - tgt) <= abs(recon_exit - stop)
            sign_target = realized > 0
            agree["agree" if near_target == sign_target else "disagree"] += 1
        tot = sum(agree.values())
        if tot:
            print(f"   reconstruct-vs-sign agreement: agree={agree['agree']} "
                  f"disagree={agree['disagree']} => {agree['agree']/tot*100:.0f}% "
                  f"(n={tot} with stop+target+entry+shares)")
            print(f"   reconstructed realized-R distribution:")
            for k in (">=+1R", "+0.25..1R", "scratch(-0.25..0.25R)", "-1..-0.25R", "<=-1R"):
                if rbuckets[k]:
                    print(f"        {k:<26} {rbuckets[k]:>4} ({rbuckets[k]/tot*100:3.0f}%)")
        else:
            print("   tier-2 NOT viable: no external row has stop+target+entry+shares.")
            print("   => reclassifier must rely on pnl-sign + scratch tolerance only.")

    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
