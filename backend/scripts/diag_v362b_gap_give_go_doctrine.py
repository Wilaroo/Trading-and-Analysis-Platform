#!/usr/bin/env python3
# v362b — GAP GIVE & GO **DOCTRINE-FAITHFUL** intraday REPLAY (READ-ONLY, 1-min bars).
#
# Models the SMB cheat-sheet structure (NOT the loose live code):
#   1. Gap UP session (gap_pct = (day_open - prev_close)/prev_close*100 >= gap_min, default 1.0).
#   2. The "GIVE": a quick drop from the open that holds ABOVE prior_close (support proxy) and
#      does NOT close more than `give_max_fill`% of the gap (default 50% -> over-extension invalid).
#   3. A 3-7 min MINI-CONSOLIDATION on declining volume: a window of W in [cons_min..cons_max]
#      1-min bars whose band (max_high-min_low)/price <= cons_band_max% (default 0.6) AND whose
#      avg volume <= vol_decline * avg volume of the give bars (default 0.7) AND whose low holds
#      above prior_close. Consolidation band must be <= 50% of the opening-give range.
#   4. ENTRY: aggressive break of the consolidation range -> buy-stop at cons_high (+0.01).
#      Trigger must occur within the opening-drive window (default by --winend 09:45 ET).
#   5. STOP: .02 below the consolidation low.
#   6. EXIT (Move2Move): a DOUBLE-BAR-BREAK lower (two consecutive bars each closing below the
#      previous bar's low) closes the trade; else maxhold. R = (exit-entry)/(entry-stop).
#
# Levers (validated on big_dog v361): --min-stop-pct(%) --min-price($).
# Flags: --days --barsize(default '1 min') --universe --maxhold(bars) --cooldown(min)
#        --gap(%) --give-max-fill(%) --cons-min --cons-max --cons-band-max(%) --vol-decline
#        --winstart/--winend(ET, default 09:30-09:45) --tz auto|utc|et --winsor(R)

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


def _report(label, rs, rrs, cap):
    if not rs:
        print(f'  {label:<22} n=0'); return
    w = sum(1 for r in rs if r > 0)
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f'  {label:<22} n={len(rs):<5} win={100.0*w/len(rs):>3.0f}%  winsorAvg={mean(wr):+.3f}  '
          f'medR={median(rs):+.3f}  totW={sum(wr):+.1f}  avgRR={mean(rrs) if rrs else 0:.2f}')


