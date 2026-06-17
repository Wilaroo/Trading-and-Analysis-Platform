#!/usr/bin/env python3
"""
v337 — `breakdown` FIND-NO-TRADE TRIAGE (READ-ONLY)

v331b (sanitized) confirmed the BIGGEST anomaly: `breakdown` fires ~2470x in 30d
but produces 0 GENUINE bot-own trades. This diag finds WHERE breakdown alerts die
along the pipeline (alert → confidence gate → trade_drops → bot_trades), so we can
tell a real BLOCK BUG from correct suppression.

It buckets, for setup_type LIKE 'breakdown%':
  • alert fire counts (live_alerts / alerts / live_scanner_alerts)
  • confidence_gate_log decisions by recommendation (GO/REDUCE/SKIP) + top SKIP reasons
  • trade_drops by gate (which gate killed it between AI-gate and bot_trades.insert)
  • rejection_events by reason_code
  • any bot_trades rows (status mix, entered_by, genuine vs artifact)

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v337_breakdown_triage.py --days 30
"""
import sys
from collections import Counter
from datetime import datetime, timezone


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _g(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _iso_since(days):
    return (datetime.now(timezone.utc).timestamp() - days * 86400)


def _dt_ts(v):
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except Exception:
        return None


def _match(setup):
    return str(setup or "").lower().startswith("breakdown")


def _scan(db, coll, setup_keys, reason_keys, since_ts, label):
    if coll not in db.list_collection_names():
        print(f"  [{coll}] absent"); return
    total = 0
    reasons = Counter()
    rec_ct = Counter()
    for d in db[coll].find({}, {"_id": 0}):
        su = _g(d, *setup_keys)
        if not _match(su):
            continue
        ts = _dt_ts(_g(d, "created_at", "ts", "timestamp", "decided_at", "time"))
        if ts is not None and ts < since_ts:
            continue
        total += 1
        rec = _g(d, "recommendation", "decision", "action", "verdict")
        if rec:
            rec_ct[str(rec).upper()] += 1
        for rk in reason_keys:
            rv = d.get(rk)
            if rv:
                reasons[str(rv)[:40]] += 1
                break
    print(f"\n[{coll}] {label}: {total} breakdown rows in window")
    if rec_ct:
        print("  by recommendation:", dict(rec_ct))
    for r, c in reasons.most_common(10):
        print(f"    {c:>5}  {r}")


def main():
    days = _arg("--days", 30, int)
    sys.path.insert(0, "backend")
    since = _iso_since(days)
    db = _load_db()

    print(f"\n=== v337 BREAKDOWN FIND-NO-TRADE TRIAGE — last {days}d ===")

    # 1) alert fire counts
    for coll in ("live_alerts", "alerts", "live_scanner_alerts", "predictive_alerts"):
        _scan(db, coll, ("setup_type", "setup", "strategy"), (), since, "alerts")

    # 2) confidence gate decisions
    _scan(db, "confidence_gate_log", ("setup_type", "setup", "strategy"),
          ("reason", "skip_reason", "reasoning", "block_reason"), since, "gate decisions")

    # 3) trade drops (which gate killed it)
    _scan(db, "trade_drops", ("setup_type", "setup"),
          ("gate", "reason_code", "first_killing_gate", "reason"), since, "trade drops")

    # 4) rejection events
    _scan(db, "rejection_events", ("setup_type", "setup"),
          ("reason_code", "reason"), since, "rejections")

    # 5) bot_trades — did ANY breakdown row reach a trade?
    try:
        sys.path.insert(0, "backend")
        from services.trade_outcome_hygiene import classify_close, is_adopted_entry
        have_hygiene = True
    except Exception:
        have_hygiene = False
    status_ct = Counter(); eb_ct = Counter(); genuine = 0; total_bt = 0
    for t in db.bot_trades.find({}, {"_id": 0}):
        if not _match(_g(t, "setup_type", "setup")):
            continue
        ts = _dt_ts(_g(t, "created_at", "entry_time", "opened_at"))
        if ts is not None and ts < since:
            continue
        total_bt += 1
        status_ct[str(_g(t, "status") or "?")] += 1
        eb_ct[str(_g(t, "entered_by", "source") or "?")[:24]] += 1
        if have_hygiene and str(_g(t, "status") or "") == "closed":
            try:
                ok, _ = classify_close(
                    close_reason=str(_g(t, "close_reason", "exit_reason") or ""),
                    entered_by=str(_g(t, "entered_by") or ""),
                    entry_price=None, exit_price=None,
                    net_pnl=None, hold_seconds=None,
                    setup_type=str(_g(t, "setup_type") or ""))
                if ok and not is_adopted_entry(
                        entered_by=str(_g(t, "entered_by") or ""),
                        source=str(_g(t, "source") or ""),
                        close_reason=str(_g(t, "close_reason") or "")):
                    genuine += 1
            except Exception:
                pass
    print(f"\n[bot_trades] breakdown rows: {total_bt} (genuine bot-own closed: {genuine})")
    print("  status:", dict(status_ct))
    print("  entered_by:", dict(eb_ct))

    print("\n=== READING ===")
    print("• alerts high + gate SKIP dominant → gate is the killer (read top SKIP reasons).")
    print("• alerts high + gate shows GO but trade_drops populated → a post-gate gate")
    print("    (account/guardrail/broker_rejected) kills it → real BLOCK BUG.")
    print("• alerts high + NO gate rows + NO drops → breakdown never reaches the gate")
    print("    (detector tagged experimental/learning-only, or dispatch filters it).")
    print("• bot_trades all simulated/rejected/artifact → 'fires' never become live trades.\n")


if __name__ == "__main__":
    main()
