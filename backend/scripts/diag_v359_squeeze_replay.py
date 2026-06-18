#!/usr/bin/env python3
# v359 — intraday `squeeze` detector REPLAY (READ-ONLY).
#
# IMPORTANT: the live _check_squeeze relies on snapshot fields (squeeze_on / squeeze_fire /
# bb_width / bb_upper / bb_lower / atr / rvol) that realtime_technical_service builds from
# **DAILY bars** (daily_closes, _calculate_atr(daily_bars,14), 20d rvol). So the "intraday"
# squeeze is really a DAILY-timeframe signal evaluated live — same BB-inside-Keltner structure
# as daily_squeeze, but with a DIFFERENT gate + exit geometry:
#   • gate:    squeeze_on (BB inside KC) AND rvol >= 1.0      (NO adaptive-tightness gate)
#   • dir:     squeeze_fire = (cp - bb_middle)/atr ; long if > 0 else short
#   • entry:   long = max(bb_upper, cp) ; short = min(bb_lower, cp)
#   • stop:    long = max(bb_lower, entry - 1.0*atr) ; short = min(bb_upper, entry + 1.0*atr)
#   • target:  entry +/- 2.5*atr
# This replays that exact geometry on '1 day' IB bars and scores realized R.
#
# Flags: --days --universe --maxhold --cooldown --minrr --maxrr --winsor
#        --entry immediate|trigger   (immediate = fill at `entry` on signal bar [default];
#                                      trigger = only count if a later bar trades through entry)
#
# Usage (repo root, DGX):
#   .venv/bin/python backend/scripts/diag_v359_squeeze_replay.py --days 365 --universe 400 --maxhold 10

import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median, mean


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _argstr(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _load_db():
    env = {}
    with open('backend/.env') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env['MONGO_URL'], serverSelectionTimeoutMS=20000)[env['DB_NAME']]


def _atr(highs, lows, closes, i, n=14):
    trs = []
    for k in range(max(1, i - n + 1), i + 1):
        trs.append(max(highs[k] - lows[k], abs(highs[k] - closes[k - 1]), abs(lows[k] - closes[k - 1])))
    return (sum(trs) / len(trs)) if trs else 0.0


def _bb(closes, i):
    w = closes[i - 19:i + 1]
    sma = sum(w) / 20.0
    std = (sum((c - sma) ** 2 for c in w) / 20.0) ** 0.5
    return sma, sma + 2 * std, sma - 2 * std, ((4 * std) / sma * 100.0 if sma > 0 else 999.0)


def _rr_bucket(rr):
    if rr < 1.0:
        return '<1.0'
    if rr < 1.5:
        return '1.0-1.5'
    if rr < 2.5:
        return '1.5-2.5'
    return '>=2.5'


def _report(label, rs, rrs, cap):
    if not rs:
        print(f'  {label:<20} n=0'); return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f'  {label:<20} n={len(rs):<5} win={100.0*w/len(rs):>3.0f}%  winsorAvg={mean(wr):+.3f}  '
          f'medR={median(rs):+.3f}  totW={sum(wr):+.1f}  avgRR={mean(rrs) if rrs else 0:.2f}')


