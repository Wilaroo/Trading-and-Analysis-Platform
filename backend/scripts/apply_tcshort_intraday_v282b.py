#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_tcshort_intraday_v282b.py — IDEMPOTENT applier for v19.34.282b
Refines trend_continuation_short (built in v282):
  1. Removes the DAILY-loop registration (the daily path doesn't auto-execute
     and would dedup-block the intraday one).
  2. Adds a self-contained 5-min INTRADAY block inside _scan_symbol_all_setups
     that flows through the SAME AI/TQS enrichment + auto-execute pipeline
     (so it fires + auto-executes on intraday staircase-down days like today).
  3. Tightens the entry: clean pullback-to-EMA only (dist -0.5%..+0.5%) and
     rejects R:R < 1.5 (kills the low-quality late shorts seen in the backtest).
  4. Rewrites the backtest probe to match the tightened logic.

REQUIRES v19.34.282 already applied. Idempotent (global guard).

RUN ON DGX (repo root):
    .venv/bin/python /tmp/apply_tcshort_intraday_v282b.py --dry-run
    .venv/bin/python /tmp/apply_tcshort_intraday_v282b.py
then:
    .venv/bin/python backend/scripts/backtest_trend_continuation_short.py NVDA TSLA
    ./start_backend.sh --force
"""
import argparse
import os
import shutil
import sys

BAK_SUFFIX = ".bak.tcshort0605b"
REPO = os.getcwd()
SCANNER = os.path.join(REPO, "backend/services/enhanced_scanner.py")
PROBE = os.path.join(REPO, "backend/scripts/backtest_trend_continuation_short.py")

GLOBAL_MARKER = "v19.34.282b — intraday trend-continuation SHORT (bars-based on 5-min"

# (old, new) edits applied in order, only when GLOBAL_MARKER is absent.
SCANNER_EDITS = [
    # 1) remove daily-loop registration
    ('''                    for check in [
                        self._check_daily_squeeze,
                        self._check_trend_continuation,
                        self._check_trend_continuation_short,  # v19.34.282
                        self._check_daily_breakout,''',
     '''                    for check in [
                        self._check_daily_squeeze,
                        self._check_trend_continuation,
                        self._check_daily_breakout,'''),

    # 2) tighten entry band
    ('''        current = closes[-1]
        dist_from_ema = (current - ema20) / ema20 * 100
        if dist_from_ema > 0.5 or dist_from_ema < -2.0:
            return None  # Not in the pullback-to-EMA short zone''',
     '''        current = closes[-1]
        dist_from_ema = (current - ema20) / ema20 * 100
        if dist_from_ema > 0.5 or dist_from_ema < -0.5:
            return None  # v19.34.282b — tightened: clean pullback-to-EMA only'''),

    # 3) reject low R:R
    ('''        stop = round(ema20 + atr * 1.5, 2)
        target = round(current - atr * 3, 2)
        rr = abs(current - target) / abs(stop - current) if abs(stop - current) > 0 else 0

        return LiveAlert(
            id=f"trend_continuation_short_{symbol}_{datetime.now().strftime('%H%M%S')}",''',
     '''        stop = round(ema20 + atr * 1.5, 2)
        target = round(current - atr * 3, 2)
        rr = abs(current - target) / abs(stop - current) if abs(stop - current) > 0 else 0
        if rr < 1.5:
            return None  # v19.34.282b — skip low-quality late entries

        return LiveAlert(
            id=f"trend_continuation_short_{symbol}_{datetime.now().strftime('%H%M%S')}",'''),

    # 4) intraday 5-min block (auto-execute path)
    ('''            # Process all alerts for this symbol - AI ENRICHMENT first, then TQS SCORING
            # GAP 2 FIX: AI enrichment runs first so TQS can incorporate AI model alignment
            for alert in alerts:''',
     '''            # v19.34.282b — intraday trend-continuation SHORT (bars-based on 5-min
            # data). Bars-based so it can't go through _check_setup (snapshot/tape);
            # gated to ~every 2.5 min (5-min bars only change every 5 min) to bound
            # DB cost. Appended to `alerts` so it inherits the SAME AI/TQS enrichment
            # + auto-execute loop below. Eligibility mirrors the snapshot path.
            if self._scan_count % 10 == 0:
                try:
                    _fmb = self.technical_service._get_intraday_bars_from_db(symbol, "5 mins", 60)
                    if _fmb and len(_fmb) >= 25:
                        _tcs = await self._check_trend_continuation_short(symbol, _fmb)
                        if _tcs is not None:
                            _tcs.time_window = "INTRADAY"
                            _tcs.trade_style = "intraday"
                            _tcs.scan_tier = "intraday"
                            _tcs.strategy_win_rate = self._auto_execute_min_win_rate
                            _tcs.tape_score = round((tape.tape_score + 1.0) * 5.0, 2)
                            _tcs.tape_confirmation = tape.confirmation_for_short
                            _tcs.rvol = float(getattr(snapshot, "rvol", 0.0) or 0.0)
                            _tcs.calculate_r_multiple()
                            try:
                                _tcs.grade_trade(strategy_ev=0.0, market_context_score=0.5)
                            except Exception:
                                pass
                            _tcs.auto_execute_eligible = (
                                self._auto_execute_enabled and
                                _tcs.priority.value in [AlertPriority.CRITICAL.value, AlertPriority.HIGH.value] and
                                _tcs.tape_confirmation and
                                _tcs.strategy_win_rate >= self._auto_execute_min_win_rate
                            )
                            alerts.append(_tcs)
                except Exception:
                    pass

            # Process all alerts for this symbol - AI ENRICHMENT first, then TQS SCORING
            # GAP 2 FIX: AI enrichment runs first so TQS can incorporate AI model alignment
            for alert in alerts:'''),
]


PROBE_SRC = r'''#!/usr/bin/env python3
"""
backtest_trend_continuation_short.py  (v19.34.282b) — READ-ONLY.

