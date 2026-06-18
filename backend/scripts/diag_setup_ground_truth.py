#!/usr/bin/env python3
# diag_setup_ground_truth.py — GENERIC realized-EV from closed bot_trades (READ-ONLY).
#
# Reusable ground-truth tool for the setup-alignment queue. Reports realized R
# (= realized_pnl / risk_dollars, risk = |entry-stop|*shares), win rate, total R and net P&L
# per setup, split by direction. Excludes synthetic/test symbols by default. NOTHING is written.
#
# Usage:
#   .venv/bin/python backend/scripts/diag_setup_ground_truth.py --setups first_move_up,first_move_down
#   .venv/bin/python backend/scripts/diag_setup_ground_truth.py --setups big_dog,gap_give_go,spencer_scalp --days 365
#   --include-synthetic   keep TEST_/E2E_/SIM_/DEMO_ and underscore symbols
#   --days N              only trades created within last N days (0 = all, default)

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


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


def _report(label, rows):
    rs = [r for r in rows if r is not None]
    if not rs:
        print(f'  {label:<26} n=0')
        return
    w = sum(1 for r in rs if r > 0)
    cap = 5.0
    wr = [max(-cap, min(cap, r)) for r in rs]
    print(f'  {label:<26} n={len(rs):<4} win={100.0*w/len(rs):>3.0f}%  avgR={mean(rs):+.3f}  '
          f'medR={median(rs):+.3f}  winsorAvg(±5)={mean(wr):+.3f}  totR={sum(wr):+.1f}')


def main():
    setups = [s.strip() for s in _arg('--setups', '', str).split(',') if s.strip()]
    if not setups:
        print("ERROR: pass --setups a,b,c"); return
    days = _arg('--days', 0, int)
    include_synth = '--include-synthetic' in sys.argv

    db = _load_db()
    q = {'setup_type': {'$in': setups}}
    if days > 0:
        q['created_at'] = {'$gte': (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()}
    rows = list(db.bot_trades.find(q, {'_id': 0}))

    if not include_synth:
        def _real(sym):
            s = str(sym or '')
            if '_' in s:
                return False
            return not any(s.upper().startswith(p) for p in ('TEST', 'E2E', 'SIM', 'DEMO', 'FAKE'))
        before = len(rows)
        rows = [t for t in rows if _real(t.get('symbol'))]
        synth_note = f"(excluded {before - len(rows)} synthetic/test trades)"
    else:
        synth_note = "(synthetic included)"

    print(f"\n=== setup ground-truth — bot_trades  setups={setups}  days={'all' if days == 0 else days} ===")
    print(f"{synth_note}  matched: {len(rows)}\n")
    if not rows:
        labels = Counter(t.get('setup_type') for t in db.bot_trades.find({}, {'_id': 0, 'setup_type': 1}))
        print("No trades for those setups. All setup_type labels in bot_trades (top 40):")
        for k, c in labels.most_common(40):
            print(f"  {str(k):<28} {c}")
        return

    print("status counts:", dict(Counter(t.get('status') for t in rows)))
    closed = [t for t in rows if t.get('exit_price') is not None or _f(t.get('realized_pnl'))]

    def r_of(t):
        entry = _f(t.get('entry_price')); stop = _f(t.get('stop_price'))
        sh = _f(t.get('shares')) or _f(t.get('original_shares'))
        pnl = _f(t.get('realized_pnl'))
        if entry is None or stop is None or not sh or pnl is None:
            return None
        risk = abs(entry - stop) * sh
        return pnl / risk if risk > 0 else None

    by_setup = defaultdict(list)
    by_setup_dir = defaultdict(list)
    pnl_by_setup = defaultdict(float)
    for t in closed:
        s = t.get('setup_type')
        d = str(t.get('direction', '')).lower().replace('tradedirection.', '')
        dd = 'long' if ('long' in d or 'buy' in d) else 'short'
        by_setup[s].append(r_of(t))
        by_setup_dir[(s, dd)].append(r_of(t))
        pnl_by_setup[s] += _f(t.get('net_pnl')) or _f(t.get('realized_pnl')) or 0.0

    print(f"closed/with-pnl: {len(closed)}")
    print('=' * 84)
    for s in setups:
        print(f"[{s}]  net P&L = ${pnl_by_setup[s]:+,.2f}")
        _report('ALL', by_setup.get(s, []))
        _report('LONG', by_setup_dir.get((s, 'long'), []))
        _report('SHORT', by_setup_dir.get((s, 'short'), []))
        print('-' * 84)
    print('=' * 84)
    print("\nsample closed (up to 10):")
    for t in closed[:10]:
        print(f"  {str(t.get('symbol')):<7} {str(t.get('direction')):<16} {str(t.get('setup_type')):<16} "
              f"entry={t.get('entry_price')} stop={t.get('stop_price')} exit={t.get('exit_price')} "
              f"pnl={t.get('realized_pnl')} status={t.get('status')} reason={t.get('close_reason')}")
    print("\n=== READING ===")
    print("• GROUND TRUTH (real fills). avgR/totR<0 -> rewrite/suppress; LONG +EV & SHORT -EV -> long-only.")
    print("• Small n -> low confidence; back with an intraday replay before patching.\n")


if __name__ == '__main__':
    main()
