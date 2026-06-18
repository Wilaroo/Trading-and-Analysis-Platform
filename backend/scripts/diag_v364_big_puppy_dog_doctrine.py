#!/usr/bin/env python3
# v364 — BIG DOG / PUPPY DOG **DOCTRINE-FAITHFUL** intraday REPLAY (READ-ONLY, 1-min bars, LONG).
#
# SMB cheat-sheet structure the current code misses (per v361b re-audit):
#   • BIG DOG: wedge/flag/pennant holding ABOVE the PRIOR-DAY HIGH, MID-DAY break (11:00-13:30 ET),
#     consolidation <= cons_frac of the day range on DECLINING volume; ENTER break of range high,
#     STOP .02 below range low, Move2Move exit (scaled 1R/2R/3R here).
#   • PUPPY DOG: same engine, smaller/faster — shorter consolidation, not PDH/midday-restricted
#     (run with --cons-len 5 --no-pdh --winstart 09:45 --winend 16:00).
#
# Compare verdict vs the SHIPPED v361 big_dog (tightened proxy: +0.097R win53% n=268).
#
# Flags: --days --barsize(1 min) --universe --maxhold(bars) --cooldown(min) --cons-len(bars)
#        --cons-frac(of day range) --vol-decline --upper-third(0=off) --require-pdh/--no-pdh
#        --target-rmult(0=scaled 1/3@1R,2R,3R) --min-price($) --winstart/--winend(ET 11:00-13:30)
#        --tz auto|utc|et --winsor(R)

import sys
from collections import defaultdict, Counter
from datetime import datetime, time, timedelta, timezone
from statistics import median, mean

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York"); _UTC = ZoneInfo("UTC")
except Exception:
    _ET = timezone(timedelta(hours=-5)); _UTC = timezone.utc

RTH_OPEN = time(9, 30); RTH_CLOSE = time(16, 0)


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _argstr(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _hhmm(s, default):
    try:
        h, m = s.split(':'); return time(int(h), int(m))
    except Exception:
        return default


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


def _to_et(raw, assume):
    dt = None
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        dt = datetime.fromtimestamp(ts, tz=_UTC)
    elif isinstance(raw, str):
        s = raw.strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_ET) if assume == 'et' else dt.replace(tzinfo=_UTC).astimezone(_ET)
    return dt.astimezone(_ET)


def _scaled_long(h, l, c, i, end, E, S):
    R = E - S
    if R <= 0:
        return None
    t = [E + R, E + 2 * R, E + 3 * R]; hit = [False, False, False]
    stop = S; pos = 1.0; realized = 0.0
    for j in range(i + 1, end + 1):
        if l[j] <= stop:
            realized += pos * ((stop - E) / R); pos = 0.0; break
        if not hit[0] and h[j] >= t[0]:
            realized += (1 / 3) * 1.0; pos -= 1 / 3; hit[0] = True; stop = E
        if not hit[1] and h[j] >= t[1]:
            realized += (1 / 3) * 2.0; pos -= 1 / 3; hit[1] = True; stop = t[0]
        if not hit[2] and h[j] >= t[2]:
            realized += (1 / 3) * 3.0; pos = 0.0; break
    if pos > 0:
        realized += pos * ((c[end] - E) / R)
    return realized


def _fixed_long(h, l, c, i, end, E, S, rmult):
    R = E - S
    if R <= 0:
        return None
    tgt = E + rmult * R
    for j in range(i + 1, end + 1):
        if l[j] <= S:
            return (S - E) / R
        if h[j] >= tgt:
            return rmult
    return (c[end] - E) / R


def _report(label, rs, cap):
    if not rs:
        print(f'  {label:<10} n=0'); return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f'  {label:<10} n={len(rs):<5} win={100.0*w/len(rs):>3.0f}%  winsorAvg={mean(wr):+.3f}  '
          f'medR={median(rs):+.3f}  totW={sum(wr):+.1f}')


