#!/usr/bin/env python3
# v365 — SCALED / MEASURED-MOVE EXIT-POLICY COMPARISON (READ-ONLY, 1-min bars).
#
# Purpose: before doing the (safety-adjacent) position-management work to support
# scaled measured-move exits, prove on data whether a scaled/Move2Move exit actually
# BEATS the shipped flat-2R target — apples-to-apples on the SAME entry set.
#
# It reconstructs entries EXACTLY like the shipped doctrine detectors:
#   • spencer_scalp  (v363): >=cons_len-min tight range in UPPER 1/3, vol-surge break, LONG.
#   • gap_give_go    (v362): gap-up give->3-7m declining-vol consolidation->range-break, LONG,
#                            opening-drive window only.
# Then runs each entry through a battery of exit policies and reports n/win%/winsorAvg/medR/EV.
#
# Exit policies compared (all LONG; both setups ship LONG-only):
#   flat_2R        : shipped baseline — fixed target = entry + 2R, else stop, else maxhold close.
#   scaled_123     : 1/3 @1R, 1/3 @2R, 1/3 @3R; BE after 1R, stop->1R after 2R (v363 model).
#   dbb_trail_100  : pure Move2Move double-bar-break trail, 100% (the v362b model).
#   m2m_half_1R    : SMB "half/half" — 1/2 @1R, trail remaining 1/2 on double-bar-break (BE after 1R).
#   m2m_half_mm    : SMB "half/half" — 1/2 at the MEASURED MOVE (entry + consolidation band height),
#                    trail remaining 1/2 on double-bar-break (BE after first partial).
#
# Flags: --setup spencer|gap_give_go|both  --days  --barsize('1 min')  --universe
#        --maxhold(bars)  --cooldown(min)  --min-price($)  --tz auto|utc|et  --winsor(R)
#        spencer:  --cons-len --cons-frac --third --vol-surge --winstart/--winend
#        gap_give: --gap --give-max-fill --cons-min --cons-max --cons-band-max --vol-decline
#                  --gwinstart/--gwinend

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


# ── exit policies (LONG) — each returns blended realized R in units of initial risk ──
def ex_flat(h, l, c, i, end, E, S, rmult=2.0):
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


def ex_scaled_123(h, l, c, i, end, E, S):
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


def ex_dbb_trail(h, l, c, i, end, E, S):
    R = E - S
    if R <= 0:
        return None
    for j in range(i + 1, end + 1):
        if l[j] <= S:
            return (S - E) / R
        if j >= i + 2 and c[j] < l[j - 1] and c[j - 1] < l[j - 2]:
            return (c[j] - E) / R
    return (c[end] - E) / R


def ex_m2m_half(h, l, c, i, end, E, S, first_tgt):
    """1/2 off at first_tgt (price), trail remaining 1/2 on double-bar-break; BE after first partial."""
    R = E - S
    if R <= 0:
        return None
    realized = 0.0; pos = 1.0; took = False; stop = S
    for j in range(i + 1, end + 1):
        if l[j] <= stop:
            realized += pos * ((stop - E) / R); pos = 0.0; break
        if not took and h[j] >= first_tgt:
            leg = (first_tgt - E) / R
            realized += 0.5 * leg; pos = 0.5; took = True; stop = E  # move to breakeven
        if took and j >= i + 2 and c[j] < l[j - 1] and c[j - 1] < l[j - 2]:
            realized += pos * ((c[j] - E) / R); pos = 0.0; break
    if pos > 0:
        realized += pos * ((c[end] - E) / R)
    return realized


POLICIES = ["flat_2R", "scaled_123", "dbb_trail_100", "m2m_half_1R", "m2m_half_mm"]


def run_policies(h, l, c, i, end, E, S, band):
    R = E - S
    return {
        "flat_2R": ex_flat(h, l, c, i, end, E, S, 2.0),
        "scaled_123": ex_scaled_123(h, l, c, i, end, E, S),
        "dbb_trail_100": ex_dbb_trail(h, l, c, i, end, E, S),
        "m2m_half_1R": ex_m2m_half(h, l, c, i, end, E, S, E + R),
        "m2m_half_mm": ex_m2m_half(h, l, c, i, end, E, S, E + max(band, R * 0.5)),
    }


def _report(label, rs, cap):
    if not rs:
        print(f'  {label:<16} n=0'); return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f'  {label:<16} n={len(rs):<5} win={100.0*w/len(rs):>3.0f}%  winsorAvg={mean(wr):+.3f}  '
          f'medR={median(rs):+.3f}  totW={sum(wr):+.1f}')


def _load_sym_sessions(db, sym, barsize, start_et, tz_assume):
    rows = []
    for b in db.ib_historical_data.find(
            {'symbol': sym, 'bar_size': barsize},
            {'_id': 0, 'date': 1, 'timestamp': 1, 'open': 1, 'high': 1,
             'low': 1, 'close': 1, 'volume': 1}):
        if not (b.get('close') and b.get('high') and b.get('low') and b.get('open')):
            continue
        et = _to_et(b.get('timestamp') if b.get('timestamp') is not None else b.get('date'), tz_assume)
        if et is None or et < start_et:
            continue
        rows.append((et, b))
    if len(rows) < 30:
        return None
    rows.sort(key=lambda x: x[0])
    sessions = defaultdict(list)
    for et, b in rows:
        sessions[et.date()].append((et, b))
    return sessions


