#!/usr/bin/env python3
"""
v19.34.248b — LEARNING-LOOP AUDIT *VERIFICATION* (READ-ONLY).

Double-checks the v248 findings with CORRECT field names + schema dumps, so we
separate real gaps from audit artifacts before changing any code.

Corrections vs v248:
  • shadow_decisions uses was_executed / outcome_tracked / actual_outcome /
    would_have_pnl / would_have_r  (v248 queried executed/outcome/would_pnl → all None).
  • calibration persists to calibration_history / calibration_config
    (NOT calibration_log → v248 false "never runs").
  • setup_grade_records uses computed_at / trading_date (NOT date).
  • regime_performance is an AGGREGATE (per strategy×regime); per-trade is regime_trade_log.
  • alert_outcomes has a 2nd feeder: apply_close_pnl → _record_alert_outcome_bestEffort
    (v124), called from EOD + reconciler paths. Only the OCA-external sweep bypasses it.

Run on DGX:
    .venv/bin/python backend/scripts/diag_learning_loop_audit_v19_34_248b.py --days 14
"""
import argparse
import os
import sys
from datetime import datetime, timezone, timedelta

try:
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]
    db.client.admin.command("ping")
    print(f"[db] connected: {mongo_url} / {db_name}")
except Exception as e:  # pragma: no cover
    print(f"[FATAL] cannot connect: {e}")
    sys.exit(1)

NOW = datetime.now(timezone.utc)
ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=14)
args = ap.parse_args()
cutoff_iso = (NOW - timedelta(days=args.days)).isoformat()


