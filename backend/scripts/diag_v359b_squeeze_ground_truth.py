#!/usr/bin/env python3
# v359b — SQUEEZE ground-truth from actual bot_trades (READ-ONLY).
#
# The v359 replay verdict for `squeeze` is fill-model-sensitive (immediate fill = -0.475 R,
# trigger fill = +0.195 R). The live order is a MARKET order (autonomous fills at avg_cost;
# manual confirm re-prices entry to live market). So neither sim model is faithful — the only
# clean tie-breaker is REALIZED outcomes from closed bot_trades.
#
# Reports realized R (= realized_pnl / risk_dollars, risk = |entry-stop|*shares), win rate,
# total R and net P&L for `squeeze` and `daily_squeeze`, split by direction. Also dumps status
# counts and a few sample closed trades. NOTHING is written.
#
# Usage:  .venv/bin/python backend/scripts/diag_v359b_squeeze_ground_truth.py [--days 0]
#   --days N  : only trades created within last N days (0 = all history, default)

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
          f'medR={median(rs):+.3f}  winsorAvg(±5)={mean(wr):+.3f}  totR={sum(rs):+.1f}')


def main():
    days = _arg('--days', 0, int)
    db = _load_db()
    q = {'setup_type': {'$in': ['squeeze', 'daily_squeeze']}}
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        q['created_at'] = {'$gte': cutoff}

    rows = list(db.bot_trades.find(q, {'_id': 0}))
    print(f"\n=== v359b SQUEEZE ground-truth — bot_trades  (days={'all' if days == 0 else days}) ===")
    print(f"matched trades: {len(rows)}\n")
    if not rows:
        print("No squeeze/daily_squeeze trades found in bot_trades. "
              "(Either never auto-fired, or different setup_type label.)")
        # show what setup_types DO exist for orientation
        labels = Counter(t.get('setup_type') for t in db.bot_trades.find({}, {'_id': 0, 'setup_type': 1}))
        print("\nAll setup_type labels in bot_trades (top 30):")
        for k, c in labels.most_common(30):
            print(f"  {str(k):<28} {c}")
        return

    status_ct = Counter(t.get('status') for t in rows)
    print("status counts:", dict(status_ct))

    closed = [t for t in rows if str(t.get('status', '')).lower() in
              ('closed', 'exited', 'stopped', 'target', 'closed_win', 'closed_loss')
              or t.get('exit_price') is not None or _f(t.get('realized_pnl'))]

    def r_of(t):
        entry = _f(t.get('entry_price')); stop = _f(t.get('stop_price'))
        sh = _f(t.get('shares')) or _f(t.get('original_shares'))
        pnl = _f(t.get('realized_pnl'))
        if entry is None or stop is None or not sh:
            return None
        risk = abs(entry - stop) * sh
        if risk <= 0 or pnl is None:
            return None
        return pnl / risk

    by_setup = defaultdict(list)
    by_setup_dir = defaultdict(list)
    pnl_by_setup = defaultdict(float)
    for t in closed:
        s = t.get('setup_type')
        d = str(t.get('direction', '')).lower().replace('tradedirection.', '')
        r = r_of(t)
        by_setup[s].append(r)
        by_setup_dir[(s, 'long' if 'long' in d or 'buy' in d else 'short')].append(r)
        pnl_by_setup[s] += _f(t.get('net_pnl')) or _f(t.get('realized_pnl')) or 0.0

    print(f"\nclosed/with-pnl trades: {len(closed)}")
    print('=' * 84)
    for s in ('squeeze', 'daily_squeeze'):
        print(f"[{s}]  net P&L = ${pnl_by_setup[s]:+,.2f}")
        _report('ALL', by_setup.get(s, []))
        _report('LONG', by_setup_dir.get((s, 'long'), []))
        _report('SHORT', by_setup_dir.get((s, 'short'), []))
        print('-' * 84)
    print('=' * 84)

    # a few sample closed trades for eyeballing
    print("\nsample closed trades (up to 8):")
    for t in closed[:8]:
        print(f"  {t.get('symbol'):<6} {str(t.get('direction')):<18} {t.get('setup_type'):<14} "
              f"entry={t.get('entry_price')} stop={t.get('stop_price')} exit={t.get('exit_price')} "
              f"pnl={t.get('realized_pnl')} status={t.get('status')} reason={t.get('close_reason')}")
    print("\n=== READING ===")
    print("• This is GROUND TRUTH (real fills). If squeeze avgR/totR < 0 -> rewrite/suppress;")
    print("  if LONG +EV but SHORT -EV -> long-only (like daily_squeeze v358).")
    print("• Small n -> verdict is low-confidence; lean on the v359 sim + structural read.\n")


if __name__ == '__main__':
    main()
