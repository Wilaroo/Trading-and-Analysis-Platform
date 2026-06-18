#!/usr/bin/env python3
# v360 — FIRST MOVE UP/DOWN (morning fade) intraday REPLAY (READ-ONLY).
#
# Mirrors the live morning mean-reversion fades on intraday bars:
#   first_move_up   = SHORT — fade a first-morning push to HOD back to VWAP/open
#       gates: push=(HOD-open)/open >=1.5% ; cp within 0.5% of HOD ; RSI14>=68 ;
#              dist_from_vwap >= +1.0% ; (live also rvol>=1.5 — see NOTE)
#       entry=cp ; stop=HOD+0.25*ATR ; target=max(VWAP, open)
#   first_move_down = LONG  — mirror (flush to LOD, RSI14<=32, dist_from_vwap<=-1.0%)
#       entry=cp ; stop=LOD-0.25*ATR ; target=min(VWAP, open)
#
# NOTE: the live rvol gate is a DAILY 20-day volume ratio (not reconstructable per intraday bar
# here), so it is NOT applied — this replay is a SUPERSET of live fires (slightly lower quality).
# Everything else (push%, HOD/LOD proximity, RSI14, dist-from-VWAP, geometry) is faithful.
#
# Flags: --days --barsize --universe --maxhold(bars) --cooldown(bars) --side up|down|both
#        --winstart/--winend (ET morning window, default 09:30-11:00) --tz auto|utc|et
#        --rsi-up/--rsi-dn --push --winsor

import sys
from collections import defaultdict
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


def _atr_at(h, l, c, i, n=14):
    trs = []
    for k in range(max(1, i - n + 1), i + 1):
        trs.append(max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])))
    return (sum(trs) / len(trs)) if trs else 0.0


def _rsi_series(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [0.0]; losses = [0.0]
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    ag = sum(gains[1:n + 1]) / n; al = sum(losses[1:n + 1]) / n
    out[n] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    return out


def _report(label, rs, rrs, cap):
    if not rs:
        print(f'  {label:<22} n=0'); return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f'  {label:<22} n={len(rs):<5} win={100.0*w/len(rs):>3.0f}%  winsorAvg={mean(wr):+.3f}  '
          f'medR={median(rs):+.3f}  totW={sum(wr):+.1f}  avgRR={mean(rrs) if rrs else 0:.2f}')