Replays a symbol's real bars (from ib_historical_data) through the EXACT gating
logic of enhanced_scanner._check_trend_continuation_short (tightened: clean
pullback-to-EMA only, R:R >= 1.5) and prints every bar where the SHORT setup
WOULD have fired, across timeframes.

Usage (DGX, from repo root):
    .venv/bin/python backend/scripts/backtest_trend_continuation_short.py
    .venv/bin/python backend/scripts/backtest_trend_continuation_short.py NVDA TSLA AAPL

Touches nothing — pure read + math.
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
    """EXACT replica of _check_trend_continuation_short gating (v282b tightened)."""
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
        return None

    recent_highs = [max(highs[-15:-10]), max(highs[-10:-5]), max(highs[-5:])]
    recent_lows = [min(lows[-15:-10]), min(lows[-10:-5]), min(lows[-5:])]
    lh = all(recent_highs[i] < recent_highs[i - 1] for i in range(1, 3))
    ll = all(recent_lows[i] < recent_lows[i - 1] for i in range(1, 3))
    if not (lh and ll):
        return None

    current = closes[-1]
    dist = (current - ema20) / ema20 * 100
    if dist > 0.5 or dist < -0.5:
        return None

    atrs = []
    for i in range(1, min(15, len(bars))):
        tr = max(highs[-i] - lows[-i], abs(highs[-i] - closes[-(i + 1)]), abs(lows[-i] - closes[-(i + 1)]))
        atrs.append(tr)
    atr = sum(atrs) / len(atrs) if atrs else current * 0.02
    stop = round(ema20 + atr * 1.5, 2)
    target = round(current - atr * 3, 2)
    rr = abs(current - target) / abs(stop - current) if abs(stop - current) > 0 else 0
    if rr < 1.5:
        return None
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
    print(f"  {bar_size:8} : {len(bars)} bars (latest {bars[-1].get('date')}) -> "
          f"{len(fires)} fire-point(s)")
    for when, r in fires[:8]:
        print(f"      FIRE @ {when}  px={r['price']} ema20={r['ema20']} "
              f"dist={r['dist_pct']}%  stop={r['stop']} tgt={r['target']} rr={r['rr']}:1")
    if len(fires) > 8:
        print(f"      ... +{len(fires) - 8} more")


def main():
    symbols = [s.upper() for s in sys.argv[1:]] or ["NVDA", "TSLA"]
    env = _load_env()
    db = MongoClient(env["MONGO_URL"])[env.get("DB_NAME", "tradecommand")]
    print(f"\n=== backtest trend_continuation_short (v282b) — {datetime.now(timezone.utc).isoformat()} ===")
    for sym in symbols:
        print(f"\n[{sym}]")
        replay(db, sym, "1 day", 120)
        replay(db, sym, "5 mins", 400)
        replay(db, sym, "1 min", 800)
    print("\nLive: the detector now runs on the 5-min INTRADAY path (auto-execute).")
    print("The '5 mins' rows are the live-equivalent timeframe.\n")


if __name__ == "__main__":
    main()
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    if not os.path.isfile(SCANNER):
        print(f"[FATAL] not found: {SCANNER}\n  -> run from repo root (~/Trading-and-Analysis-Platform)")
        sys.exit(2)

    with open(SCANNER, "r", encoding="utf-8") as f:
        text = f.read()
    orig = text

    if GLOBAL_MARKER in text:
        print("  [skip] enhanced_scanner.py already at v282b")
    else:
        if "_check_trend_continuation_short" not in text:
            print("  [FATAL] v19.34.282 not detected (no _check_trend_continuation_short). Apply v282 first.")
            sys.exit(2)
        for i, (old, new) in enumerate(SCANNER_EDITS, 1):
            if old not in text:
                print(f"  [ERROR] edit {i} anchor not found — aborting, NOTHING written.")
                sys.exit(1)
            text = text.replace(old, new, 1)
            print(f"  [apply] enhanced_scanner.py edit {i}/4")
        if not dry:
            bak = SCANNER + BAK_SUFFIX
            if not os.path.exists(bak):
                shutil.copy2(SCANNER, bak)
                print(f"  [backup] {bak}")
            with open(SCANNER, "w", encoding="utf-8") as f:
                f.write(text)

    # probe (rewrite to tightened version)
    cur = open(PROBE, encoding="utf-8").read() if os.path.exists(PROBE) else None
    if cur == PROBE_SRC:
        print("  [skip] probe already current")
    elif not dry:
        if cur is not None and not os.path.exists(PROBE + BAK_SUFFIX):
            shutil.copy2(PROBE, PROBE + BAK_SUFFIX)
        os.makedirs(os.path.dirname(PROBE), exist_ok=True)
        with open(PROBE, "w", encoding="utf-8") as f:
            f.write(PROBE_SRC)
        print(f"  [write] {PROBE}")
    else:
        print(f"  [would-write] {PROBE}")

    tag = "[DRY-RUN] " if dry else ""
    changed = (text != orig)
    print(f"\n{tag}done — scanner_changed={changed}")
    if not dry:
        print("  -> verify:  .venv/bin/python backend/scripts/backtest_trend_continuation_short.py NVDA TSLA")
        print("  -> live:    ./start_backend.sh --force")


if __name__ == "__main__":
    main()