def gen_spencer(db, syms, args, start_et):
    """Yield LONG entries reconstructed exactly like v363 shipped detector."""
    cons_len = args['cons_len']; cons_frac = args['cons_frac']; third = args['third']
    vol_surge = args['vol_surge']; cooldown = args['cooldown']; maxhold = args['maxhold']
    min_price = args['min_price']; win_start = args['s_win_start']; win_end = args['s_win_end']
    barsize = args['barsize']; tz_assume = args['tz']
    n = 0
    for sym in syms:
        sessions = _load_sym_sessions(db, sym, barsize, start_et, tz_assume)
        if not sessions:
            continue
        for _d, sb in sessions.items():
            rb = [(et, b) for et, b in sb if RTH_OPEN <= et.time() < RTH_CLOSE]
            if len(rb) < cons_len + 5:
                continue
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
                wv = [v[k] for k in win if v[k] > 0]
                if wv and v[i] < vol_surge * (sum(wv) / len(wv)):
                    continue
                # LONG only: upper third + range-high break
                if wl >= lod + (1 - third) * dr and h[i] >= wh + 0.01:
                    E = round(wh + 0.01, 2); S = round(wl - 0.02, 2)
                    end = min(i + maxhold, len(rb) - 1)
                    if E > S:
                        n += 1; last_fire = i
                        yield (h, l, c, i, end, E, S, band)
    return


def gen_gap_give_go(db, syms, args, start_et):
    """Yield LONG entries reconstructed exactly like v362 shipped detector."""
    gap_min = args['gap']; give_max_fill = args['give_max_fill']
    cons_min = args['cons_min']; cons_max = args['cons_max']
    cons_band_max = args['cons_band_max']; vol_decline = args['vol_decline']
    cooldown = args['cooldown']; maxhold = args['g_maxhold']; min_price = args['min_price']
    win_start = args['g_win_start']; win_end = args['g_win_end']
    barsize = args['barsize']; tz_assume = args['tz']
    for sym in syms:
        sessions = _load_sym_sessions(db, sym, barsize, start_et, tz_assume)
        if not sessions:
            continue
        sdates = sorted(sessions.keys()); prev_close = None
        for _d in sdates:
            sb = sessions[_d]
            rb = [(et, b) for et, b in sb if RTH_OPEN <= et.time() < RTH_CLOSE]
            this_last_close = rb[-1][1]['close'] if rb else (sb[-1][1]['close'] if sb else None)
            if len(rb) < 20:
                prev_close = this_last_close; continue
            pc = prev_close; prev_close = this_last_close
            ets = [et for et, _ in rb]
            o = [b['open'] for _, b in rb]; h = [b['high'] for _, b in rb]
            l = [b['low'] for _, b in rb]; c = [b['close'] for _, b in rb]
            v = [(b.get('volume') or 0) for _, b in rb]
            day_open = o[0]
            if not (pc and pc > 0):
                continue
            gap_pct = (day_open - pc) / pc * 100.0
            if gap_pct < gap_min:
                continue
            open_high = h[0]; last_fire_idx = -999
            for i in range(cons_min, len(rb)):
                if not (win_start <= ets[i].time() <= win_end):
                    if ets[i].time() > win_end:
                        break
                    continue
                if i - last_fire_idx < cooldown:
                    continue
                cp = c[i]
                if cp < min_price:
                    continue
                chosen = None
                for w in range(cons_max, cons_min - 1, -1):
                    a = i - w
                    if a < 1:
                        continue
                    cw_h = h[a:i]; cw_l = l[a:i]; cw_v = v[a:i]
                    if not cw_h:
                        continue
                    cons_high = max(cw_h); cons_low = min(cw_l)
                    band = cons_high - cons_low
                    if cp <= 0 or band <= 0:
                        continue
                    if band / cp * 100.0 > cons_band_max:
                        continue
                    if cons_high >= open_high:
                        continue
                    if cons_low <= pc:
                        continue
                    give_low = min(l[1:a + 1]) if a >= 1 else cons_low
                    gap_filled = (day_open - give_low) / (day_open - pc) * 100.0 if day_open > pc else 0.0
                    if gap_filled > give_max_fill:
                        continue
                    give_v = [x for x in v[1:a + 1] if x > 0]
                    cons_v = [x for x in cw_v if x > 0]
                    if give_v and cons_v and (mean(cons_v) > vol_decline * mean(give_v)):
                        continue
                    chosen = (cons_high, cons_low, band); break
                if not chosen:
                    continue
                cons_high, cons_low, band = chosen
                trigger = cons_high + 0.01
                if h[i] < trigger:
                    continue
                stop = cons_low - 0.02; entry = trigger
                if entry <= stop:
                    continue
                last_fire_idx = i
                end = min(i + maxhold, len(rb) - 1)
                yield (h, l, c, i, end, round(entry, 2), round(stop, 2), band)
    return


