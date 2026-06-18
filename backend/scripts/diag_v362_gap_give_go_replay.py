#!/usr/bin/env python3
# v362 — GAP GIVE & GO (morning gap-up pullback-to-VWAP continuation, LONG) intraday REPLAY (READ-ONLY).
#
# Mirrors the live _check_gap_give_go on intraday bars:
#   GATES (morning window, at signal bar i):
#     gap_pct = (day_open - prev_close)/prev_close*100 > gap_min (default 3.0)
#     holding_gap : cp > prev_close                       [gap not filled]
#     above_vwap  : cp > VWAP[i]
#     0 < dist_from_vwap = (cp-VWAP)/VWAP*100 < dvw_max (default 1.5)   [pulled back to VWAP]
#     (live also rvol>=2.0 — a DAILY 20-day vol ratio, NOT reconstructable per intraday bar;
#      NOT applied here, so this replay is a SUPERSET of live fires — slightly lower quality.)
#   GEOMETRY (faithful to live):
#     entry  = cp                        (market at signal — live trigger_price = current_price)
#     raw_stop = VWAP - 0.02 ; stop = min(raw_stop, cp - 0.5*ATR)      [ATR-floored, anchored to cp]
#     target = HOD (running session high at signal)
#   risk = cp - stop ; reward = HOD - cp ; R vs risk on a maxhold window.
#
# Slippage levers (validated decisive on big_dog v361):
#   --min-stop-pct(%) reject signals whose (cp-stop)/cp < X (tight-stop blow-throughs)
#   --min-price($)    reject low-priced/illiquid names
#
# Flags: --days --barsize --universe --maxhold(bars) --cooldown(bars) --gap(%) --dvw-max(%)
#        --min-stop-pct(%) --min-price($) --winstart/--winend (ET, default 09:30-11:00)
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


def _atr_at(h, l, c, i, n=14):
    trs = []
    for k in range(max(1, i - n + 1), i + 1):
        trs.append(max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])))
    return (sum(trs) / len(trs)) if trs else 0.0


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
    gap_min = _arg('--gap', 3.0, float)
    dvw_max = _arg('--dvw-max', 1.5, float)
    min_stop_pct = _arg('--min-stop-pct', 0.0, float)
    min_price = _arg('--min-price', 0.0, float)
    win_start = _hhmm(_argstr('--winstart', '09:30'), time(9, 30))
    win_end = _hhmm(_argstr('--winend', '11:00'), time(11, 0))
    tz_assume = _argstr('--tz', 'auto')
    cap = _arg('--winsor', 3.0, float)

    db = _load_db()
    start_et = (datetime.now(timezone.utc) - timedelta(days=days)).astimezone(_ET)
    uni = Counter()
    for a in db.live_alerts.find({}, {'_id': 0, 'symbol': 1}):
        if a.get('symbol'):
            uni[a['symbol']] += 1
    syms = [s for s, _ in uni.most_common(uni_cap)]

    print(f"\n=== v362 GAP GIVE&GO replay — {days}d bar='{barsize}' "
          f"win={win_start.strftime('%H:%M')}-{win_end.strftime('%H:%M')}ET "
          f"gap>{gap_min:g}% 0<distVWAP<{dvw_max:g}% hold={maxhold}b cooldown={cooldown}b "
          f"minStop>={min_stop_pct:g}% minPx>=${min_price:g} tz={tz_assume} winsor=±{cap:g}R ===")
    print("NOTE: live daily-rvol>=2.0 gate NOT applied (superset of live fires)\n")
    print(f"universe: {len(syms)} symbols\n")

    ev = []
    n_sessions = 0; rth_ct = []; n_gap_sessions = 0

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
        sdates = sorted(sessions.keys())
        prev_close = None

        for di, _d in enumerate(sdates):
            sb = sessions[_d]
            rb = [(et, b) for et, b in sb if RTH_OPEN <= et.time() < RTH_CLOSE]
            # update prev_close from this session's last RTH close AFTER processing
            this_last_close = rb[-1][1]['close'] if rb else (sb[-1][1]['close'] if sb else None)
            if len(rb) < 20:
                prev_close = this_last_close
                continue
            n_sessions += 1; rth_ct.append(len(rb))
            ets = [et for et, _ in rb]
            o = [b['open'] for _, b in rb]; h = [b['high'] for _, b in rb]
            l = [b['low'] for _, b in rb]; c = [b['close'] for _, b in rb]
            v = [(b.get('volume') or 0) for _, b in rb]
            day_open = o[0]
            vwap = []; cum_pv = 0.0; cum_v = 0.0
            for k in range(len(rb)):
                tp = (h[k] + l[k] + c[k]) / 3.0
                vol = v[k] if v[k] > 0 else 1.0
                cum_pv += tp * vol; cum_v += vol
                vwap.append(cum_pv / cum_v if cum_v > 0 else c[k])

            gap_pct = ((day_open - prev_close) / prev_close * 100.0) if (prev_close and prev_close > 0) else None
            prev_close_for_session = prev_close
            prev_close = this_last_close  # set for next session before any continue

            if gap_pct is None or gap_pct <= gap_min:
                continue
            n_gap_sessions += 1

            hod = h[0]; last_fire = -999
            for i in range(1, len(rb)):
                hod = max(hod, h[i])
                if i - last_fire < cooldown:
                    continue
                if not (win_start <= ets[i].time() <= win_end):
                    continue
                cp = c[i]; atr = _atr_at(h, l, c, i, 14)
                if atr <= 0 or vwap[i] <= 0:
                    continue
                dvw = (cp - vwap[i]) / vwap[i] * 100.0
                holding_gap = cp > prev_close_for_session
                if not (holding_gap and cp > vwap[i] and 0 < dvw < dvw_max and cp >= min_price):
                    continue
                raw_stop = vwap[i] - 0.02
                stop = min(raw_stop, cp - 0.5 * atr)
                if min_stop_pct > 0 and cp > 0 and (cp - stop) / cp * 100.0 < min_stop_pct:
                    continue
                target = hod
                risk = cp - stop; reward = target - cp
                if risk <= 0 or reward <= 0:
                    continue
                last_fire = i
                end = min(i + maxhold, len(rb) - 1)
                rr = reward / risk; r = None
                for j in range(i + 1, end + 1):
                    if l[j] <= stop:
                        r = (stop - cp) / risk; break
                    if h[j] >= target:
                        r = (target - cp) / risk; break
                if r is None:
                    r = (c[end] - cp) / risk
                ev.append((round(r, 3), rr))

    print("=== TZ / SESSION SANITY ===")
    if rth_ct:
        print(f"  sessions={n_sessions}  gap-up>{gap_min:g}% sessions={n_gap_sessions}  "
              f"RTH bars/session median={int(median(rth_ct))} (expect ~78 for 5-min). If shifted, try --tz et.\n")
    else:
        print("  no RTH bars — wrong time field/tz; try --tz et.\n")

    print('=' * 84)
    print(f"[gap_give_go]  (LONG morning gap-up VWAP-pullback continuation)  events={len(ev)}")
    _report('ALL', [r for r, _ in ev], [rr for _, rr in ev], cap)
    print('=' * 84)
    print("\n=== READING ===")
    print("• winsorAvg/medR > 0 -> +EV (keep/tune). Negative -> suppress (vwap_bounce/squeeze/first_move).")
    print("• If baseline is breakeven/negative, try the slippage levers that rescued big_dog:")
    print("  --min-stop-pct 1.0 --min-price 10 ; also --gap 4 (bigger gaps) ; --dvw-max 1.0 (tighter to VWAP).\n")


if __name__ == '__main__':
    main()
