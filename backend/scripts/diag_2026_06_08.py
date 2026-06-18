#!/usr/bin/env python3
"""
READ-ONLY diagnostic — 2026-06-08.

Answers three questions in one pass (writes NOTHING):

  PART 1 — vwap_fade recency (Audit Phase 7, Option A):
      Is the −3.98 EV_r still happening NOW, or is it stale pre-fix data?
      Splits genuine vwap_fade R-outcomes into last-20 vs older + date range.

  PART 2 — "Did v297 (universal liquidity gate) choke trade flow today?":
      Counts today's `universal_liquidity_gate` drops in `trade_drops` and
      compares to alerts fired + trades opened. High drop count ⇒ the gate is
      over-suppressing (likely a cold/empty `symbol_adv_cache`).

  PART 3 — MA forensics:
      Pulls today's MA bot_trades + reconciliation markers to confirm whether
      MA is a carry-over IB orphan (naked, synthetic SL/PT) vs a fresh bot fill.

Usage:  cd ~/Trading-and-Analysis-Platform/backend && python scripts/diag_2026_06_08_trade_flow_and_vwap_fade.py
"""
import os
import sys
from datetime import datetime, timezone

from pymongo import MongoClient


def _load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(os.path.dirname(here), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    return os.environ["MONGO_URL"], os.environ["DB_NAME"]


def _r_of(d):
    for k in ("r_multiple", "realized_r", "r"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _is_genuine(d):
    # Mirror recompute hygiene: exclude obvious artifacts.
    st = str(d.get("setup_type", "") or "").lower()
    cr = str(d.get("effective_close_reason", d.get("close_reason", "")) or "").lower()
    eb = str(d.get("entered_by", "") or "").lower()
    if d.get("genuine") is False:
        return False
    for bad in ("reconcil", "imported", "phantom", "orphan"):
        if bad in st or bad in eb:
            return False
    for bad in ("phantom", "sweep", "purge", "reconcile", "external_flatten", "operator_external"):
        if bad in cr:
            return False
    return True


def _today_start_utc():
    n = datetime.now(timezone.utc)
    return datetime(n.year, n.month, n.day, tzinfo=timezone.utc)


def main():
    mongo_url, db_name = _load_env()
    db = MongoClient(mongo_url)[db_name]
    print(f"[db] {mongo_url} / {db_name}\n")

    # ───────────────────────── PART 1 — vwap_fade recency ─────────────────────────
    print("=" * 78)
    print("PART 1 — vwap_fade RECENCY (is −3.98 EV_r still happening now?)")
    print("=" * 78)
    rows = list(db.alert_outcomes.find(
        {"setup_type": {"$regex": "^vwap_fade"}}
    ).sort("closed_at", 1))
    gen = [d for d in rows if _is_genuine(d) and _r_of(d) is not None]
    print(f"  vwap_fade rows: {len(rows)} total · {len(gen)} genuine-with-R\n")
    if gen:
        def _ev(sample):
            rs = [_r_of(d) for d in sample]
            wins = [r for r in rs if r > 0]
            losses = [r for r in rs if r <= 0]
            wr = len(wins) / len(rs) if rs else 0
            aw = sum(wins) / len(wins) if wins else 0.0
            al = abs(sum(losses) / len(losses)) if losses else 1.0
            return wr, (wr * aw) - ((1 - wr) * al), len(rs)

        def _dt(d):
            return str(d.get("closed_at", ""))[:10]

        last20 = gen[-20:]
        older = gen[:-20]
        wr_a, ev_a, n_a = _ev(gen)
        wr_l, ev_l, n_l = _ev(last20)
        print(f"  date range : {_dt(gen[0])}  →  {_dt(gen[-1])}")
        print(f"  ALL genuine ({n_a:>3}):  win {wr_a:>5.0%}   EV {ev_a:+.2f}R")
        print(f"  LAST 20     ({n_l:>3}):  win {wr_l:>5.0%}   EV {ev_l:+.2f}R")
        if older:
            wr_o, ev_o, n_o = _ev(older)
            print(f"  OLDER       ({n_o:>3}):  win {wr_o:>5.0%}   EV {ev_o:+.2f}R")
        print(f"\n  recent R-multiples (last 20): "
              f"{['%+.1f' % _r_of(d) for d in last20]}")
        verdict = "STILL BLEEDING — disable" if ev_l < -0.3 else (
            "recovering — consider throttle" if ev_l < 0 else "POSITIVE recently — keep/watch")
        print(f"\n  >>> VERDICT: last-20 EV {ev_l:+.2f}R → {verdict}")

    # ───────────────── PART 2 — did v297 choke trade flow today? ─────────────────
    print("\n" + "=" * 78)
    print("PART 2 — TRADE FLOW TODAY (is the v297 liquidity gate over-blocking?)")
    print("=" * 78)
    t0 = _today_start_utc()
    drops_today = list(db.trade_drops.find({"created_at": {"$gte": t0}}))
    by_gate = {}
    for d in drops_today:
        by_gate[d.get("gate", "?")] = by_gate.get(d.get("gate", "?"), 0) + 1
    liq_drops = [d for d in drops_today if d.get("gate") == "universal_liquidity_gate"]
    print(f"  trade_drops today (all gates): {len(drops_today)}")
    for g, c in sorted(by_gate.items(), key=lambda x: -x[1]):
        print(f"      {g:<34} {c}")
    print(f"\n  universal_liquidity_gate (v297) drops today: {len(liq_drops)}")
    for d in liq_drops[:12]:
        ctx = d.get("context", {}) or {}
        print(f"      {d.get('symbol','?'):<6} {d.get('setup_type','?'):<14} "
              f"tier={ctx.get('tier','?'):<11} adv=${ctx.get('avg_dollar_volume',0):>14,} "
              f"fail_closed={ctx.get('fail_closed')}")
    fail_closed_n = sum(1 for d in liq_drops if (d.get("context") or {}).get("fail_closed"))
    print(f"\n  of those, fail-closed (unprovable ADV): {fail_closed_n}/{len(liq_drops)}")
    print(f"  symbol_adv_cache size: {db.symbol_adv_cache.estimated_document_count()} docs")
    opened_today = db.bot_trades.count_documents({"created_at": {"$gte": t0}})
    print(f"  bot_trades opened today: {opened_today}")
    print("\n  >>> If fail-closed count is HIGH and adv_cache is small/stale,")
    print("      v297 is rejecting legit liquid names → tune (warm cache / relax floor).")

    # ───────────────────────── PART 3 — MA forensics ─────────────────────────
    print("\n" + "=" * 78)
    print("PART 3 — MA forensics (carry-over orphan vs fresh fill?)")
    print("=" * 78)
    ma = list(db.bot_trades.find({"symbol": "MA"}).sort("created_at", -1).limit(5))
    print(f"  MA bot_trades (latest {len(ma)}):")
    for t in ma:
        print(f"      id={str(t.get('_id'))[-6:]} status={t.get('status'):<10} "
              f"entered_by={t.get('entered_by','?'):<24} reason={t.get('close_reason','-')}")
        print(f"        created={str(t.get('created_at'))[:19]} "
              f"entry={t.get('fill_price')} stop={t.get('stop_price')} "
              f"targets={t.get('target_prices')} shares={t.get('shares')}")
    print("\n  >>> entered_by containing 'reconcil'/'orphan' + missing stop/targets")
    print("      ⇒ carry-over IB orphan adopted with synthetic defaults (NOT a fresh bot fill).")


if __name__ == "__main__":
    sys.exit(main())