def main():
    days = _arg('--days', 365, int)
    barsize = _argstr('--barsize', '1 day')
    uni_cap = _arg('--universe', 400, int)
    maxhold = _arg('--maxhold', 10, int)
    cooldown = _arg('--cooldown', 5, int)
    entry_mode = _argstr('--entry', 'immediate')
    minrr = _arg('--minrr', 0.0, float)
    maxrr = _arg('--maxrr', 0.0, float)
    cap = _arg('--winsor', 3.0, float)

    db = _load_db()
    start = datetime.now(timezone.utc) - timedelta(days=days)
    universe = Counter()
    for a in db.live_alerts.find({}, {'_id': 0, 'symbol': 1}):
        if a.get('symbol'):
            universe[a['symbol']] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]
    _maxrr = f'{maxrr:g}' if maxrr > 0 else 'off'

    print(f"\n=== v359 SQUEEZE (intraday detector, daily-derived) replay — {days}d  bar='{barsize}'  "
          f"entry={entry_mode}  hold={maxhold}d  cooldown={cooldown}d  minRR={minrr:g} maxRR={_maxrr}  "
          f"winsor=±{cap:g}R ===")
    print(f'universe: {len(syms)} symbols\n')

    rs, rrs = [], []
    by_rr = defaultdict(list)
    by_dir = {'long': [], 'short': []}
    n_ev = 0

    for sym in syms:
        cur = db.ib_historical_data.find(
            {'symbol': sym, 'bar_size': barsize},
            {'_id': 0, 'date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1}).sort('date', 1)
        bars = [b for b in cur if b.get('close') and b.get('high') and b.get('low')]
        if len(bars) < 40:
            continue
        highs = [b['high'] for b in bars]; lows = [b['low'] for b in bars]
        closes = [b['close'] for b in bars]; vols = [b.get('volume') or 0 for b in bars]
        n = len(bars)
        last_entry = -999
        for i in range(20, n - 1):
            if i - last_entry < cooldown:
                continue
            sma, bb_up, bb_lo, _w = _bb(closes, i)
            atr = _atr(highs, lows, closes, i, 14)
            if atr <= 0 or sma <= 0:
                continue
            kc_up = sma + 1.5 * atr
            kc_lo = sma - 1.5 * atr
            squeeze_on = bb_up < kc_up and bb_lo > kc_lo
            if not squeeze_on:
                continue
            avg_vol = sum(vols[i - 20:i]) / 20.0 if i >= 20 else 0
            rvol = (vols[i] / avg_vol) if avg_vol > 0 else 0
            if rvol < 1.0:
                continue

            cp = closes[i]
            fire = (cp - sma) / atr
            direction = 'long' if fire > 0 else 'short'
            if direction == 'long':
                entry = max(bb_up, cp)
                stop = max(bb_lo, entry - atr * 1.0)
                tgt = entry + 2.5 * atr
            else:
                entry = min(bb_lo, cp)
                stop = min(bb_up, entry + atr * 1.0)
                tgt = entry - 2.5 * atr
            risk = abs(entry - stop)
            if risk <= 0:
                continue
            rr = abs(tgt - entry) / risk
            if minrr > 0 and rr < minrr:
                continue
            if maxrr > 0 and rr > maxrr:
                continue

            end = min(i + maxhold, n - 1)
            # entry fill
            jstart = i + 1
            filled = True
            if entry_mode == 'trigger':
                filled = False
                for j in range(i + 1, end + 1):
                    if (direction == 'long' and highs[j] >= entry) or (direction == 'short' and lows[j] <= entry):
                        jstart = j + 1
                        filled = True
                        break
            if not filled:
                continue

            n_ev += 1; last_entry = i
            r = None
            for j in range(jstart, end + 1):
                if direction == 'long':
                    if lows[j] <= stop:
                        r = (stop - entry) / risk; break
                    if highs[j] >= tgt:
                        r = (tgt - entry) / risk; break
                else:
                    if highs[j] >= stop:
                        r = (entry - stop) / risk; break
                    if lows[j] <= tgt:
                        r = (entry - tgt) / risk; break
            if r is None:
                r = ((closes[end] - entry) if direction == 'long' else (entry - closes[end])) / risk
            r = round(r, 3)
            rs.append(r); rrs.append(rr); by_rr[_rr_bucket(rr)].append(r); by_dir[direction].append(r)

    print(f'SQUEEZE events={n_ev}\n')
    print('=' * 88)
    _report('ALL', rs, rrs, cap)
    _report('LONG', by_dir['long'], None, cap)
    _report('SHORT', by_dir['short'], None, cap)
    print('-' * 88)
    for k in ('<1.0', '1.0-1.5', '1.5-2.5', '>=2.5'):
        _report('RR ' + k, by_rr.get(k, []), [rr for rr in rrs if _rr_bucket(rr) == k], cap)
    print('=' * 88)
    print('\n=== READING ===')
    print('• This is the LIVE _check_squeeze geometry (no tightness gate, rvol>=1, 2.5*ATR target,')
    print('  1*ATR-clamped stop). winsorAvg/medR > 0 -> +EV. Negative everywhere -> suppress.')
    print('• Compare LONG vs SHORT — daily_squeeze (v358) was long-only; expect the same here.')
    print('• Compare --entry immediate vs --entry trigger (buy-stop fills only).')
    print('• If only a R:R band is +EV, add that gate. Probes: --maxhold 5/20 --cooldown 3.\n')


if __name__ == '__main__':
    main()
