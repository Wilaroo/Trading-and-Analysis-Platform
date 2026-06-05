#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_trend_continuation_short_v282.py — IDEMPOTENT applier for v19.34.282
"trend_continuation_short" detector (mirror of the long), auto-execute-eligible
from its first signal, + a read-only backtest probe.

WHAT IT DOES:
  1. enhanced_scanner.py
     - registers _check_trend_continuation_short in the daily-setup check list
     - adds the _check_trend_continuation_short detector (falling EMA + lower-
       highs/lower-lows + pullback up to the declining 20 EMA -> SHORT, HIGH prio)
     - grants the win-rate floor to trend_continuation_short so it is
       auto-execute-eligible on priority+tape from its first signal
  2. opportunity_evaluator.py
     - adds trend_continuation_short -> 1.75x ATR stop multiplier
  3. writes backend/scripts/backtest_trend_continuation_short.py

Builds on v19.34.281 (symbol-trace). Re-running is a no-op (idempotent).

RUN ON DGX (from repo root ~/Trading-and-Analysis-Platform):
    .venv/bin/python /tmp/apply_trend_continuation_short_v282.py --dry-run
    .venv/bin/python /tmp/apply_trend_continuation_short_v282.py
then:
    ./start_backend.sh --force
    .venv/bin/python backend/scripts/backtest_trend_continuation_short.py NVDA TSLA
