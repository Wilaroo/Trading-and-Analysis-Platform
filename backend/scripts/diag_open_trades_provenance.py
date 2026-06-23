#!/usr/bin/env python3
"""
diag_open_trades_provenance.py — READ-ONLY forensic for the CURRENT open book.

Answers the three operator questions, per open bot_trade, from real data:

  Q1. "Why were some marked ADOPTED even though they were bot-opened?"
      → For every reconciled/synthetic orphan, cross-checks the bot's own
        order intent (order_queue.trade_id == bot_trade.id, plus a symbol+
        side+time fallback) and the IB fill tape (ib_executions) to decide:
          BOT_TRACKED          — bot intent + tracked, not adopted (normal)
          ADOPTED_BUT_BOT_PATH — reconciled/synthetic BUT a matching bot
                                 order intent / IB fill exists → bot-originated
                                 then LOST (restart wiped _open_trades, or the
                                 NWSA-class "cancelled-but-filled" silent fill);
                                 the "I did NOT open this" warning is misleading.
          ADOPTED_EXTERNAL     — reconciled/synthetic AND no bot intent/fill →
                                 truly external or a prior-session leftover.

  Q2. "Why are some not scalp/intraday yet got taken before 10am?"
      → Prints trade_style/timeframe + fill time (ET) so you can see which
        styles filled when. (Daily-setup styles legitimately fill at the open;
        the flag to watch is STALE, see Q3.)

  Q3. "Make sure nothing is still firing from old/stale alerts that didn't
       meet the setup/trade parameters."
      → Joins each trade to its originating alert, computes alert→fill LAG,
        and FLAGS the two real fail-OPEN vectors in trade_execution.py
        (L1422-1437): alert created_at MISSING or UNPARSEABLE (staleness check
        skipped entirely), and LAG beyond the per-style stale threshold. Also
        surfaces prior_verdict_conflict (bot had REJECTed that setup).

NOTHING IS WRITTEN. GET-only against Mongo.

USAGE (repo root, DGX):
  .venv/bin/python backend/scripts/diag_open_trades_provenance.py
  .venv/bin/python backend/scripts/diag_open_trades_provenance.py --lookback-days 5
"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Mirrors trade_execution.py stale_thresholds (by timeframe) + a trade_style map.
STALE_BY_TIMEFRAME = {"scalp": 300, "day": 600, "swing": 900, "investment": 3600}
STALE_BY_STYLE = {
    "scalp": 300, "intraday": 600, "day": 600, "multi_day": 900,
    "swing": 900, "position": 3600, "investment": 3600,
}
DEFAULT_STALE = 600
FILL_MATCH_WINDOW_S = 1800  # ±30 min symbol+side fill/intent match window
BOT_PROVENANCE = {"bot_fired", "bot", "", None}


def _load_env():
    for cand in ["backend/.env", ".env",
                 os.path.join(os.path.dirname(__file__), "..", ".env")]:
        p = Path(cand)
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _dt(s):
    if not s:
        return None
    try:
        s = str(s).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _f(d, *keys, default=0.0):
    for k in keys:
        v = (d or {}).get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return default


def _s(d, *keys, default=""):
    for k in keys:
        v = (d or {}).get(k)
        if v not in (None, ""):
            return str(v)
    return default


def _et(d):
    """UTC datetime → naive ET-ish string (UTC-4, RTH season). Display only."""
    if not d:
        return "—"
    return (d - timedelta(hours=4)).strftime("%m-%d %H:%M:%S") + "ET"


def _side_for_direction(direction):
    return "BUY" if str(direction or "").lower().startswith("l") else "SELL"


def main():
    _load_env()
    lookback = 5
    if "--lookback-days" in sys.argv:
        try:
            lookback = int(sys.argv[sys.argv.index("--lookback-days") + 1])
        except Exception:
            pass
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"],
                     serverSelectionTimeoutMS=20000)[os.environ["DB_NAME"]]
    since_iso = (datetime.now(timezone.utc) - timedelta(days=lookback)).isoformat()

    trades = list(db["bot_trades"].find({"status": "open"}))
    if not trades:
        trades = list(db["bot_trades"].find(
            {"status": {"$nin": ["closed", "cancelled", "rejected", "exited", "flat"]}}))

    print("=" * 100)
    print(f"OPEN-TRADES PROVENANCE  (READ-ONLY)   now={datetime.now(timezone.utc).isoformat()[:19]}Z"
          f"   lookback={lookback}d")
    print(f"  open/active bot_trades: {len(trades)}")
    print("=" * 100)

    # ---- preload joins ----
    oq_by_tid, oq_by_symside = {}, {}
    for o in db["order_queue"].find({"queued_at": {"$gte": since_iso}}):
        tid = o.get("trade_id")
        if tid:
            oq_by_tid.setdefault(str(tid), []).append(o)
        oq_by_symside.setdefault(
            (str(o.get("symbol") or "").upper(),
             "BUY" if str(o.get("action") or "").upper().startswith("B") else "SELL"),
            []).append(o)

    fills_by_sym = {}
    for e in db["ib_executions"].find({"time": {"$gte": since_iso}}):
        fills_by_sym.setdefault(str(e.get("symbol") or "").upper(), []).append(e)

    alert_by_id, alert_by_symsetup = {}, {}
    for a in db["live_alerts"].find({"created_at": {"$gte": since_iso}}):
        aid = a.get("id")
        if aid:
            alert_by_id[str(aid)] = a
        alert_by_symsetup.setdefault(
            (str(a.get("symbol") or "").upper(), str(a.get("setup_type") or "")), []).append(a)

    prov_counts, flag_counts = Counter(), Counter()

    for t in sorted(trades, key=lambda x: _s(x, "executed_at", "entry_time", "created_at")):
        sym = _s(t, "symbol", default="?").upper()
        tid = _s(t, "id", "trade_id")
        direction = _s(t, "direction", default="?")
        setup = _s(t, "setup_type", "setup", "strategy_name", default="?")
        style = _s(t, "trade_style", "timeframe", "scan_tier", default="?").lower()
        entered_by = t.get("entered_by")
        syn = _s(t, "synthetic_source")
        ec = t.get("entry_context") or {}
        reconciled = bool(ec.get("reconciled") or syn or _s(t, "entered_by").startswith("reconciled"))
        verdict_conflict = bool(t.get("prior_verdict_conflict"))
        opened = _dt(_s(t, "executed_at", "entry_time", "created_at", "opened_at"))
        side = _side_for_direction(direction)

        # --- bot order intent? (trade_id first, then symbol+side+time) ---
        intents = list(oq_by_tid.get(tid, []))
        if not intents and opened:
            for o in oq_by_symside.get((sym, side), []):
                oq_t = _dt(o.get("queued_at"))
                if oq_t and abs((oq_t - opened).total_seconds()) <= FILL_MATCH_WINDOW_S:
                    intents.append(o)
        intent_statuses = sorted({_s(o, "status") for o in intents if o.get("status")})

        # --- IB fill on the tape? (symbol+side+time[, shares]) ---
        sh = _f(t, "shares", "original_shares")
        matched_fill = None
        for e in fills_by_sym.get(sym, []):
            if str(e.get("side") or "").upper() != side:
                continue
            e_t = _dt(e.get("time"))
            if e_t and opened and abs((e_t - opened).total_seconds()) <= FILL_MATCH_WINDOW_S:
                matched_fill = e
                break

        # --- provenance classification ---
        if not reconciled and entered_by in BOT_PROVENANCE:
            prov = "BOT_TRACKED"
        elif intents or matched_fill:
            prov = "ADOPTED_BUT_BOT_PATH"
        else:
            prov = "ADOPTED_EXTERNAL"
        prov_counts[prov] += 1

        # --- stale-alert audit ---
        alert = alert_by_id.get(_s(t, "alert_id"))
        if not alert and opened:
            cands = alert_by_symsetup.get((sym, setup), [])
            cands2 = [c for c in cands if (_dt(c.get("created_at")) and _dt(c.get("created_at")) <= opened)]
            if cands2:
                alert = max(cands2, key=lambda c: _dt(c.get("created_at")))
        a_created_raw = alert.get("created_at") if alert else None
        a_created = _dt(a_created_raw)
        thr = STALE_BY_STYLE.get(style) or STALE_BY_TIMEFRAME.get(style) or DEFAULT_STALE

        stale_flags = []
        if alert is not None:
            if not a_created_raw:
                stale_flags.append("ALERT_created_at_MISSING(fail-open)")
            elif a_created is None:
                stale_flags.append("ALERT_created_at_UNPARSEABLE(fail-open)")
            elif opened:
                lag = (opened - a_created).total_seconds()
                if lag > thr:
                    stale_flags.append(f"LAG {lag/60:.0f}m > stale-thr {thr//60}m")
        else:
            stale_flags.append("NO_ALERT_LINK")
        if verdict_conflict:
            stale_flags.append("PRIOR_VERDICT_CONFLICT(bot REJECTed setup)")
        for fl in stale_flags:
            flag_counts[fl.split("(")[0].split(" ")[0]] += 1

        lag_str = "—"
        if opened and a_created:
            lag_str = f"{(opened - a_created).total_seconds()/60:.0f}m"

        print(f"\n{sym:<6} {direction.upper():<5} {setup[:22]:<22} style={style:<11} "
              f"{prov}")
        print(f"   filled={_et(opened):<14}  entered_by={str(entered_by):<20} "
              f"synthetic_source={syn or '—'}  reconciled={reconciled}")
        print(f"   bot_intent={intent_statuses or 'NONE'}   ib_fill="
              f"{'YES order_id=' + str(matched_fill.get('order_id')) if matched_fill else 'none'}")
        print(f"   alert_created={str(a_created_raw)[:19] or '—':<19}  lag={lag_str:<6} "
              f"stale_thr={thr//60}m")
        if stale_flags:
            print(f"   ⚠ {' | '.join(stale_flags)}")

    print("\n" + "=" * 100)
    print("PROVENANCE SUMMARY")
    for k, v in prov_counts.most_common():
        print(f"   {k:<22} {v}")
    print("\nFLAG SUMMARY (stale / conformance)")
    for k, v in flag_counts.most_common():
        print(f"   {k:<34} {v}")
    print("\nREAD:")
    print("  ADOPTED_BUT_BOT_PATH  → bot DID open it (intent/fill exists); restart wiped tracking,")
    print("                          OR a cancelled-but-filled silent fill (NWSA-class). 'I did NOT")
    print("                          open this' is misleading for these.")
    print("  ADOPTED_EXTERNAL      → no bot intent/fill → truly external or prior-session leftover.")
    print("  ALERT_created_at_*    → the fail-OPEN vectors in trade_execution.py L1422-1437: when the")
    print("                          alert timestamp is missing/unparseable the staleness gate is SKIPPED.")
    print("  LAG > stale-thr       → fired from an alert older than its style's stale threshold.")
    print("  PRIOR_VERDICT_CONFLICT→ bot had REJECTed that setup ≥2 of last 3 — setup params not met.")
    print("=" * 100)


if __name__ == "__main__":
    main()
