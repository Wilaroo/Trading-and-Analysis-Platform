#!/usr/bin/env python3
# v361 — BIG DOG (tight-consolidation HOD breakout, LONG) intraday REPLAY (READ-ONLY).
#
# Mirrors the live _check_big_dog long-continuation on intraday bars:
#   GATES (at signal bar i):
#     daily_range_pct = (HOD-LOD)/LOD*100 < range_max (default 2.0)   [tight session]
#     above_vwap  : cp > VWAP[i]
#     above_ema9  : cp > EMA9[i]
#     dist_from_hod = (HOD-cp)/cp*100 < 1.0%                          [coiled near HOD]
#     (live also rvol>=1.2 — a DAILY 20-day vol ratio, NOT reconstructable per intraday bar;
#      NOT applied here, so this replay is a SUPERSET of live fires — slightly lower quality.)
#   GEOMETRY (faithful to live):
#     trigger = HOD          (buy-stop breakout — the live trigger_price)
#     raw_stop = EMA9 - 0.02 ; stop = min(raw_stop, cp - 0.5*ATR)     [ATR-floored, anchored to cp]
#     target  = HOD + 1.5*ATR
#   EXECUTION (faithful): entry only fills if a later bar's high >= trigger within --trigwin bars
#     (live minutes_to_trigger=15, expires 1h). risk = trigger - stop ; R vs that risk.
#
# Two cuts so the breakout-chase penalty is visible:
#   [LIVE  trigger@HOD]  entry=HOD on breakout (what actually trades)
#   [MKT @ signal]       entry=cp at the signal bar, stop=min(EMA9-0.02, cp-0.5*ATR),
#                        target=cp+1.5*ATR — the coil edge WITHOUT chasing the HOD break.
#
# Flags: --days --barsize --universe --maxhold(bars) --cooldown(bars) --trigwin(bars)
#        --range-max(%) --disthod(%) --winstart/--winend (ET, default 09:30-16:00)
#        --min-stop-pct(%) [reject signals whose (cp-stop)/cp < X — kills tight-stop blow-throughs]
#        --min-price($)    [reject low-priced/illiquid names]
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