def main():
    days = _arg('--days', 180, int)
    barsize = _argstr('--barsize', '1 min')
    uni_cap = _arg('--universe', 300, int)
    maxhold = _arg('--maxhold', 20, int)
    cooldown = _arg('--cooldown', 5, int)
    gap_min = _arg('--gap', 1.0, float)
    give_max_fill = _arg('--give-max-fill', 50.0, float)
    cons_min = _arg('--cons-min', 3, int)
    cons_max = _arg('--cons-max', 7, int)
    cons_band_max = _arg('--cons-band-max', 0.6, float)
    vol_decline = _arg('--vol-decline', 0.7, float)
    min_stop_pct = _arg('--min-stop-pct', 0.0, float)
    min_price = _arg('--min-price', 0.0, float)
    target_rmult = _arg('--target-rmult', 0.0, float)  # 0 = double-bar-break exit; >0 = fixed N*risk target
    win_start = _hhmm(_argstr('--winstart', '09:30'), time(9, 30))
    win_end = _hhmm(_argstr('--winend', '09:45'), time(9, 45))
    tz_assume = _argstr('--tz', 'auto')
    cap = _arg('--winsor', 3.0, float)

    db = _load_db()
    start_et = (datetime.now(timezone.utc) - timedelta(days=days)).astimezone(_ET)
    uni = Counter()
    for a in db.live_alerts.find({}, {'_id': 0, 'symbol': 1}):
        if a.get('symbol'):
            uni[a['symbol']] += 1
    syms = [s for s, _ in uni.most_common(uni_cap)]

    print(f"\n=== v362b GAP GIVE&GO DOCTRINE replay — {days}d bar='{barsize}' "
          f"win={win_start.strftime('%H:%M')}-{win_end.strftime('%H:%M')}ET gap>={gap_min:g}% "
          f"giveFill<={give_max_fill:g}% cons={cons_min}-{cons_max}bar band<={cons_band_max:g}% "
          f"volDecl<={vol_decline:g} minStop>={min_stop_pct:g}% minPx>=${min_price:g} "
          f"exit={'rmult='+str(target_rmult) if target_rmult>0 else 'double-bar-break'} "
          f"hold={maxhold}b tz={tz_assume} winsor=±{cap:g}R ===\n")
    print(f"universe: {len(syms)} symbols\n")

    ev = []
    n_sessions = 0; rth_ct = []; n_gap = 0; n_cons = 0; n_trig = 0
    barsizes_seen = Counter()

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

        for _d in sdates:
            sb = sessions[_d]
            rb = [(et, b) for et, b in sb if RTH_OPEN <= et.time() < RTH_CLOSE]
            this_last_close = rb[-1][1]['close'] if rb else (sb[-1][1]['close'] if sb else None)
            if len(rb) < 20:
                prev_close = this_last_close; continue
            n_sessions += 1; rth_ct.append(len(rb))
            pc = prev_close
            prev_close = this_last_close
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
            n_gap += 1
            open_high = h[0]
            last_fire_idx = -999

            # scan opening-drive window for a consolidation -> range-break
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
                # try widest->narrowest consolidation window ending at i-1
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
                    band_pct = band / cp * 100.0
                    if band_pct > cons_band_max:
                        continue
                    # give: the consolidation sits BELOW the opening high (a pullback happened)
                    if cons_high >= open_high:
                        continue
                    # give holds above prior_close support
                    if cons_low <= pc:
                        continue
                    # give did not fill > give_max_fill% of the gap (over-extension guard)
                    give_low = min(l[1:a + 1]) if a >= 1 else cons_low
                    gap_filled = (day_open - give_low) / (day_open - pc) * 100.0 if day_open > pc else 0.0
                    if gap_filled > give_max_fill:
                        continue
                    # declining volume vs the give bars
                    give_v = [x for x in v[1:a + 1] if x > 0]
                    cons_v = [x for x in cw_v if x > 0]
                    if give_v and cons_v and (mean(cons_v) > vol_decline * mean(give_v)):
                        continue
                    chosen = (cons_high, cons_low, band)
                    break
                if not chosen:
                    continue
                n_cons += 1
                cons_high, cons_low, band = chosen
                trigger = cons_high + 0.01
                if h[i] < trigger:  # range break must print on this bar
                    continue
                stop = cons_low - 0.02
                entry = trigger
                if entry <= stop:
                    continue
                if min_stop_pct > 0 and (entry - stop) / entry * 100.0 < min_stop_pct:
                    continue
                n_trig += 1; last_fire_idx = i
                risk = entry - stop
                end = min(i + maxhold, len(rb) - 1)
                r = None
                if target_rmult > 0:
                    # SHIPPABLE detector-only exit: fixed target = entry + N*risk (or stop, or maxhold)
                    tgt = entry + target_rmult * risk
                    for j in range(i + 1, end + 1):
                        if l[j] <= stop:
                            r = (stop - entry) / risk; break
                        if h[j] >= tgt:
                            r = target_rmult; break
                    if r is None:
                        r = (c[end] - entry) / risk
                    rr = target_rmult
                else:
                    # doctrine exit: double-bar-break lower (two consecutive bars each closing below prior bar low)
                    for j in range(i + 1, end + 1):
                        if l[j] <= stop:
                            r = (stop - entry) / risk; break
                        if j >= i + 2 and c[j] < l[j - 1] and c[j - 1] < l[j - 2]:
                            r = (c[j] - entry) / risk; break
                    if r is None:
                        r = (c[end] - entry) / risk
                    rr = (h[end] - entry) / risk if (h[end] - entry) > 0 else 0.0
                ev.append((round(r, 3), rr))

    print("=== SANITY ===")
    if rth_ct:
        print(f"  sessions={n_sessions}  RTH bars/session median={int(median(rth_ct))} "
              f"(expect ~390 for 1-min). If far off, try --tz et or check --barsize.")
    else:
        print("  no RTH bars found — check --barsize / --tz et.")
    print(f"  gap-up>={gap_min:g}% sessions={n_gap}  valid-consolidations={n_cons}  range-break entries={n_trig}\n")

    print('=' * 84)
    print(f"[gap_give_go DOCTRINE]  (1-min give->consolidation->range-break, double-bar-break exit)  events={len(ev)}")
    _report('ALL', [r for r, _ in ev], [rr for _, rr in ev], cap)
    print('=' * 84)
    print("\n=== READING ===")
    print("• winsorAvg/medR > 0 -> doctrine edge is real -> REWRITE the code to this structure (like v355 ORB).")
    print("• If still <=0 after probes -> suppress. Probes: --gap 2 ; --cons-band-max 0.4 (tighter) ;")
    print("  --winend 10:00 (more sample) ; --min-stop-pct 1.0 --min-price 10 ; --vol-decline 0.6.")
    print("• If 'no RTH bars' or median far from ~390: 1-min history may be absent — run with --barsize '5 mins'")
    print("  (coarser; consolidation/range-break fidelity drops) or backfill 1-min for the universe.\n")


if __name__ == '__main__':
    main()
