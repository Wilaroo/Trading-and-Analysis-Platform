#!/usr/bin/env python3
"""
backtest_trend_continuation_short.py  (v19.34.282) — READ-ONLY.

Replays a symbol's real bars (from ib_historical_data) through the EXACT gating
logic of enhanced_scanner._check_trend_continuation_short and prints every bar
where the new SHORT setup WOULD have fired. Runs across multiple timeframes so
you can see whether the detector catches a daily downtrend AND/OR an intraday
staircase-down (e.g. NVDA / TSLA 2026-06-05).

Usage (DGX, from repo root):
    .venv/bin/python backend/scripts/backtest_trend_continuation_short.py
    .venv/bin/python backend/scripts/backtest_trend_continuation_short.py NVDA TSLA AAPL

Touches nothing — pure read + math. No orders, no DB writes.
"""
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


def detect_short(bars):
    """EXACT replica of _check_trend_continuation_short gating.
    Returns a dict of trade levels if it fires on bars[-1], else None."""
    if len(bars) < 25:
        return None
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    ema20 = closes[-20]
    m = 2 / 21
    for c in closes[-19:]:
        ema20 = c * m + ema20 * (1 - m)
    ema20_5ago = closes[-25]
    for c in closes[-24:-5]:
        ema20_5ago = c * m + ema20_5ago * (1 - m)
    if ema20 >= ema20_5ago:
        return None  # EMA not falling

    recent_highs = [max(highs[-15:-10]), max(highs[-10:-5]), max(highs[-5:])]
    recent_lows = [min(lows[-15:-10]), min(lows[-10:-5]), min(lows[-5:])]
    lh = all(recent_highs[i] < recent_highs[i - 1] for i in range(1, 3))
    ll = all(recent_lows[i] < recent_lows[i - 1] for i in range(1, 3))
    if not (lh and ll):
        return None

    current = closes[-1]
    dist = (current - ema20) / ema20 * 100
    if dist > 0.5 or dist < -2.0:
        return None

    atrs = []
    for i in range(1, min(15, len(bars))):
        tr = max(highs[-i] - lows[-i], abs(highs[-i] - closes[-(i + 1)]), abs(lows[-i] - closes[-(i + 1)]))
        atrs.append(tr)
    atr = sum(atrs) / len(atrs) if atrs else current * 0.02
    stop = round(ema20 + atr * 1.5, 2)
    target = round(current - atr * 3, 2)
    rr = abs(current - target) / abs(stop - current) if abs(stop - current) > 0 else 0
    return {"price": round(current, 2), "ema20": round(ema20, 2),
            "dist_pct": round(dist, 2), "stop": stop, "target": target, "rr": round(rr, 1)}


def replay(db, symbol, bar_size, limit):
    bars = list(db["ib_historical_data"].find(
        {"symbol": symbol, "bar_size": bar_size},
        {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ).sort("date", -1).limit(limit))
    bars.reverse()
    if len(bars) < 25:
        print(f"  {bar_size:8} : only {len(bars)} bars — not enough to test")
        return
    fires = []
    for i in range(25, len(bars) + 1):
        r = detect_short(bars[:i])
        if r:
            fires.append((bars[i - 1].get("date"), r))
    last_date = bars[-1].get("date")
    print(f"  {bar_size:8} : {len(bars)} bars (latest {last_date}) -> "
          f"{len(fires)} fire-point(s)")
    for when, r in fires[:6]:
        print(f"      FIRE @ {when}  px={r['price']} ema20={r['ema20']} "
              f"dist={r['dist_pct']}%  stop={r['stop']} tgt={r['target']} rr={r['rr']}:1")
    if len(fires) > 6:
        print(f"      ... +{len(fires) - 6} more")


def main():
    symbols = [s.upper() for s in sys.argv[1:]] or ["NVDA", "TSLA"]
    env = _load_env()
    db = MongoClient(env["MONGO_URL"])[env.get("DB_NAME", "tradecommand")]
    print(f"\n=== backtest trend_continuation_short — {datetime.now(timezone.utc).isoformat()} ===")
    for sym in symbols:
        print(f"\n[{sym}]")
        replay(db, sym, "1 day", 120)
        replay(db, sym, "5 mins", 400)
        replay(db, sym, "1 min", 800)
    print("\nNote: the live detector currently runs on the DAILY check loop. If the")
    print("intraday (1 min / 5 mins) rows show fires but '1 day' does not, the logic")
    print("works on the intraday staircase but needs an intraday registration to fire")
    print("live on days like today — that's the next decision.\n")


if __name__ == "__main__":
    main()
