#!/usr/bin/env python3
"""
v380 — dedup_cooldown IMPACT PROBE (READ-ONLY).  Issue 4.

QUESTION
--------
The 300s `dedup_cooldown` (alert_deduplicator.py, keyed by
(symbol, setup_type, direction)) is suspected of blocking legitimate
CONTINUATION re-entries on all-day trending names (e.g. HON). Is it, and WHY?

MECHANISM (for reference)
-------------------------
trading_bot_service.py:
  - should_skip(): SKIP if an open trade exists for the key OR the key fired
    within cooldown_s (300s).
  - mark_fired() is called BEFORE heavy evaluation (line ~4696) — so an alert
    that PASSES dedup but is later REJECTED downstream (smart_filter / gate /
    no-price …) STILL starts the 300s cooldown, even though no trade opened.

WHAT THIS PROBE DOES
--------------------
For every `dedup_cooldown` drop, it joins to `bot_trades` for the SAME
(symbol, setup, direction) and classifies the block:
  - BLOCKED_WHILE_OPEN   : a trade for the key was OPEN at the drop time
                           -> legit churn guard (intended behaviour).
  - LOST_CONTINUATION    : the key's trade had already CLOSED before the drop
                           (same day) -> a continuation re-entry we blocked.
  - BLOCKED_THEN_TRADED  : the key DID open a trade later that day -> cooldown
                           merely delayed entry.
  - BLOCKED_NO_TRADE_DAY : NO trade for the key that day at all -> the cooldown
                           was started by a fire that never became a trade
                           (the mark_fired-before-eval opportunity loss).

The mix tells us the fix:
  * mostly BLOCKED_NO_TRADE_DAY -> move mark_fired to AFTER a trade opens.
  * mostly LOST_CONTINUATION    -> allow re-entry after a profitable close /
                                   shorten cooldown for trending names.
  * mostly BLOCKED_WHILE_OPEN   -> dedup is working as intended; look elsewhere.

Usage (DGX, repo root):
  .venv/bin/python backend/scripts/diag_v380_dedup_cooldown_impact.py --days 7
  .venv/bin/python backend/scripts/diag_v380_dedup_cooldown_impact.py --days 7 --symbol HON
"""
import sys
from collections import defaultdict
from datetime import datetime, timezone

DROPS = "trade_drops"
TRADES = "bot_trades"


def _arg(flag, default, cast=str):
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


