#!/usr/bin/env python3
# v357 — FASHIONABLY LATE (intraday momentum scalp) REPLAY (READ-ONLY).
#
# SMB doctrine (from the_fashionably_late_scalp_cheat_sheet):
#   LONG : an UP-sloping 9-EMA crosses a FLAT-to-DOWN-sloping VWAP. Enter at the cross.
#          measured move = (cross_price - LOD).  target = cross + measured_move.
#          hard stop = 1/3 of the (VWAP -> LOD) distance below VWAP -> clean ~3:1 RR.
#   SHORT: inverted (down-sloping 9-EMA crosses flat-to-UP-sloping VWAP; HOD instead of LOD).
#   ideal times: 10:00-10:45 and 10:46-13:30 ET.  stats: 60% win, 3:1 RR.
#
# This script REPLAYS the cross signal on intraday bars and scores realized R under:
#   (1) DOCTRINE exits  : measured-move 3:1 (stop = 1/3 VWAP->LOD)
#   (2) LIVE-style exits : current _check_fashionably_late geometry (stop = vwap - atr*0.33,
#                          target = vwap + (vwap - LOD))
# so we can decide: preserve-as-is / rewrite-to-doctrine / suppress.  NOTHING is written.
#
# Usage (run from repo root on DGX):
#   .venv/bin/python backend/scripts/diag_v357_fashionably_late_replay.py \
#       --days 120 --barsize "5 mins" --ema 9 --universe 300 \
#       --maxhold 24 --cooldown 3 --side both --timewin on --vwapslope on --tz auto
#
# Flags:
#   --side  long|short|both     which direction(s) to replay (default both)
#   --timewin on|off            restrict entries to 10:00-13:30 ET (default on)
#   --vwapslope on|off          require flat-to-down VWAP for long / flat-to-up for short (default on)
#   --tz auto|utc|et            how to interpret NAIVE bar timestamps (default auto=treat naive as UTC)
#   --minmove <pct>             skip degenerate moves where (cross->LOD) < pct% of price (default 0.05)

import sys
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from statistics import median, mean

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
    _UTC = ZoneInfo("UTC")
except Exception:
    _ET = timezone(timedelta(hours=-5))  # crude fallback (no DST)
    _UTC = timezone.utc

RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
WIN_START = time(10, 0)
WIN_END = time(13, 30)


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


def _to_et(raw, assume):
    """Return a tz-aware ET datetime from a stored bar time (datetime / epoch / ISO str)."""
    dt = None
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:      # ms epoch
            ts /= 1000.0
        dt = datetime.fromtimestamp(ts, tz=_UTC)
    elif isinstance(raw, str):
        s = raw.strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y%m%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                try:
                    dt = datetime.strptime(s[:19], fmt)
                    break
                except Exception:
                    continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        if assume == 'et':
            return dt.replace(tzinfo=_ET)
        return dt.replace(tzinfo=_UTC).astimezone(_ET)  # auto/utc
    return dt.astimezone(_ET)


def _ema_series(closes, n):
    if not closes:
        return []
    a = 2.0 / (n + 1.0)
    out = [closes[0]]
    for c in closes[1:]:
        out.append(a * c + (1 - a) * out[-1])
    return out


def _atr_at(highs, lows, closes, i, n=14):
    trs = []
    for k in range(max(1, i - n + 1), i + 1):
        trs.append(max(highs[k] - lows[k], abs(highs[k] - closes[k - 1]), abs(lows[k] - closes[k - 1])))
    return (sum(trs) / len(trs)) if trs else 0.0


def _sim_long(highs, lows, closes, i, end, entry, stop, target):
    risk = entry - stop
    if risk <= 0:
        return None, 0.0
    rr = (target - entry) / risk
    for j in range(i + 1, end + 1):
        if lows[j] <= stop:
            return (stop - entry) / risk, rr
        if highs[j] >= target:
            return (target - entry) / risk, rr
    return (closes[end] - entry) / risk, rr


def _sim_short(highs, lows, closes, i, end, entry, stop, target):
    risk = stop - entry
    if risk <= 0:
        return None, 0.0
    rr = (entry - target) / risk
    for j in range(i + 1, end + 1):
        if highs[j] >= stop:
            return (entry - stop) / risk, rr
        if lows[j] <= target:
            return (entry - target) / risk, rr
    return (entry - closes[end]) / risk, rr


def _report(label, rows, key, cap):
    rs = [r[key] for r in rows if r.get(key) is not None]
    rrs = [r[key + '_rr'] for r in rows if r.get(key) is not None]
    if not rs:
        print(f'  {label:<28} n=0')
        return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f'  {label:<28} n={len(rs):<5} win={100.0*w/len(rs):>3.0f}%  '
          f'winsorAvg={mean(wr):+.3f}  medR={median(rs):+.3f}  totW={sum(wr):+.1f}  '
          f'avgRR={mean(rrs):.2f}')