def _dt(ts):
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts if ts < 1e12 else ts/1000, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(ts, str):
        try:
            d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            # date-only "YYYY-MM-DD"
            try:
                return datetime.strptime(ts[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                return None
    return None


def _age(ts):
    d = _dt(ts)
    if not d:
        return "—"
    s = (NOW - d).total_seconds()
    if s < 90:
        return f"{int(s)}s"
    if s < 5400:
        return f"{int(s/60)}m"
    if s < 172800:
        return f"{int(s/3600)}h"
    return f"{int(s/86400)}d"


def cnt(c, q=None):
    try:
        return db[c].count_documents(q or {})
    except Exception:
        return -1


def hdr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


# ── 1. SCHEMA DUMP ─────────────────────────────────────────────────
hdr("1. SCHEMA DUMP (real field names — 1 sample doc each)")
for c in ["bot_trades", "trade_outcomes", "alert_outcomes", "strategy_stats",
          "shadow_decisions", "regime_performance", "regime_trade_log",
          "setup_grade_records", "calibration_history", "calibration_config",
          "gate_calibration", "tuning_recommendations", "ev_tracking",
          "weekly_intelligence_reports", "confidence_gate_log", "learning_stats"]:
    n = cnt(c)
    try:
        d = db[c].find_one(sort=[("_id", -1)]) if n > 0 else None
    except Exception:
        d = None
    keys = ", ".join(sorted(k for k in d.keys() if k != "_id")[:24]) if d else "(empty)"
    print(f"  {c:<26} n={n:<7} keys: {keys[:140]}")


# ── 2. COVERAGE (robust + keying-artifact guard) ───────────────────
hdr(f"2. CLOSE-PATH COVERAGE (closed bot_trades last {args.days}d)")
closed = list(db["bot_trades"].find(
    {"status": {"$in": ["closed", "CLOSED"]}, "closed_at": {"$gte": cutoff_iso}},
    {"_id": 0, "trade_id": 1, "id": 1, "symbol": 1, "closed_at": 1,
     "close_reason": 1, "setup_type": 1},
))
def tid(t):
    return t.get("trade_id") or t.get("id")

to_ids, to_by_symtime = set(), []
for d in db["trade_outcomes"].find({"created_at": {"$gte": cutoff_iso}},
                                   {"_id": 0, "bot_trade_id": 1, "symbol": 1, "exit_time": 1}):
    to_ids.add(d.get("bot_trade_id"))
    to_by_symtime.append((d.get("symbol"), _dt(d.get("exit_time"))))
ao_ids = set()
for d in db["alert_outcomes"].find({"closed_at": {"$gte": cutoff_iso}},
                                   {"_id": 0, "trade_id": 1, "bot_trade_id": 1, "alert_id": 1}):
    ao_ids.update({d.get("trade_id"), d.get("bot_trade_id"), d.get("alert_id")})

miss_to = [t for t in closed if tid(t) not in to_ids]
miss_ao = [t for t in closed if tid(t) not in ao_ids]
n = len(closed)
print(f"  closed={n}   in trade_outcomes={n-len(miss_to)} ({100*(n-len(miss_to))//max(n,1)}%)   "
      f"in alert_outcomes={n-len(miss_ao)} ({100*(n-len(miss_ao))//max(n,1)}%)")

def breakdown(rows, label):
    from collections import Counter
    cc = Counter((t.get("close_reason") or "?") for t in rows)
    print(f"  {label} missing by close_reason:")
    for r, c in cc.most_common(12):
        print(f"      {r:<42} {c}")
breakdown(miss_to, "trade_outcomes")
breakdown(miss_ao, "alert_outcomes")

# keying-artifact guard: do "missing" trades actually exist in the sink by symbol+time?
artifact = 0
for t in miss_to[:40]:
    ct = _dt(t.get("closed_at"))
    if ct and any(s == t.get("symbol") and et and abs((et-ct).total_seconds()) < 600
                  for s, et in to_by_symtime):
        artifact += 1
print(f"  keying-artifact check: {artifact}/{min(40,len(miss_to))} 'missing' trades DO have a "
      f"symbol+time match in trade_outcomes (→ ID-keying mismatch, not a true leak)")


# ── 3. SHADOW (correct fields) ─────────────────────────────────────
hdr("3. SHADOW vs REAL (correct fields: was_executed/outcome_tracked/actual_outcome)")
sd = list(db["shadow_decisions"].find({"timestamp": {"$gte": cutoff_iso}},
          {"_id": 0, "was_executed": 1, "outcome_tracked": 1, "actual_outcome": 1,
           "would_have_pnl": 1, "would_have_r": 1, "combined_recommendation": 1}))
if not sd:  # try created_at
    sd = list(db["shadow_decisions"].find({}, {"_id": 0, "was_executed": 1,
              "outcome_tracked": 1, "actual_outcome": 1, "would_have_pnl": 1,
              "would_have_r": 1, "combined_recommendation": 1}).sort("_id", -1).limit(5000))
ne = len(sd)
ex = [d for d in sd if d.get("was_executed")]
tracked = [d for d in sd if d.get("outcome_tracked")]
print(f"  sample={ne}  was_executed={len(ex)}  outcome_tracked={len(tracked)} "
      f"({100*len(tracked)//max(ne,1)}%)")
def wr(rows):
    w = sum(1 for r in rows if str(r.get("actual_outcome", "")).lower() in ("won", "win"))
    dec = sum(1 for r in rows if str(r.get("actual_outcome", "")).lower() in ("won", "win", "lost", "loss"))
    return f"{100*w/dec:.0f}%" if dec else "—"
print(f"  executed actual_outcome win%={wr(ex)}   tracked-overall win%={wr(tracked)}")
from collections import Counter
print(f"  recommendation mix: {dict(Counter(d.get('combined_recommendation','?') for d in sd).most_common(6))}")


# ── 4. EV DIVERGENCE DECOMPOSITION ─────────────────────────────────
hdr("4. EV DIVERGENCE DECOMP (trade_outcomes realized vs strategy_stats SMB)")
def base(s):
    return (s or "").lower().replace("_long", "").replace("_short", "")
recomp = {}
for d in db["trade_outcomes"].find({}, {"_id": 0, "setup_type": 1, "outcome": 1, "actual_r": 1}):
    recomp.setdefault(base(d.get("setup_type")), []).append(d)
ss = {d.get("setup_type"): d for d in db["strategy_stats"].find({}, {"_id": 0})}
print(f"  {'setup':<22}{'TO_n':>5}{'TO_wr':>6}{'TO_ev':>7} | {'SS_trig':>7}{'SS_won':>6}"
      f"{'SS_nr':>5}{'awR':>6}{'alR':>6}{'SS_ev':>7}")
for bs in sorted(recomp, key=lambda k: -len(recomp[k]))[:18]:
    rows = recomp[bs]
    wins = sum(1 for r in rows if r.get("outcome") == "won")
    dec = sum(1 for r in rows if r.get("outcome") in ("won", "lost"))
    wr_to = wins/dec if dec else 0
    rs = [float(r.get("actual_r") or 0) for r in rows]
    ev_to = sum(rs)/len(rs) if rs else 0
    s = ss.get(bs, {})
    nr = len(s.get("r_outcomes", []) or [])
    def g(k):
        v = s.get(k)
        return f"{v:.2f}" if isinstance(v, (int, float)) else "—"
    print(f"  {bs:<22}{len(rows):>5}{wr_to:>6.2f}{ev_to:>7.2f} | "
          f"{str(s.get('alerts_triggered','—')):>7}{str(s.get('alerts_won','—')):>6}"
          f"{nr:>5}{g('avg_win_r'):>6}{g('avg_loss_r'):>6}{g('expected_value_r'):>7}")
print("  TO_ev = mean realized actual_r ; SS_ev = SMB (win_rate*awR-(1-wr)*alR), wr from "
      "ALL-TIME counters, awR/alR from last-100 r_outcomes → mismatch is the divergence.")


# ── 5. SIBLING-SINK LIVENESS (correct collections/fields) ──────────
hdr("5. SINK LIVENESS (correct collections + timestamp fields)")
for c, tf in [("calibration_history", "timestamp"), ("calibration_config", "last_updated"),
              ("gate_calibration", "timestamp"), ("tuning_recommendations", "created_at"),
              ("setup_grade_records", "computed_at"), ("regime_performance", "last_updated"),
              ("regime_trade_log", "timestamp"), ("weekly_intelligence_reports", "generated_at"),
              ("ev_tracking", "last_updated")]:
    n = cnt(c)
    last = None
    if n > 0:
        try:
            d = db[c].find_one({}, sort=[(tf, -1)])
            last = d.get(tf) if d else None
            if last is None:  # field guess wrong — show newest by _id
                d2 = db[c].find_one(sort=[("_id", -1)])
                last = next((d2.get(k) for k in ("timestamp", "created_at", "computed_at",
                            "last_updated", "generated_at", "trading_date", "date") if d2 and d2.get(k)), None)
        except Exception:
            pass
    print(f"  {c:<28} n={n:<7} latest={_age(last)}  (ts={tf})")


# ── 6. CONNECTORS: which close_reasons feed which sink ─────────────
hdr("6. CONNECTOR MAP — close_reason coverage per sink")
cr_closed = Counter((t.get("close_reason") or "?") for t in closed)
# build reason set for trades present in each sink
present_to = {tid(t) for t in closed if tid(t) in to_ids}
present_ao = {tid(t) for t in closed if tid(t) in ao_ids}
print(f"  {'close_reason':<42}{'closed':>7}{'→TO':>5}{'→AO':>5}")
for r, c in cr_closed.most_common(14):
    in_to = sum(1 for t in closed if (t.get("close_reason") or "?") == r and tid(t) in present_to)
    in_ao = sum(1 for t in closed if (t.get("close_reason") or "?") == r and tid(t) in present_ao)
    print(f"  {r:<42}{c:>7}{in_to:>5}{in_ao:>5}")

print("\nDone. (read-only)\n")