"""
import argparse
import os
import shutil
import sys

BAK_SUFFIX = ".bak.tcshort0605"
REPO = os.getcwd()
SCANNER = os.path.join(REPO, "backend/services/enhanced_scanner.py")
EVAL = os.path.join(REPO, "backend/services/opportunity_evaluator.py")
PROBE = os.path.join(REPO, "backend/scripts/backtest_trend_continuation_short.py")

EDITS = []

# 1) register in the daily-setup check list
EDITS.append((SCANNER, "self._check_trend_continuation_short,  # v19.34.282",
'''                    for check in [
                        self._check_daily_squeeze,
                        self._check_trend_continuation,
                        self._check_daily_breakout,''',
'''                    for check in [
                        self._check_daily_squeeze,
                        self._check_trend_continuation,
                        self._check_trend_continuation_short,  # v19.34.282
                        self._check_daily_breakout,'''))

# 2) eligibility special-case (immediate auto-execute)
EDITS.append((SCANNER, 'if setup_type == "trend_continuation_short":',
'''                    # Add tape reading to alert
                    # v19.34.213 — normalize tape_score from the producer's raw''',
'''                    # v19.34.282 — user-approved immediate auto-execute for the newly
                    # added trend_continuation_short. Canonicalizes to
                    # `trend_continuation` for stats; force the win-rate floor as its
                    # cold-start baseline so it auto-executes on priority+tape from its
                    # first signal (operator choice, 2026-06-05).
                    if setup_type == "trend_continuation_short":
                        alert.strategy_win_rate = max(
                            float(getattr(alert, "strategy_win_rate", 0.0) or 0.0),
                            self._auto_execute_min_win_rate,
                        )
                        alert.calculate_r_multiple()
                        try:
                            alert.grade_trade(
                                strategy_ev=float(getattr(alert, "strategy_ev_r", 0.0) or 0.0),
                                market_context_score=0.5,
                            )
                        except Exception:
                            pass

                    # Add tape reading to alert
                    # v19.34.213 — normalize tape_score from the producer's raw'''))

# 3) the detector method (inserted between the long detector and _check_daily_breakout)
EDITS.append((SCANNER, "async def _check_trend_continuation_short(self, symbol: str, bars: list)",
'''            direction_bias="long",
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        )

    async def _check_daily_breakout(self, symbol: str, bars: list) -> Optional[LiveAlert]:''',
'''            direction_bias="long",
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        )

    async def _check_trend_continuation_short(self, symbol: str, bars: list) -> Optional[LiveAlert]:
        """v19.34.282 — SHORT mirror of _check_trend_continuation.

        Lower highs + lower lows, pulling back UP to a FALLING 20 EMA, then
        resuming down (trend-continuation short). Added because the bot had no
        way to express 'stay short with the trend' on clean downtrend days
        (e.g. NVDA / TSLA 2026-06-05, which produced only counter-trend longs).
        Emits HIGH priority + is granted the win-rate floor downstream so it is
        auto-execute-eligible from its first signal (operator choice)."""
        if len(bars) < 25:
            return None

        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]

        # 20 EMA (current)
        ema20 = closes[-20]
        multiplier = 2 / 21
        for c in closes[-19:]:
            ema20 = c * multiplier + ema20 * (1 - multiplier)

        # 20 EMA as of 5 bars ago (for slope)
        ema20_5ago = closes[-25]
        for c in closes[-24:-5]:
            ema20_5ago = c * multiplier + ema20_5ago * (1 - multiplier)

        if ema20 >= ema20_5ago:
            return None  # EMA not falling

        # Lower highs and lower lows (last 3 swings) — mirror of the long's HH/HL
        recent_highs = [max(highs[-15:-10]), max(highs[-10:-5]), max(highs[-5:])]
        recent_lows = [min(lows[-15:-10]), min(lows[-10:-5]), min(lows[-5:])]

        lh = all(recent_highs[i] < recent_highs[i - 1] for i in range(1, len(recent_highs)))
        ll = all(recent_lows[i] < recent_lows[i - 1] for i in range(1, len(recent_lows)))

        if not (lh and ll):
            return None  # No downtrend structure

        # Price pulling back UP near the falling 20 EMA (within band).
        # Long zone is (-0.5%..+2.0%); the short mirror is (-2.0%..+0.5%).
        current = closes[-1]
        dist_from_ema = (current - ema20) / ema20 * 100
        if dist_from_ema > 0.5 or dist_from_ema < -2.0:
            return None  # Not in the pullback-to-EMA short zone

        # ATR for stop
        atrs = []
        for i in range(1, min(15, len(bars))):
            tr = max(highs[-(i)] - lows[-(i)], abs(highs[-(i)] - closes[-(i + 1)]), abs(lows[-(i)] - closes[-(i + 1)]))
            atrs.append(tr)
        atr = sum(atrs) / len(atrs) if atrs else current * 0.02

        stop = round(ema20 + atr * 1.5, 2)
        target = round(current - atr * 3, 2)
        rr = abs(current - target) / abs(stop - current) if abs(stop - current) > 0 else 0

        return LiveAlert(
            id=f"trend_continuation_short_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="trend_continuation_short",
            strategy_name="trend_continuation_short",
            direction="short",
            priority=AlertPriority.HIGH,
            current_price=current,
            trigger_price=current,
            stop_loss=stop,
            target=target,
            risk_reward=round(rr, 1),
            trigger_probability=0.6,
            win_probability=0.55,
            minutes_to_trigger=0,
            headline=f"{symbol} Trend Continuation SHORT - Pullback to falling 20 EMA",
            reasoning=[
                "Daily downtrend: Lower highs + lower lows confirmed",
                f"Price {dist_from_ema:.1f}% from falling 20 EMA (pullback-to-resistance short)",
                f"EMA slope: falling (current ${ema20:.2f} < 5-bar-ago ${ema20_5ago:.2f})",
                f"ATR: ${atr:.2f} | R:R {rr:.1f}:1 | Swing hold",
            ],
            time_window="DAILY",
            market_regime="neutral",
            trade_style="multi_day",
            setup_category="trend_momentum",
            scan_tier="swing",
            direction_bias="short",
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        )

    async def _check_daily_breakout(self, symbol: str, bars: list) -> Optional[LiveAlert]:'''))

# 4) opportunity_evaluator ATR multiplier
EDITS.append((EVAL, "'trend_continuation_short': 1.75,  # v19.34.282",
'''        'trend_continuation':     1.75,''',
'''        'trend_continuation':     1.75,
        'trend_continuation_short': 1.75,  # v19.34.282'''))


PROBE_SRC = r'''#!/usr/bin/env python3
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
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    for p in (SCANNER, EVAL):
        if not os.path.isfile(p):
            print(f"[FATAL] not found: {p}\n  -> run from repo root (~/Trading-and-Analysis-Platform)")
            sys.exit(2)

    by_file = {}
    for path, marker, old, new in EDITS:
        by_file.setdefault(path, []).append((marker, old, new))

    applied = skipped = errors = 0
    backed_up = set()
    for path, edits in by_file.items():
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        orig = text
        for marker, old, new in edits:
            if marker in text:
                print(f"  [skip] already applied: {os.path.basename(path)} :: {marker[:50]}")
                skipped += 1
                continue
            if old not in text:
                print(f"  [ERROR] anchor not found in {os.path.basename(path)} :: {marker[:50]}")
                errors += 1
                continue
            text = text.replace(old, new, 1)
            print(f"  [apply] {os.path.basename(path)} :: {marker[:50]}")
            applied += 1
        if text != orig and not dry:
            bak = path + BAK_SUFFIX
            if path not in backed_up and not os.path.exists(bak):
                shutil.copy2(path, bak)
                print(f"  [backup] {bak}")
            backed_up.add(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

    # probe file
    if PROBE_SRC is None:
        print("  [warn] probe source missing next to applier — skipping probe write")
    elif os.path.exists(PROBE):
        print(f"  [skip] probe exists: {PROBE}")
    elif not dry:
        os.makedirs(os.path.dirname(PROBE), exist_ok=True)
        with open(PROBE, "w", encoding="utf-8") as f:
            f.write(PROBE_SRC)
        print(f"  [write] {PROBE}")
    else:
        print(f"  [would-write] {PROBE}")

    tag = "[DRY-RUN] " if dry else ""
    print(f"\n{tag}done — applied={applied} skipped={skipped} errors={errors}")
    if errors:
        print("  ! anchors missing — file drifted from expected version; NOTHING written for those.")
        sys.exit(1)
    if not dry:
        print("  -> restart:  ./start_backend.sh --force")
        print("  -> verify:   .venv/bin/python backend/scripts/backtest_trend_continuation_short.py NVDA TSLA")


if __name__ == "__main__":
    main()
