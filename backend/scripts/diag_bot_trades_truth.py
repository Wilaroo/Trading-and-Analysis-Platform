#!/usr/bin/env python3
"""
diag_bot_trades_truth.py  (READ-ONLY)
=====================================
GROUND TRUTH on what the bot ACTUALLY did — using bot_trades + alert_outcomes,
NOT confidence_gate_log (which logs every shadow/candidate the gate scored, not
real fills). Outcome values are 'won'/'lost'/'scratch' and PnL is realized_pnl.

Reports:
  A. bot_trades status distribution (open / closed / paper / pending / ...).
  B. CLOSED trades: counts (all / 7d / 30d), realized win-rate, total & avg PnL,
     paper vs live split if distinguishable.
  C. alert_outcomes: outcome distribution, avg R-multiple, total PnL,
     and per-setup breakdown (win-rate, avg R, total $) — the real edge per setup.
  D. A few sample closed docs so we can see the true field names.

Writes NOTHING.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_bot_trades_truth.py
"""
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc)
iso_7d = (now - timedelta(days=7)).isoformat()
iso_30d = (now - timedelta(days=30)).isoformat()


def fnum(v):
    try:
        return float(v)
    except Exception:
        return None


def first_field(doc, names):
    for n in names:
        if n in doc and doc[n] is not None:
            return doc[n]
    return None


bt = db.bot_trades
print("=" * 80)
print(f"A. bot_trades — {bt.count_documents({}):,} total")
print("=" * 80)
status_c = Counter()
mode_c = Counter()
for r in bt.find({}, {"status": 1, "mode": 1, "is_paper": 1, "account_type": 1, "_id": 0}):
    status_c[str(r.get("status"))] += 1
    m = r.get("mode") or r.get("account_type") or ("paper" if r.get("is_paper") else None)
    if m is not None:
        mode_c[str(m)] += 1
print("status distribution:")
for s, c in status_c.most_common():
    print(f"  {s:<14} {c:>7}")
if mode_c:
    print("mode/account distribution:")
    for m, c in mode_c.most_common():
        print(f"  {m:<14} {c:>7}")

print("\n" + "=" * 80)
print("B. CLOSED trades — realized performance (source of truth)")
print("=" * 80)
TIME_FIELDS = ("closed_at", "exit_time", "closed_time", "updated_at", "created_at")


def closed_stats(extra_match=None):
    q = {"status": "closed"}
    if extra_match:
        q.update(extra_match)
    n = won = lost = scratch = 0
    total_pnl = 0.0
    rs = []
    for r in bt.find(q, {"realized_pnl": 1, "pnl": 1, "r_multiple": 1, "_id": 0}):
        n += 1
        pnl = fnum(first_field(r, ["realized_pnl", "pnl"]))
        if pnl is None:
            pnl = 0.0
        total_pnl += pnl
        if pnl > 0:
            won += 1
        elif pnl < 0:
            lost += 1
        else:
            scratch += 1
        rm = fnum(r.get("r_multiple"))
        if rm is not None:
            rs.append(rm)
    return n, won, lost, scratch, total_pnl, rs


n, won, lost, scratch, total_pnl, rs = closed_stats()
print(f"closed (all): {n:,}")
if n:
    decided = won + lost
    wr = won / decided * 100 if decided else 0
    print(f"  won={won}  lost={lost}  scratch={scratch}  win-rate={wr:.1f}%")
    print(f"  total realized PnL = ${total_pnl:,.2f}   avg/trade = ${total_pnl/n:,.2f}")
    if rs:
        import statistics
        print(f"  R-multiple: mean={statistics.mean(rs):+.3f}  "
              f"median={statistics.median(rs):+.3f}  n={len(rs)}")
        print(f"  → mean R {'+' if statistics.mean(rs)>=0 else ''}{statistics.mean(rs):.3f} = "
              f"{'PROFITABLE' if statistics.mean(rs)>0 else 'BLEEDING'} per unit risk")

# recent windows
for label, iso in [("7d", iso_7d), ("30d", iso_30d)]:
    for tf in TIME_FIELDS:
        c = bt.count_documents({"status": "closed", tf: {"$gte": iso}})
        if c:
            print(f"  closed in last {label} (by {tf}): {c:,}")
            break

print("\n" + "=" * 80)
print("C. alert_outcomes — per-setup realized edge")
print("=" * 80)
ao = db.alert_outcomes
ao_total = ao.count_documents({})
print(f"alert_outcomes total: {ao_total:,}")
if ao_total:
    oc = Counter()
    per_setup = defaultdict(lambda: {"n": 0, "won": 0, "lost": 0, "pnl": 0.0, "r": []})
    for r in ao.find({}, {"outcome": 1, "realized_pnl": 1, "pnl": 1, "r_multiple": 1,
                          "setup_type": 1, "setup": 1, "strategy": 1, "_id": 0}):
        o = str(r.get("outcome", "?")).lower()
        oc[o] += 1
        st = str(first_field(r, ["setup_type", "setup", "strategy"]) or "?")
        d = per_setup[st]
        d["n"] += 1
        if o == "won":
            d["won"] += 1
        elif o == "lost":
            d["lost"] += 1
        pnl = fnum(first_field(r, ["realized_pnl", "pnl"]))
        if pnl is not None:
            d["pnl"] += pnl
        rm = fnum(r.get("r_multiple"))
        if rm is not None:
            d["r"].append(rm)
    print(f"outcome distribution: {dict(oc)}")
    print(f"\n{'setup':<26}{'n':>6}{'win%':>7}{'avgR':>8}{'totalPnL':>12}")
    print("-" * 60)
    import statistics
    for st, d in sorted(per_setup.items(), key=lambda kv: -kv[1]["n"])[:25]:
        dec = d["won"] + d["lost"]
        wr = d["won"] / dec * 100 if dec else 0
        avgr = statistics.mean(d["r"]) if d["r"] else 0
        flag = "🟢" if (avgr > 0.05 and d["pnl"] > 0) else ("🔴" if d["pnl"] < 0 else "⚪")
        print(f"{flag}{st:<25}{d['n']:>6}{wr:>6.1f}%{avgr:>+8.3f}{d['pnl']:>12.0f}")

print("\n" + "=" * 80)
print("D. Sample CLOSED bot_trades docs (field names)")
print("=" * 80)
for r in bt.find({"status": "closed"}).sort([("_id", -1)]).limit(3):
    r.pop("_id", None)
    keys = sorted(r.keys())
    print(f"\n  keys: {keys}")
    for k in ("symbol", "setup_type", "direction", "status", "realized_pnl", "pnl",
              "r_multiple", "fill_price", "stop_price", "exit_price", "closed_at",
              "p_win", "mode", "is_paper"):
        if k in r:
            print(f"    {k} = {r[k]}")

print("\nDONE — paste this whole block back.")
