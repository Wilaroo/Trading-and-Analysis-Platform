#!/usr/bin/env python3
"""v19.34.166-audit — Market Regime Accuracy Audit (read-only)

Investigation prompted by the v19.34.165 9_ema_scalp dormancy review.
TradeCommand has TWO independent regime systems that don't talk to
each other; this script samples both, compares them to current live
SPY/VIX/QQQ data, and surfaces any mismatch.

What it audits
==============

A. MarketRegimeEngine (sophisticated)
   - File:  backend/services/market_regime_engine.py
   - Enum:  CONFIRMED_UP / HOLD / CONFIRMED_DOWN
   - Used:  dashboard widget, confidence gate, AI modules
   - API:   GET /api/market-regime/current?force_refresh=true
   - Cache: 30 min

B. EnhancedBackgroundScanner._market_regime (in-scanner, ad-hoc)
   - File:  backend/services/enhanced_scanner.py  (def _update_market_context, L1913)
   - Enum:  STRONG_UPTREND / STRONG_DOWNTREND / MOMENTUM /
            RANGE_BOUND / FADE / VOLATILE
   - Used:  attached to every live alert as `market_regime` feature;
            documented metadata for STRATEGY_REGIME_PREFERENCES
            (NOT a hard gate per L182-188 comment).
   - Update logic: SPY-only — dist_from_vwap, rsi_14, daily_range_pct,
                   trend, above_vwap, above_ema9.  NO VIX, breadth, QQQ.

What we check
=============
1. Current state of both systems
2. Re-compute B independently from the SAME SPY snapshot the scanner
   uses — flag mismatch (engine bug vs computational bug)
3. Pull live SPY/QQQ/VIX/IWM via the API and sanity-check against
   the engine's signal-block scores
4. Last 30 days of MarketState history from `market_regime` Mongo
   collection — flag stuck transitions (e.g. >7 days without change
   when broad market clearly moved)
5. Sample 20 recent live_alerts and report distribution of their
   embedded `market_regime` field — confirms what scanner regime
   was ACTUALLY tagging trades with throughout the day

Usage:
    cd ~/Trading-and-Analysis-Platform && source .venv/bin/activate
    DB_NAME=tradecommand python backend/scripts/audit_regime_v19_34_166.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient


def hr(t: str) -> None:
    print(f"\n{'=' * 72}\n  {t}\n{'=' * 72}")


def fetch(url: str, timeout: int = 8) -> dict:
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return {"_error": f"HTTP {r.status_code}", "_body": r.text[:200]}
    except Exception as e:
        return {"_error": str(e)}


def _recompute_scanner_regime(snap: dict) -> str:
    """Replay the EXACT logic from enhanced_scanner._update_market_context
    (L1928-1944) against a SPY snapshot dict so we can flag drift between
    what the scanner SHOULD say vs what it currently DOES say.

    Snapshot keys used (must match TechnicalSnapshot dataclass field
    names): daily_range_pct, trend, above_vwap, above_ema9, rsi_14,
    dist_from_vwap.
    """
    dr = float(snap.get("daily_range_pct") or 0)
    trend = str(snap.get("trend") or "").lower()
    above_vwap = bool(snap.get("above_vwap"))
    above_ema9 = bool(snap.get("above_ema9"))
    rsi = float(snap.get("rsi_14") or 50)
    d_vwap = abs(float(snap.get("dist_from_vwap") or 0))

    if dr > 2.0:
        return "VOLATILE"
    if trend == "uptrend" and above_vwap and above_ema9:
        return "MOMENTUM" if rsi > 60 else "STRONG_UPTREND"
    if trend == "downtrend" and not above_vwap:
        return "STRONG_DOWNTREND"
    if d_vwap < 0.5 and dr < 1.0:
        return "FADE" if (rsi > 55 or rsi < 45) else "RANGE_BOUND"
    return "RANGE_BOUND"


def main() -> int:
    base = "http://localhost:8001"
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    db = MongoClient(mongo_url)[db_name]

    # ─── A. Engine regime ─────────────────────────────────────────────
    hr("A. MarketRegimeEngine (/api/market-regime/current)")
    engine = fetch(f"{base}/api/market-regime/current?force_refresh=true")
    if "_error" in engine:
        print(f"  ❌ Engine endpoint failed: {engine}")
    else:
        print(f"  State:           {engine.get('state')}")
        print(f"  Composite score: {engine.get('composite_score')}/100")
        print(f"  Confidence:      {engine.get('confidence')}/100")
        print(f"  Last updated:    {engine.get('last_updated')}")
        sb = engine.get("signal_blocks", {})
        print("\n  Signal block scores:")
        for name, block in sb.items():
            print(f"    {name:<12}  {block.get('score', '?')}/100  "
                  f"(weight {block.get('weight', 0)})")

    # ─── B. Scanner regime (via recent alerts) ────────────────────────
    hr("B. Scanner._market_regime (sampled from last 50 live_alerts)")
    recent_alerts = list(db.live_alerts.find(
        {},
        {"_id": 0, "symbol": 1, "setup_type": 1, "market_regime": 1,
         "created_at": 1},
    ).sort("created_at", -1).limit(50))
    if not recent_alerts:
        print("  ⚠ No live_alerts present at all.")
    else:
        print(f"  Latest alert: {recent_alerts[0]}")
        regime_dist = Counter(a.get("market_regime") for a in recent_alerts)
        print(f"\n  Regime distribution across last {len(recent_alerts)} alerts:")
        for reg, ct in regime_dist.most_common():
            pct = 100.0 * ct / len(recent_alerts)
            bar = "█" * int(pct / 2)
            print(f"    {str(reg):<22}  {ct:>3}  ({pct:5.1f}%)  {bar}")

    # ─── C. Recompute scanner regime independently ────────────────────
    hr("C. Recompute scanner regime from current SPY snapshot")
    # Try the technicals endpoint for SPY snapshot
    spy_snap = None
    for ep in ("/api/technicals/snapshot/SPY",
               "/api/realtime-technical/SPY",
               "/api/technicals/SPY"):
        out = fetch(base + ep)
        if "_error" not in out:
            spy_snap = out
            print(f"  SPY snapshot from {ep}:")
            for k in ("current_price", "vwap", "ema_9", "ema_20",
                      "rsi_14", "dist_from_vwap", "daily_range_pct",
                      "trend", "above_vwap", "above_ema9"):
                if k in spy_snap:
                    print(f"    {k:<22}  {spy_snap[k]}")
            break
    if not spy_snap:
        print("  ⚠ No SPY snapshot endpoint responded.")
    else:
        computed = _recompute_scanner_regime(spy_snap)
        print(f"\n  Independently computed scanner regime: {computed}")
        if recent_alerts:
            actual = recent_alerts[0].get("market_regime")
            match = "✅ MATCH" if str(actual) == computed else "⚠ MISMATCH"
            print(f"  Latest alert says:                     {actual}")
            print(f"  Verdict: {match}")

    # ─── D. Live cross-checks: SPY/QQQ/VIX  ───────────────────────────
    hr("D. Live cross-check: SPY / QQQ / IWM / VIX vs engine signals")
    quotes = {}
    for sym in ("SPY", "QQQ", "IWM", "VIX"):
        for ep in (f"/api/live/quote/{sym}",
                   f"/api/quote/{sym}",
                   f"/api/ib/quote/{sym}"):
            out = fetch(base + ep)
            if "_error" not in out:
                quotes[sym] = out
                last = out.get("last") or out.get("price") or out.get("close")
                chg = out.get("change_pct") or out.get("pct_change")
                print(f"  {sym:<5}  last={last}  change_pct={chg}")
                break
        else:
            print(f"  {sym:<5}  ⚠ no quote endpoint responded")

    # ─── E. Mongo 30-day regime history ───────────────────────────────
    hr("E. `market_regime` collection — last 30 days of state transitions")
    if "market_regime" not in db.list_collection_names():
        print(f"  Collection `market_regime` does NOT exist in `{db_name}`.")
        print("  → Engine is not persisting; we have NO historical record.")
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        rows = list(db.market_regime.find(
            {"last_updated": {"$gte": cutoff}},
            {"_id": 0, "last_updated": 1, "state": 1, "composite_score": 1},
        ).sort("last_updated", 1))
        if not rows:
            print(f"  No rows in last 30 days. Total docs: "
                  f"{db.market_regime.count_documents({})}")
        else:
            print(f"  {len(rows)} snapshots over last 30d.")
            last_state = None
            transitions = []
            for r in rows:
                st = r.get("state")
                if st != last_state and last_state is not None:
                    transitions.append((r.get("last_updated"), last_state, st))
                last_state = st
            print("\n  State distribution (last 30d):")
            for st, ct in Counter(r.get("state") for r in rows).most_common():
                pct = 100.0 * ct / len(rows)
                print(f"    {str(st):<18}  {ct:>4}  ({pct:5.1f}%)")
            print(f"\n  Transitions in last 30d: {len(transitions)}")
            for ts, fr, to in transitions[-15:]:
                print(f"    {ts[:19]}  {fr} → {to}")
            # Detect "stuck" — span of >7 days with no transition
            if transitions:
                last_change = datetime.fromisoformat(
                    transitions[-1][0].replace("Z", "+00:00"))
                stuck_days = (datetime.now(timezone.utc) - last_change).days
                if stuck_days > 7:
                    print(f"\n  ⚠ STUCK: last state change was {stuck_days}d ago.")
            else:
                print(f"\n  ⚠ STUCK: zero state transitions in 30 days "
                      f"(all snapshots say `{last_state}`).")

    # ─── F. Verdict ───────────────────────────────────────────────────
    hr("F. Verdict")
    print("  Run this audit again during a session where you EXPECT a")
    print("  regime shift (e.g. FOMC, CPI, big VIX move). If the engine")
    print("  doesn't transition within 30min of the event, the cache TTL")
    print("  or block scoring needs tuning.")
    print()
    print("  Next steps if any of the above flagged ⚠:")
    print("    1. Scanner uses SPY-only — consider adding QQQ/IWM/VIX")
    print("       for breadth-aware regime. See L1913 _update_market_context.")
    print("    2. Engine signal-block weights (Trend 35, Breadth 25,")
    print("       FTD 20, Vol/VIX 20) may need rebalancing per backtest.")
    print("    3. If §E shows the engine hasn't persisted any history,")
    print("       check that `_store_regime` is being called from the")
    print("       scheduler loop (server.py).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
