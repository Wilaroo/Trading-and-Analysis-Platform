#!/usr/bin/env python3
# v363 — SPENCER SCALP **DOCTRINE-FAITHFUL** intraday REPLAY (READ-ONLY, 1-min bars).
#
# SMB cheat-sheet structure (works LONG and SHORT — institutional accumulation/distribution):
#   1. A tight CONSOLIDATION of >= cons_len minutes (default 20) whose band is < cons_frac of the
#      day's range-so-far (default 0.20), located in the UPPER 1/3 of the day range (LONG) or the
#      LOWER 1/3 (SHORT).
#   2. A low-volume bar just before the break (1-2 bars < 70% of prior) then a VOLUME SURGE on break.
#   3. ENTRY: aggressive break of the range high (LONG) / low (SHORT).
#   4. STOP: .02 below range low (LONG) / .02 above range high (SHORT).
#   5. EXIT: measured-move SCALE-OUT — 1/3 at 1R, 1/3 at 2R, 1/3 at 3R; after 1R move stop to BE,
#      after 2R move stop to the 1R level. (--target-rmult X overrides with a single fixed X*R target.)
#   Time windows (doctrine): 09:59-16:00 ET. Invalidation hints (extended move / 3rd leg) NOT modeled
#   -> this replay is a SUPERSET of doctrine fires (slightly lower quality).
#
# Flags: --days --barsize(1 min) --universe --maxhold(bars) --cooldown(min) --cons-len(min)
#        --cons-frac --third(0.333) --vol-surge --side long|short|both --target-rmult(0=scaled)
#        --min-price($) --winstart/--winend(ET 09:59-16:00) --tz auto|utc|et --winsor(R)

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
    t = [E + R, E + 2 * R, E + 3 * R]
    hit = [False, False, False]
    stop = S; pos = 1.0; realized = 0.0
    for j in range(i + 1, end + 1):
        if l[j] <= stop:
            realized += pos * ((stop - E) / R); pos = 0.0; break
        if not hit[0] and h[j] >= t[0]:
            realized += (1.0 / 3.0) * 1.0; pos -= 1.0 / 3.0; hit[0] = True; stop = E
        if not hit[1] and h[j] >= t[1]:
            realized += (1.0 / 3.0) * 2.0; pos -= 1.0 / 3.0; hit[1] = True; stop = t[0]
        if not hit[2] and h[j] >= t[2]:
            realized += (1.0 / 3.0) * 3.0; pos = 0.0; break
    if pos > 0:
        realized += pos * ((c[end] - E) / R)
    return realized


def _scaled_short(h, l, c, i, end, E, S):
    R = S - E
    if R <= 0:
        return None
    t = [E - R, E - 2 * R, E - 3 * R]
    hit = [False, False, False]
    stop = S; pos = 1.0; realized = 0.0
    for j in range(i + 1, end + 1):
        if h[j] >= stop:
            realized += pos * ((E - stop) / R); pos = 0.0; break
        if not hit[0] and l[j] <= t[0]:
            realized += (1.0 / 3.0) * 1.0; pos -= 1.0 / 3.0; hit[0] = True; stop = E
        if not hit[1] and l[j] <= t[1]:
            realized += (1.0 / 3.0) * 2.0; pos -= 1.0 / 3.0; hit[1] = True; stop = t[0]
        if not hit[2] and l[j] <= t[2]:
            realized += (1.0 / 3.0) * 3.0; pos = 0.0; break
    if pos > 0:
        realized += pos * ((E - c[end]) / R)
    return realized