def _ema_series(closes, span=9):
    out = [None] * len(closes)
    if not closes:
        return out
    a = 2.0 / (span + 1.0)
    e = closes[0]; out[0] = e
    for i in range(1, len(closes)):
        e = a * closes[i] + (1 - a) * e
        out[i] = e
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
    trigwin = _arg('--trigwin', 12, int)
    range_max = _arg('--range-max', 2.0, float)
    disthod = _arg('--disthod', 1.0, float)
    min_stop_pct = _arg('--min-stop-pct', 0.0, float)
    min_price = _arg('--min-price', 0.0, float)
    win_start = _hhmm(_argstr('--winstart', '09:30'), time(9, 30))
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

    print(f"\n=== v361 BIG DOG replay — {days}d bar='{barsize}' "
          f"win={win_start.strftime('%H:%M')}-{win_end.strftime('%H:%M')}ET "
          f"range<{range_max:g}% distHOD<{disthod:g}% trigwin={trigwin}b hold={maxhold}b "
          f"cooldown={cooldown}b minStop>={min_stop_pct:g}% minPx>=${min_price:g} "
          f"tz={tz_assume} winsor=±{cap:g}R ===")
    print("NOTE: live daily-rvol>=1.2 gate NOT applied (superset of live fires)\n")
    print(f"universe: {len(syms)} symbols\n")

    ev = {'live_trigger': [], 'mkt_signal': []}
    n_sessions = 0; rth_ct = []; n_signals = 0; n_triggered = 0

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
            ema9 = _ema_series(c, 9)
            vwap = []; cum_pv = 0.0; cum_v = 0.0
            for k in range(len(rb)):
                tp = (h[k] + l[k] + c[k]) / 3.0
                vol = v[k] if v[k] > 0 else 1.0
                cum_pv += tp * vol; cum_v += vol
                vwap.append(cum_pv / cum_v if cum_v > 0 else c[k])

            hod = h[0]; lod = l[0]; last_fire = -999
            for i in range(1, len(rb)):
                hod = max(hod, h[i]); lod = min(lod, l[i])
                if i - last_fire < cooldown:
                    continue
                if not (win_start <= ets[i].time() <= win_end):
                    continue
                cp = c[i]; atr = _atr_at(h, l, c, i, 14)
                if atr <= 0 or lod <= 0 or ema9[i] is None:
                    continue
                rng = (hod - lod) / lod * 100.0
                dist_hod = (hod - cp) / cp * 100.0
                if not (rng < range_max and cp > vwap[i] and cp > ema9[i]
                        and 0 <= dist_hod < disthod and cp >= min_price):
                    continue
                raw_stop = ema9[i] - 0.02
                stop = min(raw_stop, cp - 0.5 * atr)
                if min_stop_pct > 0 and cp > 0 and (cp - stop) / cp * 100.0 < min_stop_pct:
                    continue  # tight-stop blow-through risk — reject
                n_signals += 1; last_fire = i
                end = min(i + maxhold, len(rb) - 1)

                # --- MKT @ signal cut: enter at cp now, ATR geometry off cp ---
                m_risk = cp - stop; m_tgt = cp + 1.5 * atr; m_reward = m_tgt - cp
                if m_risk > 0 and m_reward > 0:
                    rr = m_reward / m_risk; r = None
                    for j in range(i + 1, end + 1):
                        if l[j] <= stop:
                            r = (stop - cp) / m_risk; break
                        if h[j] >= m_tgt:
                            r = (m_tgt - cp) / m_risk; break
                    if r is None:
                        r = (c[end] - cp) / m_risk
                    ev['mkt_signal'].append((round(r, 3), rr))

                # --- LIVE trigger@HOD cut: buy-stop at HOD, must break out within trigwin ---
                trigger = hod
                tw_end = min(i + trigwin, len(rb) - 1)
                entry_bar = None
                for j in range(i + 1, tw_end + 1):
                    if h[j] >= trigger:
                        entry_bar = j; break
                if entry_bar is None:
                    continue  # breakout never came — no fill (faithful)
                n_triggered += 1
                entry = trigger
                t_risk = entry - stop; t_tgt = hod + 1.5 * atr; t_reward = t_tgt - entry
                if t_risk <= 0 or t_reward <= 0:
                    continue
                hold_end = min(entry_bar + maxhold, len(rb) - 1)
                rr = t_reward / t_risk; r = None
                for j in range(entry_bar, hold_end + 1):
                    if l[j] <= stop:
                        r = (stop - entry) / t_risk; break
                    if h[j] >= t_tgt:
                        r = (t_tgt - entry) / t_risk; break
                if r is None:
                    r = (c[hold_end] - entry) / t_risk
                ev['live_trigger'].append((round(r, 3), rr))

    print("=== TZ / SESSION SANITY ===")
    if rth_ct:
        print(f"  sessions={n_sessions}  RTH bars/session median={int(median(rth_ct))} "
              f"(expect ~78 for 5-min). If shifted, re-run --tz et.")
    else:
        print("  no RTH bars — wrong time field/tz; try --tz et.")
    trig_rate = (100.0 * n_triggered / n_signals) if n_signals else 0.0
    print(f"  signals={n_signals}  breakout-triggered={n_triggered} ({trig_rate:.0f}%)\n")

    print('=' * 84)
    print(f"[big_dog — LIVE trigger@HOD]  (LONG breakout — what actually trades)  events={len(ev['live_trigger'])}")
    _report('ALL', [r for r, _ in ev['live_trigger']], [rr for _, rr in ev['live_trigger']], cap)
    print('=' * 84)
    print(f"[big_dog — MKT @ signal]      (coil edge w/o chasing HOD)             events={len(ev['mkt_signal'])}")
    _report('ALL', [r for r, _ in ev['mkt_signal']], [rr for _, rr in ev['mkt_signal']], cap)
    print('=' * 84)
    print("\n=== READING ===")
    print("• LIVE trigger@HOD is the verdict driver (it's the real execution). winsorAvg/medR > 0")
    print("  -> +EV (keep/tune). Negative -> suppress (like vwap_bounce/squeeze/first_move).")
    print("• If MKT@signal is +EV but LIVE trigger@HOD is -EV -> the HOD breakout-chase is the")
    print("  bleed; a v359-style entry-anchor rewrite (enter at cp, geometry off entry) may rescue it.")
    print("• Probes: --range-max 1.5 (tighter coil) ; --disthod 0.5 ; --trigwin 6 ; --winend 11:00 ;")
    print("          --min-stop-pct 1.0 (kill blow-throughs) ; --min-price 10 (drop illiquid).\n")


if __name__ == '__main__':
    main()
