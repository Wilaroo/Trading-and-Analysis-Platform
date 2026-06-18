#!/usr/bin/env python3
# v358 — DAILY SQUEEZE (TTM Bollinger-inside-Keltner) REPLAY (READ-ONLY).
#
# Mirrors the live _check_daily_squeeze detector on '1 day' bars:
#   • BB(20,2) inside Keltner(20, 1.5*ATR)  -> squeeze ON
#   • adaptive tightness: bb_width < TIGHT * median(prior-20 bb_widths)
#   • direction from momentum (close vs SMA20)
#   • LIVE exits: stop = ATR-floored(min 1.5*ATR) anchored to 20-bar low/high;
#                 target = entry * 1.10 (long) / 0.90 (short)   [fixed ±10%]
#
# RESEARCH GOAL (no cheat sheet exists): is this +EV, and which trigger/exit geometry is best?
#   --trigger compression|release   compression = live (fire while squeezed); release = canonical
#                                    TTM (fire the bar the squeeze EXPANDS back outside Keltner)
#   --target  pct|atr               pct = live ±10%; atr = entry ± TMULT*ATR
#   --tmult <f>                     ATR target multiple (default 2.5)
#   --stopatr <f>                   min ATR mult for the floored stop (default 1.5, = live)
#   --tight <f>                     bb_width must be < tight * median prior width (default 0.7 = live)
#   --maxhold <d>                   max holding days (default 15)
#   --cooldown <d>                  min days between fires per symbol (default 5)
#   --minrr / --maxrr               optional R:R gate (0 = off)
#
# Usage (repo root, DGX):
#   .venv/bin/python backend/scripts/diag_v358_daily_squeeze_replay.py \
#       --days 365 --universe 400 --trigger compression --target pct --maxhold 15 --cooldown 5

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
    """20-period SMA, std (population), bb_upper/lower, width% at index i (incl i)."""
    w = closes[i - 19:i + 1]
    sma = sum(w) / 20.0
    std = (sum((c - sma) ** 2 for c in w) / 20.0) ** 0.5
    up = sma + 2 * std
    lo = sma - 2 * std
    width = (up - lo) / sma * 100.0 if sma > 0 else 999.0
    return sma, up, lo, width


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
    trigger = _argstr('--trigger', 'compression')
    target_mode = _argstr('--target', 'pct')
    tmult = _arg('--tmult', 2.5, float)
    stopatr = _arg('--stopatr', 1.5, float)
    tight = _arg('--tight', 0.7, float)
    maxhold = _arg('--maxhold', 15, int)
    cooldown = _arg('--cooldown', 5, int)
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

    print(f"\n=== v358 DAILY SQUEEZE replay — {days}d  bar='{barsize}'  trigger={trigger}  "
          f"target={target_mode}{('/'+str(tmult)+'ATR') if target_mode=='atr' else '/±10%'}  "
          f"stopATR={stopatr:g}  tight={tight:g}  hold={maxhold}d  cooldown={cooldown}d  "
          f"minRR={minrr:g} maxRR={_maxrr}  winsor=±{cap:g}R ===")
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
        if len(bars) < 60:
            continue
        highs = [b['high'] for b in bars]; lows = [b['low'] for b in bars]
        closes = [b['close'] for b in bars]

        # precompute bb_width + squeeze flags per index
        n = len(bars)
        width = [None] * n
        squeezed = [False] * n
        for i in range(19, n):
            sma, up, lo, wd = _bb(closes, i)
            width[i] = wd
            atr = _atr(highs, lows, closes, i, 14)
            kc_up = sma + 1.5 * atr
            kc_lo = sma - 1.5 * atr
            squeezed[i] = (up < kc_up and lo > kc_lo)

        last_entry = -999
        for i in range(40, n - 1):
            if i - last_entry < cooldown:
                continue
            sma, up, lo, wd = _bb(closes, i)
            atr = _atr(highs, lows, closes, i, 14)
            if atr <= 0:
                continue
            prior = [w for w in width[i - 20:i] if w is not None]
            if not prior:
                continue
            med = sorted(prior)[len(prior) // 2]

            fire = False
            if trigger == 'compression':
                fire = squeezed[i] and wd < tight * med
            elif trigger == 'release':
                fire = squeezed[i - 1] and (not squeezed[i]) and width[i - 1] is not None and width[i - 1] < tight * med
            if not fire:
                continue

            direction = 'long' if (closes[i] - sma) > 0 else 'short'
            entry = closes[i]
            if direction == 'long':
                anchor = min(lows[i - 19:i + 1]) - 0.02
                # ATR-floored stop: farther (lower) of structural anchor vs atr-floor
                stop = min(anchor, entry - atr * stopatr)
                tgt = entry * 1.10 if target_mode == 'pct' else entry + tmult * atr
            else:
                anchor = max(highs[i - 19:i + 1]) + 0.02
                stop = max(anchor, entry + atr * stopatr)
                tgt = entry * 0.90 if target_mode == 'pct' else entry - tmult * atr

            risk = abs(entry - stop)
            if risk <= 0:
                continue
            rr = abs(tgt - entry) / risk
            if minrr > 0 and rr < minrr:
                continue
            if maxrr > 0 and rr > maxrr:
                continue

            n_ev += 1; last_entry = i
            end = min(i + maxhold, n - 1)
            r = None
            for j in range(i + 1, end + 1):
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

    print(f'DAILY SQUEEZE events={n_ev}\n')
    print('=' * 88)
    _report('ALL', rs, rrs, cap)
    _report('LONG', by_dir['long'], None, cap)
    _report('SHORT', by_dir['short'], None, cap)
    print('-' * 88)
    for k in ('<1.0', '1.0-1.5', '1.5-2.5', '>=2.5'):
        _report('RR ' + k, by_rr.get(k, []), [rr for rr in rrs if _rr_bucket(rr) == k], cap)
    print('=' * 88)
    print('\n=== READING ===')
    print('• winsorAvg/medR > 0 overall -> setup is +EV (keep/tune). Negative everywhere -> suppress.')
    print('• Compare --trigger compression (LIVE) vs --trigger release (canonical TTM).')
    print('• Compare --target pct (LIVE ±10%) vs --target atr --tmult 2.0/2.5/3.0 for a viable geometry.')
    print('• If only a R:R band is +EV, add that gate (like ORB/second_chance).')
    print('• Probes: --tight 0.5 (tighter) ; --maxhold 10/20 ; --stopatr 1.0/2.0.\n')


if __name__ == '__main__':
    main()