def _fixed(h, l, c, i, end, E, S, rmult, is_long):
    R = (E - S) if is_long else (S - E)
    if R <= 0:
        return None
    if is_long:
        tgt = E + rmult * R
        for j in range(i + 1, end + 1):
            if l[j] <= S:
                return (S - E) / R
            if h[j] >= tgt:
                return rmult
        return (c[end] - E) / R
    else:
        tgt = E - rmult * R
        for j in range(i + 1, end + 1):
            if h[j] >= S:
                return (E - S) / R
            if l[j] <= tgt:
                return rmult
        return (E - c[end]) / R


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
    maxhold = _arg('--maxhold', 60, int)
    cooldown = _arg('--cooldown', 10, int)
    cons_len = _arg('--cons-len', 20, int)
    cons_frac = _arg('--cons-frac', 0.20, float)
    third = _arg('--third', 0.333, float)
    vol_surge = _arg('--vol-surge', 1.0, float)  # break-bar vol >= vol_surge * window-avg (1.0=off-ish)
    side = _argstr('--side', 'both')
    target_rmult = _arg('--target-rmult', 0.0, float)
    min_price = _arg('--min-price', 0.0, float)
    win_start = _hhmm(_argstr('--winstart', '09:59'), time(9, 59))
    win_end = _hhmm(_argstr('--winend', '16:00'), time(16, 0))
    tz_assume = _argstr('--tz', 'auto')
    cap = _arg('--winsor', 3.0, float)

    db = _load_db()
    start_et = (datetime.now(timezone.utc) - timedelta(days=days)).astimezone(_ET)
    uni = Counter()
    for a in db.live_alerts.find({}, {'_id': 0, 'symbol': 1}):
        if a.get('symbol'):
            uni[a['symbol']] += 1
    syms = [s for s, _ in uni.most_common(uni_cap)]

    print(f"\n=== v363 SPENCER SCALP DOCTRINE replay — {days}d bar='{barsize}' "
          f"win={win_start.strftime('%H:%M')}-{win_end.strftime('%H:%M')}ET side={side} "
          f"cons>={cons_len}m band<{cons_frac:g}*dayRange third={third:g} volSurge>={vol_surge:g} "
          f"exit={'rmult='+str(target_rmult) if target_rmult>0 else 'scaled 1/3@1R,2R,3R'} "
          f"minPx>=${min_price:g} hold={maxhold}b tz={tz_assume} winsor=±{cap:g}R ===")
    print("NOTE: extended-move / 3rd-leg invalidations NOT modeled (superset of doctrine fires)\n")
    print(f"universe: {len(syms)} symbols\n")

    ev = {'long': [], 'short': []}
    n_sessions = 0; rth_ct = []; n_long_sig = 0; n_short_sig = 0

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

        for _d, sb in sessions.items():
            rb = [(et, b) for et, b in sb if RTH_OPEN <= et.time() < RTH_CLOSE]
            if len(rb) < cons_len + 5:
                continue
            n_sessions += 1; rth_ct.append(len(rb))
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
                win = range(i - cons_len, i)              # consolidation = prior cons_len bars
                wh = max(h[k] for k in win); wl = min(l[k] for k in win)
                band = wh - wl
                if band <= 0 or band > cons_frac * dr:
                    continue
                # volume: break bar surge vs window avg
                wv = [v[k] for k in win if v[k] > 0]
                if wv and v[i] < vol_surge * (sum(wv) / len(wv)):
                    continue
                end = min(i + maxhold, len(rb) - 1)
                # LONG: consolidation in UPPER third, break of range high
                if side in ('both', 'long') and wl >= lod + (1 - third) * dr and h[i] >= wh + 0.01:
                    E = round(wh + 0.01, 2); S = round(wl - 0.02, 2)
                    r = _fixed(h, l, c, i, end, E, S, target_rmult, True) if target_rmult > 0 \
                        else _scaled_long(h, l, c, i, end, E, S)
                    if r is not None:
                        ev['long'].append(round(r, 3)); n_long_sig += 1; last_fire = i; continue
                # SHORT: consolidation in LOWER third, break of range low
                if side in ('both', 'short') and wh <= lod + third * dr and l[i] <= wl - 0.01:
                    E = round(wl - 0.01, 2); S = round(wh + 0.02, 2)
                    r = _fixed(h, l, c, i, end, E, S, target_rmult, False) if target_rmult > 0 \
                        else _scaled_short(h, l, c, i, end, E, S)
                    if r is not None:
                        ev['short'].append(round(r, 3)); n_short_sig += 1; last_fire = i

    print("=== SANITY ===")
    if rth_ct:
        print(f"  sessions={n_sessions}  RTH bars/session median={int(median(rth_ct))} "
              f"(expect ~390 for 1-min). If far off, try --tz et / --barsize.")
    print(f"  long entries={n_long_sig}  short entries={n_short_sig}\n")

    print('=' * 84)
    print(f"[spencer_scalp DOCTRINE]  (>=20m tight range -> measured-move scaled exit)")
    _report('ALL', ev['long'] + ev['short'], cap)
    _report('LONG', ev['long'], cap)
    _report('SHORT', ev['short'], cap)
    print('=' * 84)
    print("\n=== READING ===")
    print("• winsorAvg/medR > 0 -> doctrine edge real -> REWRITE (entry=range break, stop=.02 beyond range,")
    print("  scaled 1R/2R/3R; add SHORT side). LONG +EV & SHORT -EV -> long-only. Both -EV -> suppress.")
    print("• Probes: --cons-frac 0.15 (tighter) ; --cons-len 25 ; --vol-surge 1.3 ; --target-rmult 2 ;")
    print("  --winend 11:00 (morning only) ; --min-price 10.")


if __name__ == '__main__':
    main()
