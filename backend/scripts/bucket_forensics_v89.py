"""bucket_forensics_v89.py — forensics on the bleeding (setup × grade) buckets.
Targets:
  - setup=squeeze       × smb_grade=A    (0/7 wins)
  - setup=daily_squeeze × smb_grade=B    (0/14 wins, -$13,958)
"""
from __future__ import annotations
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"
for ln in ENV.read_text().splitlines():
    ln = ln.strip()
    if ln and not ln.startswith("#") and "=" in ln:
        k, _, v = ln.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hour(iso: str) -> int:
    try:
        return datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(timezone.utc).hour
    except Exception:
        return -1


def dump(setup: str, grade: str) -> None:
    print(f"\n{'='*78}\n  BUCKET: setup={setup}  grade={grade}\n{'='*78}")
    trades = list(db.bot_trades.find(
        {"setup_type": setup, "smb_grade": grade, "status": {"$regex": "^closed", "$options": "i"}},
        {"_id": 0},
    ).sort("created_at", 1))
    print(f"  n={len(trades)}")
    if not trades:
        return

    hours, holds, rr, slips = [], [], [], []
    reasons, syms, dirs = Counter(), Counter(), Counter()
    per_symbol = defaultdict(list)

    for t in trades:
        entry = float(t.get("fill_price") or 0)
        stop  = float(t.get("stop_price")  or t.get("stop_loss") or 0)
        tgt   = float(t.get("tp_price")    or t.get("target") or 0)
        d = t.get("direction") or "long"
        d = d.get("value", d) if isinstance(d, dict) else d
        signal_px = float(t.get("signal_price") or t.get("alert_price") or entry)

        if entry > 0 and stop > 0 and tgt > 0 and abs(entry-stop) > 0:
            rr.append(round(abs(tgt-entry)/abs(entry-stop), 2))
        if signal_px > 0 and entry > 0:
            slips.append(round((entry-signal_px)/signal_px*100, 3))
        try:
            a = datetime.fromisoformat(str(t.get("created_at","")).replace("Z","+00:00"))
            b = datetime.fromisoformat(str(t.get("closed_at","")).replace("Z","+00:00"))
            holds.append(int((b-a).total_seconds()/60))
        except Exception:
            pass

        h = _hour(str(t.get("created_at","")))
        if h >= 0: hours.append(h)
        reasons[t.get("close_reason","?")] += 1
        syms[t.get("symbol","?")] += 1
        dirs[str(d)] += 1
        per_symbol[t.get("symbol","?")].append(t)

    def stats(name, arr, fmt="{:.2f}"):
        if not arr:
            print(f"  {name}: (no data)"); return
        s = sorted(arr); med = s[len(s)//2]
        print(f"  {name}: n={len(arr)} min={fmt.format(min(arr))} "
              f"med={fmt.format(med)} max={fmt.format(max(arr))} "
              f"avg={fmt.format(sum(arr)/len(arr))}")

    print(f"\n  -- direction: {dict(dirs)}")
    print(f"  -- close reasons: {dict(reasons)}")
    print(f"  -- top symbols: {dict(syms.most_common(10))}")
    print(f"  -- hour-of-day (UTC): {dict(sorted(Counter(hours).items()))}\n")
    stats("R:R ratio (reward/risk)", rr)
    stats("slippage % (fill vs signal)", slips, "{:+.3f}%")
    stats("hold duration (min)", holds, "{:.0f}")
    loops = [(s, len(ts)) for s, ts in per_symbol.items() if len(ts) >= 3]
    if loops: print(f"\n  -- loop offenders (>=3): {loops}")

    print(f"\n  {'i':>2} {'sym':>6} {'dir':>5} {'entry':>9} {'stop':>9} "
          f"{'tgt':>9} {'exit':>9} {'R':>7} {'reason':<32} created")
    for i, t in enumerate(trades, 1):
        d = t.get("direction") or "long"
        d = d.get("value", d) if isinstance(d, dict) else d
        e, s, x = (float(t.get(k) or 0) for k in ("fill_price","stop_price","exit_price"))
        rmult = 0.0
        if e and s and x and abs(e-s) > 0:
            pps = (x-e) if str(d).lower()=="long" else (e-x)
            rmult = round(pps/abs(e-s), 2)
        print(f"  {i:>2} {str(t.get('symbol','?')):>6} {str(d):>5} "
              f"{e:>9.2f} {s:>9.2f} {float(t.get('tp_price') or 0):>9.2f} "
              f"{x:>9.2f} {rmult:>+7.2f} "
              f"{str(t.get('close_reason','?'))[:32]:<32} "
              f"{str(t.get('created_at',''))[:19]}")


if __name__ == "__main__":
    dump("squeeze", "A")
    dump("daily_squeeze", "B")
