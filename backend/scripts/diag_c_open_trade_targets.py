#!/usr/bin/env python3
"""
diag_c_open_trade_targets.py  —  2026-06-22  (SentCom / DGX Spark)  READ-ONLY

Pins WHY the open holds show TGT=0.00 / UPL=0.00 BEFORE any live-order patch.
For every open bot trade it reports: entry, stop, target(s), whether a target
order is attached, live mark (current_price), unrealized P&L, provenance
(scanner vs IB-adopted/reconciled), and whether a LIVE quote exists for the
symbol in ib_live_snapshot. Then it classifies each gap so we fix the RIGHT
thing:
   • NO-TARGET + ADOPTED        → adopted IB orphan, never had setup context
   • NO-TARGET + SCANNER        → target derivation/attach gap on execution
   • TARGET but NOT-ATTACHED    → bracket (OCA) never reached IB
   • NO-MARK + live-quote-exists→ quote not being applied to the trade (apply gap)
   • NO-MARK + no-live-quote    → symbol not subscribed to the live feed

Reads the LIVE backend (read-only):
   GET /api/trading-bot/trades/open
Plus Mongo ib_live_snapshot.current.quotes. Writes/changes NOTHING.

   .venv/bin/python scripts/diag_c_open_trade_targets.py
"""
import json
import os
import sys
import urllib.request
from collections import Counter

BASE = os.environ.get("DIAG_BASE_URL", "http://localhost:8001")