def _epoch(d, keys):
    for k in keys:
        v = d.get(k)
        if v in (None, ""):
            continue
        if isinstance(v, (int, float)):
            return float(v) / 1000.0 if v > 1e12 else float(v)
        if isinstance(v, datetime):
            return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp()
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except Exception:
            try:
                return datetime.strptime(str(v)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                continue
    return None


def _key(sym, setup, direction):
    return ((sym or "").upper().strip(), (setup or "").lower().strip(),
            (direction or "").lower().strip().replace("buy", "long").replace("sell", "short"))


def _day(ep):
    return datetime.fromtimestamp(ep, timezone.utc).strftime("%Y-%m-%d") if ep else "?"


def main():
    days = _arg("--days", 7, float)
    only = _arg("--symbol", None)
    only = only.upper() if only else None
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    db = _load_db()

    # 1) dedup drops (cooldown + open_position for context)
    q = {"gate": {"$in": ["dedup_cooldown", "dedup_open_position"]}}
    if only:
        q["symbol"] = only
    cooldown, openpos = [], 0
    for d in db[DROPS].find(q, {"_id": 0}):
        ep = _epoch(d, ("ts_epoch_ms", "ts", "created_at", "dropped_at", "at"))
        if ep is not None and ep < since:
            continue
        if d.get("gate") == "dedup_open_position":
            openpos += 1
            continue
        cooldown.append((ep, d))
    print("=" * 84)
    print(f"dedup drops (last {days}d{', '+only if only else ''}): "
          f"cooldown={len(cooldown)}  open_position={openpos}")
    print("=" * 84)
    if not cooldown:
        print("No dedup_cooldown drops in window — nothing to analyze.")
        return

    # 2) index bot_trades by key -> list of (created_ep, closed_ep, day)
    syms = sorted({(d.get("symbol") or "").upper() for _, d in cooldown if d.get("symbol")})
    trades_by_key = defaultdict(list)
    tq = {"symbol": {"$in": syms}} if syms else {}
    for t in db[TRADES].find(tq, {"_id": 0}):
        k = _key(t.get("symbol"), t.get("setup_type"), t.get("direction"))
        c = _epoch(t, ("created_at", "entry_time", "opened_at", "created"))
        x = _epoch(t, ("closed_at", "exit_time", "closed"))
        trades_by_key[k].append((c, x))

    # 3) classify each cooldown drop
    verdict = defaultdict(int)
    by_sym = defaultdict(lambda: defaultdict(int))
    cd_left = []
    examples = defaultdict(list)
    for ep, d in cooldown:
        k = _key(d.get("symbol"), d.get("setup_type"), d.get("direction"))
        ctx = d.get("context") or {}
        if isinstance(ctx, dict) and isinstance(ctx.get("cooldown_seconds_left"), (int, float)):
            cd_left.append(float(ctx["cooldown_seconds_left"]))
        day = _day(ep)
        same_day = [(c, x) for (c, x) in trades_by_key.get(k, [])
                    if c is not None and _day(c) == day]
        if ep is None:
            v = "UNKNOWN_TS"
        elif any(c is not None and c <= ep and (x is None or x >= ep) for c, x in same_day):
            v = "BLOCKED_WHILE_OPEN"
        elif any(x is not None and x < ep for c, x in same_day):
            v = "LOST_CONTINUATION"
        elif any(c is not None and c > ep for c, x in same_day):
            v = "BLOCKED_THEN_TRADED"
        else:
            v = "BLOCKED_NO_TRADE_DAY"
        verdict[v] += 1
        by_sym[k[0]][v] += 1
        if len(examples[v]) < 4:
            examples[v].append(f"{k[0]}/{k[1]}/{k[2]} @ {day}")

    # 4) report
    total = len(cooldown)
    print("\nCLASSIFICATION OF dedup_cooldown DROPS")
    print("-" * 84)
    order = ["BLOCKED_WHILE_OPEN", "LOST_CONTINUATION", "BLOCKED_THEN_TRADED",
             "BLOCKED_NO_TRADE_DAY", "UNKNOWN_TS"]
    label = {
        "BLOCKED_WHILE_OPEN":   "legit churn guard (position was OPEN)",
        "LOST_CONTINUATION":    "re-entry blocked AFTER the key's trade closed",
        "BLOCKED_THEN_TRADED":  "cooldown only DELAYED entry (traded later same day)",
        "BLOCKED_NO_TRADE_DAY": "cooldown started by a fire that never traded (mark_fired-pre-eval)",
        "UNKNOWN_TS":           "no timestamp on drop",
    }
    for v in order:
        n = verdict.get(v, 0)
        if n:
            print(f"  {v:<22} {n:>6} ({n/total*100:4.1f}%)  {label[v]}")
            for ex in examples[v]:
                print(f"        e.g. {ex}")

    if cd_left:
        cl = sorted(cd_left)
        print(f"\n  cooldown_seconds_left on blocks: min={cl[0]:.0f} "
              f"med={cl[len(cl)//2]:.0f} max={cl[-1]:.0f} (window=300s)")

    print("\nTOP BLOCKED SYMBOLS (by cooldown drops)")
    print("-" * 84)
    top = sorted(by_sym.items(), key=lambda kv: -sum(kv[1].values()))[:15]
    print(f"  {'symbol':<8} {'total':>6}  {'WHILE_OPEN':>10} {'LOST_CONT':>9} "
          f"{'DELAYED':>8} {'NO_TRADE':>9}")
    for sym, vs in top:
        print(f"  {sym:<8} {sum(vs.values()):>6}  {vs.get('BLOCKED_WHILE_OPEN',0):>10} "
              f"{vs.get('LOST_CONTINUATION',0):>9} {vs.get('BLOCKED_THEN_TRADED',0):>8} "
              f"{vs.get('BLOCKED_NO_TRADE_DAY',0):>9}")

    # 5) verdict / recommendation
    print("\n" + "=" * 84)
    print("VERDICT")
    print("=" * 84)
    lost = verdict.get("LOST_CONTINUATION", 0)
    notrade = verdict.get("BLOCKED_NO_TRADE_DAY", 0)
    whileopen = verdict.get("BLOCKED_WHILE_OPEN", 0)
    biggest = max(verdict, key=verdict.get)
    print(f"  dominant class: {biggest} ({verdict[biggest]}/{total})")
    if biggest == "BLOCKED_NO_TRADE_DAY":
        print("  ==> Root cause is mark_fired-BEFORE-eval: the cooldown is consumed by")
        print("      alerts that never opened a trade (rejected downstream). FIX: only")
        print("      mark_fired AFTER a trade actually opens (move the call past the")
        print("      gate, or call it on successful submit). Low-risk, high-recovery.")
    elif biggest == "LOST_CONTINUATION":
        print("  ==> The cooldown is blocking re-entries AFTER the key's trade closed.")
        print("      FIX: allow continuation re-entry once flat (clear the key on close),")
        print("      and/or shorten cooldown for trending names. Validate vs the PRCT")
        print("      stacking incident the dedup was built to prevent.")
    elif biggest == "BLOCKED_WHILE_OPEN":
        print("  ==> dedup is mostly working as intended (blocking stacking on OPEN")
        print("      positions). The continuation complaint may be the OPEN-position")
        print("      rule, not the cooldown — investigate allow_multiple_entries.")
    print(f"\n  (lost_continuation={lost}, no_trade_day={notrade}, while_open={whileopen})")


if __name__ == "__main__":
    main()