def main():
    days = _arg('--days', 180, int)
    barsize = _argstr('--barsize', '5 mins')
    uni_cap = _arg('--universe', 300, int)
    maxhold = _arg('--maxhold', 18, int)
    cooldown = _arg('--cooldown', 6, int)
    side = _argstr('--side', 'both')
    win_start = _hhmm(_argstr('--winstart', '09:30'), time(9, 30))
    win_end = _hhmm(_argstr('--winend', '11:00'), time(11, 0))
    tz_assume = _argstr('--tz', 'auto')
    rsi_up = _arg('--rsi-up', 68.0, float)
    rsi_dn = _arg('--rsi-dn', 32.0, float)
    push_min = _arg('--push', 1.5, float)
    cap = _arg('--winsor', 3.0, float)

    db = _load_db()
    start_et = (datetime.now(timezone.utc) - timedelta(days=days)).astimezone(_ET)
    from collections import Counter
    uni = Counter()
    for a in db.live_alerts.find({}, {'_id': 0, 'symbol': 1}):
        if a.get('symbol'):
            uni[a['symbol']] += 1
    syms = [s for s, _ in uni.most_common(uni_cap)]

    print(f"\n=== v360 FIRST MOVE replay — {days}d bar='{barsize}' side={side} "
          f"win={win_start.strftime('%H:%M')}-{win_end.strftime('%H:%M')}ET RSI up>={rsi_up:g}/dn<={rsi_dn:g} "
          f"push>={push_min:g}% hold={maxhold}b cooldown={cooldown}b tz={tz_assume} winsor=±{cap:g}R ===")
    print("NOTE: live daily-rvol>=1.5 gate NOT applied (superset of live fires)\n")
    print(f"universe: {len(syms)} symbols\n")

    ev = {'first_move_up': [], 'first_move_down': []}
    n_sessions = 0; rth_ct = []

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
        if len(rows) < 30:
            continue
        rows.sort(key=lambda x: x[0])
        sessions = defaultdict(list)
        for et, b in rows:
            sessions[et.date()].append((et, b))

        for _d, sb in sessions.items():
            rb = [(et, b) for et, b in sb if RTH_OPEN <= et.time() < RTH_CLOSE]
            if len(rb) < 20:
                continue
            n_sessions += 1; rth_ct.append(len(rb))
            ets = [et for et, _ in rb]
            o = [b['open'] for _, b in rb]; h = [b['high'] for _, b in rb]
            l = [b['low'] for _, b in rb]; c = [b['close'] for _, b in rb]
            v = [(b.get('volume') or 0) for _, b in rb]
            day_open = o[0]
            rsi = _rsi_series(c, 14)
            vwap = []; cum_pv = 0.0; cum_v = 0.0
            for k in range(len(rb)):
                tp = (h[k] + l[k] + c[k]) / 3.0
                vol = v[k] if v[k] > 0 else 1.0
                cum_pv += tp * vol; cum_v += vol
                vwap.append(cum_pv / cum_v if cum_v > 0 else c[k])

            hod = h[0]; lod = l[0]; last_fire = -999
            for i in range(1, len(rb)):
                hod = max(hod, h[i]); lod = min(lod, l[i])
                if rsi[i] is None or i - last_fire < cooldown:
                    continue
                if not (win_start <= ets[i].time() <= win_end):
                    continue
                cp = c[i]; atr = _atr_at(h, l, c, i, 14)
                if atr <= 0 or day_open <= 0:
                    continue
                end = min(i + maxhold, len(rb) - 1)
                dvw = (cp - vwap[i]) / vwap[i] * 100.0

                if side in ('up', 'both'):
                    push = (hod - day_open) / day_open * 100.0
                    dist_hod = (hod - cp) / cp * 100.0
                    if push >= push_min and dist_hod <= 0.5 and rsi[i] >= rsi_up and dvw >= 1.0:
                        entry = cp; stop = hod + atr * 0.25; tgt = max(vwap[i], day_open)
                        risk = stop - entry; reward = entry - tgt
                        if risk > 0 and reward > 0:
                            rr = reward / risk; r = None
                            for j in range(i + 1, end + 1):
                                if h[j] >= stop:
                                    r = (entry - stop) / risk; break
                                if l[j] <= tgt:
                                    r = (entry - tgt) / risk; break
                            if r is None:
                                r = (entry - c[end]) / risk
                            ev['first_move_up'].append((round(r, 3), rr)); last_fire = i
                            continue

                if side in ('down', 'both'):
                    flush = (day_open - lod) / day_open * 100.0
                    dist_lod = (cp - lod) / cp * 100.0
                    if flush >= push_min and dist_lod <= 0.5 and rsi[i] <= rsi_dn and dvw <= -1.0:
                        entry = cp; stop = lod - atr * 0.25; tgt = min(vwap[i], day_open)
                        risk = entry - stop; reward = tgt - entry
                        if risk > 0 and reward > 0:
                            rr = reward / risk; r = None
                            for j in range(i + 1, end + 1):
                                if l[j] <= stop:
                                    r = (stop - entry) / risk; break
                                if h[j] >= tgt:
                                    r = (tgt - entry) / risk; break
                            if r is None:
                                r = (c[end] - entry) / risk
                            ev['first_move_down'].append((round(r, 3), rr)); last_fire = i

    print("=== TZ / SESSION SANITY ===")
    if rth_ct:
        print(f"  sessions={n_sessions}  RTH bars/session median={int(median(rth_ct))} "
              f"(expect ~78 for 5-min). If shifted, re-run --tz et.\n")
    else:
        print("  no RTH bars — wrong time field/tz; try --tz et.\n")

    for st in ('first_move_up', 'first_move_down'):
        rows = ev[st]
        print('=' * 84)
        print(f"[{st}]  ({'SHORT fade' if st.endswith('up') else 'LONG fade'})  events={len(rows)}")
        _report('ALL', [r for r, _ in rows], [rr for _, rr in rows], cap)
        print('=' * 84)
    print("\n=== READING ===")
    print("• winsorAvg/medR > 0 -> the fade is +EV (keep/tune). Negative -> suppress.")
    print("• Probes: --side up ; --side down ; --winend 10:30 ; --push 2.0 ; --rsi-up 72/--rsi-dn 28.\n")


if __name__ == '__main__':
    main()