def _get(path):
    try:
        with urllib.request.urlopen(BASE.rstrip("/") + path, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  ! GET {path} failed: {e}")
        return None


def _env(key):
    for cand in ("backend/.env", os.path.join(os.path.dirname(__file__), "..", ".env"), ".env"):
        try:
            for line in open(cand, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and line.split("=", 1)[0].strip() == key:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    return os.environ.get(key)


def _live_quotes():
    try:
        from pymongo import MongoClient
        url, dbn = _env("MONGO_URL"), _env("DB_NAME")
        if not url or not dbn:
            return {}
        cli = MongoClient(url, serverSelectionTimeoutMS=4000)
        snap = cli[dbn]["ib_live_snapshot"].find_one({"_id": "current"}, {"_id": 0, "quotes": 1})
        cli.close()
        out = {}
        for sym, q in ((snap or {}).get("quotes") or {}).items():
            if isinstance(q, dict):
                p = q.get("last") or q.get("close") or q.get("price") or 0
                if not p and q.get("bid") and q.get("ask"):
                    p = (q["bid"] + q["ask"]) / 2.0
                if p:
                    out[sym.upper()] = float(p)
        return out
    except Exception as e:
        print(f"  ! live quote read failed: {e}")
        return {}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _first(d, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    return default


def _targets(t):
    tp = _first(t, "target_prices", default=[]) or []
    if isinstance(tp, (int, float)):
        tp = [tp]
    vals = [_f(x) for x in tp if _f(x) > 0]
    pt = _f(_first(t, "primary_target", "target_price", "target", default=0))
    if pt > 0 and pt not in vals:
        vals = [pt] + vals
    return vals


def _attached(t):
    if t.get("target_ever_attached"):
        return True
    if _first(t, "target_order_id", default=None):
        return True
    if _first(t, "target_order_ids", default=[]):
        return True
    return False


def _is_adopted(t):
    if _first(t, "adopted_from_orphan_at", default=None):
        return True
    src = str(_first(t, "synthetic_source", "entered_by", "source", default="") or "").lower()
    return any(k in src for k in ("orphan", "reconcil", "adopt", "external", "ib_"))


def main():
    print(f"=== C open-trade target/mark diagnostic  base={BASE} ===\n")
    quotes = _live_quotes()
    print(f"live quotes available: {len(quotes)} symbols\n")

    payload = _get("/api/trading-bot/trades/open")
    if not payload:
        print("ABORT — could not read /api/trading-bot/trades/open")
        sys.exit(1)
    trades = payload.get("trades", payload) if isinstance(payload, dict) else payload
    if not isinstance(trades, list):
        trades = next((v for v in payload.values() if isinstance(v, list)), [])
    print(f"open trades: {len(trades)}\n")

    rows = []
    for t in trades:
        sym = (_first(t, "symbol", default="?") or "?").upper()
        entry = _f(_first(t, "entry_price", "fill_price", default=0))
        stop = _f(_first(t, "stop_price", "stop_loss", default=0))
        tgts = _targets(t)
        mark = _f(_first(t, "current_price", "mark_price", default=0))
        upl = _f(_first(t, "unrealized_pnl", default=0))
        lq = quotes.get(sym, 0.0)
        rows.append({
            "sym": sym, "setup": _first(t, "setup_type", default="?"),
            "dir": _first(t, "direction", default="?"),
            "entry": entry, "stop": stop, "tgts": tgts, "attached": _attached(t),
            "mark": mark, "upl": upl, "lq": lq, "adopted": _is_adopted(t),
            "src": str(_first(t, "synthetic_source", "entered_by", "source", default="") or ""),
        })

    print(f"{'SYMBOL':<7}{'SETUP':<20}{'DIR':<6}{'ENTRY':>9}{'STOP':>9}{'TARGET':>10}"
          f"{'ATT':>4}{'MARK':>9}{'UPL':>10}{'LQ':>9}  {'PROV'}")
    print("-" * 110)
    for r in sorted(rows, key=lambda r: (bool(r["tgts"]), r["mark"] > 0)):
        tg = f"{r['tgts'][0]:.2f}" if r["tgts"] else "—"
        att = "Y" if r["attached"] else "-"
        prov = "ADOPTED" if r["adopted"] else "scanner"
        if r["src"]:
            prov += f"({r['src'][:14]})"
        print(f"{r['sym']:<7}{str(r['setup'])[:19]:<20}{str(r['dir'])[:5]:<6}{r['entry']:>9.2f}"
              f"{r['stop']:>9.2f}{tg:>10}{att:>4}{r['mark']:>9.2f}{r['upl']:>10.2f}{r['lq']:>9.2f}  {prov}")

    no_tgt = [r for r in rows if not r["tgts"]]
    tgt_unattached = [r for r in rows if r["tgts"] and not r["attached"]]
    no_mark = [r for r in rows if r["mark"] <= 0]
    no_mark_has_lq = [r for r in no_mark if r["lq"] > 0]
    no_mark_no_lq = [r for r in no_mark if r["lq"] <= 0]
    adopted = [r for r in rows if r["adopted"]]

    print("\n" + "=" * 60 + "\nSUMMARY\n" + "=" * 60)
    print(f"  open trades:                      {len(rows)}")
    print(f"  NO target:                        {len(no_tgt)}")
    print(f"    ├─ adopted (no setup context):  {sum(1 for r in no_tgt if r['adopted'])}")
    print(f"    └─ scanner (derivation/attach): {sum(1 for r in no_tgt if not r['adopted'])}")
    print(f"  target set but NOT attached @IB:  {len(tgt_unattached)}")
    print(f"  NO live mark (current_price<=0):  {len(no_mark)}")
    print(f"    ├─ live quote EXISTS (apply gap): {len(no_mark_has_lq)}")
    print(f"    └─ no live quote (not subscribed): {len(no_mark_no_lq)}")
    print(f"  IB-adopted holds total:           {len(adopted)}")
    if rows:
        print("\n  setup_type spread:")
        for k, v in Counter(r["setup"] for r in rows).most_common():
            print(f"     {v:>3}  {k}")

    print("\n" + "=" * 60 + "\nREAD\n" + "=" * 60)
    if no_tgt:
        if sum(1 for r in no_tgt if r["adopted"]) >= len(no_tgt) * 0.6:
            print("  • TGT=0 is mostly on ADOPTED IB orphans → fix = BACKFILL a target from")
            print("    entry/stop + an R-ladder for adopted holds (the scanner exec path already")
            print("    derives targets, so it's not an execution-propagation bug).")
        else:
            print("  • TGT=0 on SCANNER-entered holds → the derive/attach step is being skipped")
            print("    on the execution path for these — needs a targeted fix there.")
    if tgt_unattached:
        print(f"  • {len(tgt_unattached)} hold(s) have a target value but NO OCA order at IB →")
        print("    bracket attach gap (attach_oca_stop_target / bracket_reissue).")
    if no_mark_has_lq:
        print(f"  • {len(no_mark_has_lq)} hold(s) have NO mark despite a LIVE quote existing →")
        print("    the quote isn't being applied to the trade's current_price (APPLY gap),")
        print("    not a subscription gap.")
    if no_mark_no_lq:
        print(f"  • {len(no_mark_no_lq)} hold(s) have NO mark AND no live quote → not subscribed")
        print("    to the live feed (SUBSCRIPTION gap — add held symbols to the sub set).")
    if not no_tgt and not no_mark:
        print("  ✅ All open holds have a target and a live mark. No plumbing gap.")


if __name__ == "__main__":
    main()