def main():
    days = _arg('--days', 180, int)
    barsize = _argstr('--barsize', '1 min')
    uni_cap = _arg('--universe', 300, int)
    maxhold = _arg('--maxhold', 45, int)
    cooldown = _arg('--cooldown', 10, int)
    cons_len = _arg('--cons-len', 10, int)
    cons_frac = _arg('--cons-frac', 0.50, float)
    vol_decline = _arg('--vol-decline', 0.7, float)
    upper_third = _arg('--upper-third', 0.667, float)  # 0 = disable upper-portion gate
    require_pdh = '--no-pdh' not in sys.argv
    target_rmult = _arg('--target-rmult', 0.0, float)
    min_price = _arg('--min-price', 0.0, float)
    win_start = _hhmm(_argstr('--winstart', '11:00'), time(11, 0))
    win_end = _hhmm(_argstr('--winend', '13:30'), time(13, 30))
    tz_assume = _argstr('--tz', 'auto')
    cap = _arg('--winsor', 3.0, float)

    db = _load_db()
    start_et = (datetime.now(timezone.utc) - timedelta(days=days)).astimezone(_ET)
    uni = Counter()
    for a in db.live_alerts.find({}, {'_id': 0, 'symbol': 1}):
        if a.get('symbol'):
            uni[a['symbol']] += 1
    syms = [s for s, _ in uni.most_common(uni_cap)]

    print(f"\n=== v364 BIG/PUPPY DOG DOCTRINE replay — {days}d bar='{barsize}' "
          f"win={win_start.strftime('%H:%M')}-{win_end.strftime('%H:%M')}ET cons>={cons_len}bar "
          f"band<{cons_frac:g}*dayRange volDecl<={vol_decline:g} upperThird={upper_third:g} "
          f"PDH={'on' if require_pdh else 'off'} "
          f"exit={'rmult='+str(target_rmult) if target_rmult>0 else 'scaled 1/3@1R,2R,3R'} "
          f"minPx>=${min_price:g} hold={maxhold}b tz={tz_assume} winsor=±{cap:g}R ===")
    print("NOTE: rvol / news / >75%-above-open / HTF-resistance gates NOT modeled (superset)\n")
    print(f"universe: {len(syms)} symbols\n")

    ev = []
    n_sessions = 0; rth_ct = []; n_pdh_ok = 0; n_entries = 0

    for sym in syms:
        rows = []
        for b in db.ib_historical_data.find(
                {'symbol': sym, 'bar_size': barsize},
                {'_id': 0, 'date': 1, 'timestamp': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1}):
            if not (b.get('close') and b.get('high') and b.get('low') and b.get('open')):
                continue
            et = _to_et(b.get('timestamp') if b.get('timestamp') is not None else b.get('date'), tz_assume)
            if et is None or et < start_et:
                continue
            rows.append((et, b))
        if len(rows) < 60:
            continue
        rows.sort(key=lambda x: x[0])
        sessions = defaultdict(list)
        for et, b in rows:
            sessions[et.date()].append((et, b))
        sdates = sorted(sessions.keys())
        prev_day_high = None

        for _d in sdates:
            sb = sessions[_d]
            rb = [(et, b) for et, b in sb if RTH_OPEN <= et.time() < RTH_CLOSE]
            this_high = max((b['high'] for _, b in rb), default=None)
            if len(rb) < cons_len + 5:
                if this_high is not None:
                    prev_day_high = this_high
                continue
            n_sessions += 1; rth_ct.append(len(rb))
            pdh = prev_day_high
            prev_day_high = this_high
            ets = [et for et, _ in rb]
            h = [b['high'] for _, b in rb]; l = [b['low'] for _, b in rb]
            c = [b['close'] for _, b in rb]; v = [(b.get('volume') or 0) for _, b in rb]
            hod = h[0]; lod = l[0]; last_fire = -999
            for i in range(cons_len + 1, len(rb)):
                hod = max(hod, h[i]); lod = min(lod, l[i])
                if i - last_fire < cooldown:
                    continue
                if not (win_start <= ets[i].time() <= win_end):
                    continue
                cp = c[i]
                if cp < min_price:
                    continue
                dr = hod - lod
                if dr <= 0:
                    continue
                win = range(i - cons_len, i)
                wh = max(h[k] for k in win); wl = min(l[k] for k in win)
                band = wh - wl
                if band <= 0 or band > cons_frac * dr:
                    continue
                if require_pdh and not (pdh and wl >= pdh):       # holding above prior-day high
                    continue
                if upper_third > 0 and wl < lod + upper_third * dr:
                    continue
                wv = [v[k] for k in win if v[k] > 0]
                pre = [v[k] for k in range(max(0, i - 2 * cons_len), i - cons_len) if v[k] > 0]
                if wv and pre and (mean(wv) > vol_decline * mean(pre)):   # declining volume
                    continue
                if h[i] < wh + 0.01:                              # range-break must print
                    continue
                E = round(wh + 0.01, 2); S = round(wl - 0.02, 2)
                if E <= S:
                    continue
                end = min(i + maxhold, len(rb) - 1)
                r = _fixed_long(h, l, c, i, end, E, S, target_rmult) if target_rmult > 0 \
                    else _scaled_long(h, l, c, i, end, E, S)
                if r is not None:
                    ev.append(round(r, 3)); n_entries += 1; last_fire = i
                if require_pdh:
                    n_pdh_ok += 1

    print("=== SANITY ===")
    if rth_ct:
        print(f"  sessions={n_sessions}  RTH bars/session median={int(median(rth_ct))} "
              f"(expect ~390 for 1-min). If far off, try --tz et / --barsize.")
    print(f"  range-break entries={n_entries}\n")
    print('=' * 84)
    print(f"[big/puppy dog DOCTRINE]  (consolidation breakout -> measured-move) vs v361 ship +0.097R")
    _report('LONG', ev, cap)
    print('=' * 84)
    print("\n=== READING ===")
    print("• winsorAvg > v361's +0.097R with healthy n -> rewrite to doctrine wins. <= +0.097 -> keep v361.")
    print("• Probes: --cons-frac 0.3 ; --cons-len 15 ; --target-rmult 2 ; --no-pdh (puppy) ;")
    print("  PUPPY: --cons-len 5 --no-pdh --winstart 09:45 --winend 16:00 --upper-third 0.5")


if __name__ == '__main__':
    main()