def evaluate(name, gen, db, syms, args, start_et, cap):
    buckets = {p: [] for p in POLICIES}
    n_entries = 0
    for (h, l, c, i, end, E, S, band) in gen(db, syms, args, start_et):
        res = run_policies(h, l, c, i, end, E, S, band)
        if res["flat_2R"] is None:
            continue
        n_entries += 1
        for p in POLICIES:
            r = res[p]
            if r is not None:
                buckets[p].append(round(r, 3))
    print('=' * 84)
    print(f"[{name}]  entries={n_entries}  (LONG-only, same entry set across all policies)")
    print('-' * 84)
    base = mean([max(-cap, min(cap, r)) for r in buckets['flat_2R']]) if buckets['flat_2R'] else 0.0
    for p in POLICIES:
        _report(p, buckets[p], cap)
    # delta vs baseline
    print('-' * 84)
    print(f"  baseline = flat_2R winsorAvg = {base:+.3f}R")
    for p in POLICIES:
        if p == 'flat_2R' or not buckets[p]:
            continue
        m = mean([max(-cap, min(cap, r)) for r in buckets[p]])
        print(f"    {p:<16} Δ vs flat_2R = {m-base:+.3f}R   "
              f"{'>>> WINS' if m-base > 0.01 else ('~tie' if abs(m-base)<=0.01 else 'loses')}")
    print('=' * 84 + '\n')


def main():
    setup = _argstr('--setup', 'both')
    days = _arg('--days', 180, int)
    barsize = _argstr('--barsize', '1 min')
    uni_cap = _arg('--universe', 300, int)
    cap = _arg('--winsor', 3.0, float)
    tz_assume = _argstr('--tz', 'auto')

    args = {
        'barsize': barsize, 'tz': tz_assume, 'cooldown': _arg('--cooldown', 10, int),
        'min_price': _arg('--min-price', 0.0, float),
        # spencer
        'cons_len': _arg('--cons-len', 20, int), 'cons_frac': _arg('--cons-frac', 0.15, float),
        'third': _arg('--third', 0.333, float), 'vol_surge': _arg('--vol-surge', 1.3, float),
        'maxhold': _arg('--maxhold', 60, int),
        's_win_start': _hhmm(_argstr('--winstart', '09:59'), time(9, 59)),
        's_win_end': _hhmm(_argstr('--winend', '16:00'), time(16, 0)),
        # gap_give_go
        'gap': _arg('--gap', 1.0, float), 'give_max_fill': _arg('--give-max-fill', 50.0, float),
        'cons_min': _arg('--cons-min', 3, int), 'cons_max': _arg('--cons-max', 7, int),
        'cons_band_max': _arg('--cons-band-max', 0.6, float),
        'vol_decline': _arg('--vol-decline', 0.7, float),
        'g_maxhold': _arg('--gmaxhold', 20, int),
        'g_win_start': _hhmm(_argstr('--gwinstart', '09:30'), time(9, 30)),
        'g_win_end': _hhmm(_argstr('--gwinend', '09:45'), time(9, 45)),
    }

    db = _load_db()
    start_et = (datetime.now(timezone.utc) - timedelta(days=days)).astimezone(_ET)
    uni = Counter()
    for a in db.live_alerts.find({}, {'_id': 0, 'symbol': 1}):
        if a.get('symbol'):
            uni[a['symbol']] += 1
    syms = [s for s, _ in uni.most_common(uni_cap)]

    print(f"\n=== v365 SCALED-EXIT POLICY COMPARISON — {days}d bar='{barsize}' "
          f"universe={len(syms)} winsor=±{cap:g}R tz={tz_assume} ===")
    print("Policies: flat_2R(shipped) | scaled_123 | dbb_trail_100 | m2m_half_1R | m2m_half_mm")
    print("m2m_half = SMB 'half first leg / half second leg' (1/2 off, trail 1/2 on double-bar-break, BE)\n")

    if setup in ('both', 'spencer'):
        evaluate('spencer_scalp', gen_spencer, db, syms, args, start_et, cap)
    if setup in ('both', 'gap_give_go'):
        evaluate('gap_give_go', gen_gap_give_go, db, syms, args, start_et, cap)

    print("=== READING ===")
    print("• If a scaled/m2m policy beats flat_2R by a ROBUST margin (Δ>+0.03R, similar n) -> worth the")
    print("  position-management build for that setup. If flat_2R wins or ties -> KEEP flat_2R (no PM change).")
    print("• m2m_half_mm uses the consolidation-band height as the first measured move (true SMB M2M).")
    print("• Re-check robustness: --cons-frac 0.12 / --vol-surge 1.5 (spencer); --gap 2 --cons-band-max 0.4")
    print("  (gap_give_go); and --winsor 2 to confirm the edge isn't a fat-tail artifact.\n")


if __name__ == '__main__':
    main()