def main():
    days = _arg('--days', 120, int)
    barsize = _argstr('--barsize', '5 mins')
    ema_n = _arg('--ema', 9, int)
    uni_cap = _arg('--universe', 300, int)
    maxhold = _arg('--maxhold', 24, int)
    cooldown = _arg('--cooldown', 3, int)
    side = _argstr('--side', 'both')
    timewin = _argstr('--timewin', 'on') == 'on'
    vwapslope = _argstr('--vwapslope', 'on') == 'on'
    tz_assume = _argstr('--tz', 'auto')
    minmove = _arg('--minmove', 0.05, float)
    warmup = _arg('--warmup', 3, int)
    cap = _arg('--winsor', 3.0, float)

    db = _load_db()
    start_et = (datetime.now(timezone.utc) - timedelta(days=days)).astimezone(_ET)

    from collections import Counter
    universe = Counter()
    for a in db.live_alerts.find({}, {'_id': 0, 'symbol': 1}):
        if a.get('symbol'):
            universe[a['symbol']] += 1
    syms = [s for s, _ in universe.most_common(uni_cap)]

    print(f"\n=== v357 FASHIONABLY LATE replay — {days}d  bar='{barsize}'  ema={ema_n}  "
          f"side={side}  timewin={'10:00-13:30' if timewin else 'off'}  "
          f"vwapslope={'on' if vwapslope else 'off'}  maxhold={maxhold}bars  "
          f"cooldown={cooldown}bars  tz={tz_assume}  winsor=±{cap:g}R ===")
    print(f'universe: {len(syms)} symbols\n')

    events = []
    n_sessions = 0
    tz_hours = Counter()
    rth_per_session = []
    sanity_done = False

    for sym in syms:
        cur = db.ib_historical_data.find(
            {'symbol': sym, 'bar_size': barsize},
            {'_id': 0, 'date': 1, 'timestamp': 1, 'open': 1, 'high': 1,
             'low': 1, 'close': 1, 'volume': 1})
        raw = []
        for b in cur:
            if not (b.get('close') and b.get('high') and b.get('low')):
                continue
            et = _to_et(b.get('timestamp') if b.get('timestamp') is not None else b.get('date'), tz_assume)
            if et is None or et < start_et:
                continue
            raw.append((et, b))
        if len(raw) < ema_n + 10:
            continue
        raw.sort(key=lambda x: x[0])

        # group into sessions by ET calendar date
        sessions = defaultdict(list)
        for et, b in raw:
            sessions[et.date()].append((et, b))

        for sess_date, sb in sessions.items():
            # RTH only (regular session) for VWAP / signal integrity
            rb = [(et, b) for et, b in sb if RTH_OPEN <= et.time() < RTH_CLOSE]
            if len(rb) < ema_n + 5:
                continue
            n_sessions += 1
            rth_per_session.append(len(rb))
            for et, _ in rb:
                tz_hours[et.hour] += 1

            ets = [et for et, _ in rb]
            o = [b['open'] for _, b in rb]
            h = [b['high'] for _, b in rb]
            l = [b['low'] for _, b in rb]
            c = [b['close'] for _, b in rb]
            v = [(b.get('volume') or 0) for _, b in rb]

            ema = _ema_series(c, ema_n)
            # cumulative session VWAP (typical price)
            vwap = []
            cum_pv = 0.0
            cum_v = 0.0
            for k in range(len(rb)):
                tp = (h[k] + l[k] + c[k]) / 3.0
                vol = v[k] if v[k] > 0 else 1.0
                cum_pv += tp * vol
                cum_v += vol
                vwap.append(cum_pv / cum_v if cum_v > 0 else c[k])

            last_entry = -999
            lod = l[0]
            hod = h[0]
            for i in range(1, len(rb)):
                lod = min(lod, l[i])
                hod = max(hod, h[i])
                if i < warmup or i - last_entry < cooldown:
                    continue
                in_win = WIN_START <= ets[i].time() <= WIN_END
                if timewin and not in_win:
                    continue
                entry = c[i]
                cross_price = vwap[i]
                atr = _atr_at(h, l, c, i, 14)
                end = min(i + maxhold, len(rb) - 1)

                # ---- LONG : up-sloping 9-EMA crosses above flat/down VWAP
                if side in ('long', 'both'):
                    cross_up = ema[i] > vwap[i] and ema[i - 1] <= vwap[i - 1]
                    ema_up = ema[i] > ema[i - 1]
                    vwap_ok = vwap[i] <= vwap[i - 1] if vwapslope else True
                    move = cross_price - lod
                    if (cross_up and ema_up and vwap_ok and move > 0
                            and move / entry * 100.0 >= minmove):
                        stop_d = cross_price - move / 3.0
                        tgt_d = cross_price + move
                        r_doc, rr_doc = _sim_long(h, l, c, i, end, entry, stop_d, tgt_d)
                        stop_l = vwap[i] - atr * 0.33
                        tgt_l = vwap[i] + move
                        r_liv, rr_liv = _sim_long(h, l, c, i, end, entry, stop_l, tgt_l)
                        events.append({'side': 'long', 'in_win': in_win, 'vwap_ok': vwap_ok,
                                       'doc': r_doc, 'doc_rr': rr_doc,
                                       'live': r_liv, 'live_rr': rr_liv})
                        last_entry = i
                        continue

                # ---- SHORT : down-sloping 9-EMA crosses below flat/up VWAP
                if side in ('short', 'both'):
                    cross_dn = ema[i] < vwap[i] and ema[i - 1] >= vwap[i - 1]
                    ema_dn = ema[i] < ema[i - 1]
                    vwap_ok = vwap[i] >= vwap[i - 1] if vwapslope else True
                    move = hod - cross_price
                    if (cross_dn and ema_dn and vwap_ok and move > 0
                            and move / entry * 100.0 >= minmove):
                        stop_d = cross_price + move / 3.0
                        tgt_d = cross_price - move
                        r_doc, rr_doc = _sim_short(h, l, c, i, end, entry, stop_d, tgt_d)
                        stop_l = vwap[i] + atr * 0.33
                        tgt_l = vwap[i] - move
                        r_liv, rr_liv = _sim_short(h, l, c, i, end, entry, stop_l, tgt_l)
                        events.append({'side': 'short', 'in_win': in_win, 'vwap_ok': vwap_ok,
                                       'doc': r_doc, 'doc_rr': rr_doc,
                                       'live': r_liv, 'live_rr': rr_liv})
                        last_entry = i

    # ---- TZ sanity (so the operator can trust RTH bucketing) ----
    print('=== TZ / SESSION SANITY ===')
    if rth_per_session:
        print(f'  sessions={n_sessions}  RTH bars/session: '
              f'min={min(rth_per_session)} median={int(median(rth_per_session))} max={max(rth_per_session)}  '
              f'(expect ~78 for 5-min, ~26 for 15-min, ~13 for 30-min)')
        top = sorted(tz_hours.items())
        print('  ET-hour histogram (RTH bars): ' + ' '.join(f'{hh:02d}h:{cnt}' for hh, cnt in top))
        print('  -> all bars should fall in 09..15h ET. If they look shifted, re-run with --tz et (or utc).')
    else:
        print('  no RTH bars parsed — wrong time field or tz. Re-run with --tz et and confirm bar_size.')
    print()

    print(f'FASHIONABLY LATE events={len(events)}\n')
    print('=' * 92)
    print('DOCTRINE exits (measured-move 3:1, stop=1/3 VWAP->LOD):')
    _report('ALL', events, 'doc', cap)
    _report('LONG', [e for e in events if e['side'] == 'long'], 'doc', cap)
    _report('SHORT', [e for e in events if e['side'] == 'short'], 'doc', cap)
    _report('in 10:00-13:30 window', [e for e in events if e['in_win']], 'doc', cap)
    _report('outside window', [e for e in events if not e['in_win']], 'doc', cap)
    print('-' * 92)
    print('LIVE-style exits (stop=vwap-atr*0.33, target=vwap+(vwap-LOD)) — current _check_fashionably_late:')
    _report('ALL', events, 'live', cap)
    _report('LONG', [e for e in events if e['side'] == 'long'], 'live', cap)
    _report('SHORT', [e for e in events if e['side'] == 'short'], 'live', cap)
    print('=' * 92)
    print('\n=== READING ===')
    print('• Cheat sheet claims 60% win @ 3:1 RR. Compare DOCTRINE win% / winsorAvg vs LIVE-style.')
    print('• If DOCTRINE winsorAvg/medR > LIVE and > 0  -> rewrite live geometry to measured-move 3:1.')
    print('• If both negative everywhere               -> suppress (return None), like vwap_bounce (v354).')
    print('• If LIVE already >= DOCTRINE and +EV       -> preserve as-is, like daily_breakout (v356).')
    print('• Compare in-window vs outside-window to confirm the 10:00-13:30 ET gate adds edge.')
    print('• Re-run probes: --side long ; --side short ; --vwapslope off ; --timewin off ; --barsize "1 min".\n')


if __name__ == '__main__':
    main()
