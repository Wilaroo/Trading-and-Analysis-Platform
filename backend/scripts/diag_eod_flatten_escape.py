#!/usr/bin/env python3
"""
diag_eod_flatten_escape.py  (read-only) — EOD-flatten escape forensics
=======================================================================
Built for the ACMR scalp that lived 3,952 minutes (65+ hours) before gapping
through its stop. A scalp should die by (a) the 60-min decay sweep, (b) the
15:55 ET EOD close pass, or (c) the 15:45+ naked/force-flatten guard. This
probe reconstructs which gate(s) the trade was INVISIBLE to and what the
schedulers were doing on every EOD window the trade survived.

Sections:
  1. bot_trades rows for the symbol — full lifecycle dump + hold duration.
  2. Guard-eligibility replay per row:
       • decay sweep   — timeframe/status/executed_at requirements
       • EOD close     — order-policy resolution (should_close_at_eod) and
                         which precedence branch decided it
       • heartbeat qry — would the row have counted as "eligible" in the
                         EOD heartbeat (closed_at/exit_price/fill_price/
                         close_at_eod attr query)
  3. bracket_lifecycle_events for the symbol.
  4. Per-EOD-day scheduler evidence while the trade was open:
       • bot_events event_type=eod_auto_close (did the close pass run? did
         this symbol fail?)
       • sentcom_thoughts category=eod_heartbeat (was the manage loop alive
         in the window?)
       • state_integrity_events for the symbol.
  5. Verdict — most likely escape path(s).

Usage:
  cd ~/Trading-and-Analysis-Platform && \
    .venv/bin/python backend/scripts/diag_eod_flatten_escape.py --symbol ACMR --days 30
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env", BACKEND / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        sys.exit(1)
    print(f"[db] {name} @ {url.split('@')[-1]}")
    return MongoClient(url)[name]


def _enum(v):
    return getattr(v, "value", v)


def _s(v, n=None):
    out = "-" if v is None else str(_enum(v))
    return out[:n] if n else out


def _dt(v):
    """Parse an ISO string / datetime → aware UTC datetime, or None."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _et(dt_utc):
    try:
        from zoneinfo import ZoneInfo
        return dt_utc.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        return dt_utc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="ACMR")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--trade-id", default=None,
                    help="id prefix — bypasses the symbol/date filter entirely")
    ap.add_argument("--min-hold-min", type=float, default=0.0,
                    help="only replay rows held longer than this (minutes)")
    args = ap.parse_args()
    sym = args.symbol.upper()
    _load_env()
    db = _db()
    cut_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
    cutoff = cut_dt.isoformat()

    # v2 — TYPE-AGNOSTIC window: created_at/closed_at may be stored as ISO
    # strings OR native BSON datetimes depending on the writer's era, and
    # Mongo range queries only match the SAME BSON type (type bracketing).
    # Also match on closed_at so a long-lived row CREATED before the window
    # but CLOSED inside it (the EXT_SL-autopsy semantics) is still found.
    if args.trade_id:
        q = {"id": {"$regex": f"^{args.trade_id}"}}
    else:
        q = {"symbol": sym, "$or": [
            {"created_at": {"$gte": cutoff}},
            {"created_at": {"$gte": cut_dt}},
            {"closed_at": {"$gte": cutoff}},
            {"closed_at": {"$gte": cut_dt}},
        ]}
    rows = list(db["bot_trades"].find(q, {"_id": 0}).sort("created_at", -1))

    print("\n" + "=" * 100)
    print(f"1. bot_trades for {args.trade_id or sym} — last {args.days}d "
          f"(created OR closed in window) — {len(rows)} row(s) (newest first)")
    print("=" * 100)
    for t in rows:
        ex, cl = _dt(t.get("executed_at")), _dt(t.get("closed_at"))
        hold_min = ((cl or datetime.now(timezone.utc)) - ex).total_seconds() / 60.0 if ex else None
        print(f"\n  id={_s(t.get('id'))}  dir={_s(t.get('direction'))}"
              f"  shares={_s(t.get('shares'))}/{_s(t.get('remaining_shares'))}rem"
              f"  status={_s(t.get('status'))}  entered_by={_s(t.get('entered_by'))}")
        print(f"    setup={_s(t.get('setup_type'))}  style={_s(t.get('trade_style'))}"
              f"  tf={_s(t.get('timeframe'))}  close_at_eod_attr={_s(t.get('close_at_eod'))}"
              f"  sim={_s(t.get('simulated'))}")
        print(f"    entry={_s(t.get('entry_price'))}  fill={_s(t.get('fill_price'))}"
              f"  stop={_s(t.get('stop_price'))}  exit={_s(t.get('exit_price'))}")
        print(f"    created={_s(t.get('created_at'), 19)}"
              f"  executed={_s(t.get('executed_at'), 19)}"
              f"  closed={_s(t.get('closed_at'), 19)}"
              f"  HOLD={'-' if hold_min is None else f'{hold_min:,.0f} min'}")
        print(f"    close_reason={_s(t.get('close_reason'))}"
              f"  realized_pnl={_s(t.get('realized_pnl'))}"
              f"  net_pnl={_s(t.get('net_pnl'))}")
        print(f"    raw types: created={type(t.get('created_at')).__name__}"
              f" executed={type(t.get('executed_at')).__name__}"
              f" closed={type(t.get('closed_at')).__name__}"
              f"  symbol_field={t.get('symbol')!r}")

    # ── 2. guard-eligibility replay ──────────────────────────────────────
    print("\n" + "=" * 100)
    print("2. Guard-eligibility replay (per row)")
    print("=" * 100)
    try:
        from services.order_policy_registry import (
            should_close_at_eod, get_policy_for_trade)
        _policy_ok = True
    except Exception as ie:
        print(f"  (order_policy_registry import failed: {ie} — policy replay skipped)")
        _policy_ok = False

    suspects = []
    for t in rows:
        ex, cl = _dt(t.get("executed_at")), _dt(t.get("closed_at"))
        hold_min = ((cl or datetime.now(timezone.utc)) - ex).total_seconds() / 60.0 if ex else None
        if hold_min is not None and hold_min < args.min_hold_min:
            continue
        tid = _s(t.get("id"), 8)
        tf = str(_enum(t.get("timeframe")) or "").lower()
        status = str(_enum(t.get("status")) or "").lower()
        findings = []
        print(f"\n  ── trade {tid} (hold={'-' if hold_min is None else f'{hold_min:,.0f}min'}) "
              f"──────────────────────────────")

        # decay sweep requirements (position_manager.check_scalp_decay):
        #   timeframe == 'scalp', status == 'open' (in bot._open_trades),
        #   executed_at/entry_time parseable.
        decay_tf = (tf == "scalp")
        decay_ts = ex is not None
        print(f"  decay sweep   : tf=='scalp'? {decay_tf} (tf={tf!r})"
              f"  executed_at parseable? {decay_ts}"
              f"  final_status={status!r}")
        if not decay_tf:
            findings.append("DECAY-INVISIBLE: timeframe is not 'scalp' — the "
                            "60-min decay sweep never considers this row")
        if not decay_ts:
            findings.append("DECAY-INVISIBLE: executed_at/entry_time missing/unparseable")
        if status in ("rejected", "pending", "cancelled"):
            findings.append(f"MEMORY-INVISIBLE: final status={status!r} — rows in this "
                            "state are NOT in bot._open_trades, so decay sweep, EOD "
                            "close pass AND the tracked map of the naked guard all "
                            "miss it (CASY bookkeeping class)")

        # EOD close pass: should_close_at_eod via ORDER POLICY
        if _policy_ok:
            try:
                pol = get_policy_for_trade(t)
                scae = should_close_at_eod(t)
                style = t.get("trade_style")
                branch = ("trade_style" if style
                          else ("setup_registry" if t.get("setup_type") else "default"))
                print(f"  eod close     : should_close_at_eod={scae} "
                      f"(policy={getattr(pol, 'style', '?')} via {branch})")
                if not scae:
                    findings.append("EOD-EXEMPT: order policy resolves close_at_eod="
                                    "False — the 15:55 close pass deliberately holds "
                                    "this row overnight")
            except Exception as pe:
                print(f"  eod close     : policy replay failed: {pe}")

        # heartbeat eligibility query (check_eod_close v169):
        hb_match = (t.get("closed_at") is None and t.get("exit_price") is None
                    and t.get("fill_price") is not None
                    and t.get("close_at_eod") is True)
        print(f"  heartbeat qry : would match eligible-count query "
              f"(while open)? closed_at_None+exit_None+fill_set+attr_True "
              f"→ attr={_s(t.get('close_at_eod'))} fill={_s(t.get('fill_price'))}"
              f" (final-state match={hb_match})")
        if t.get("close_at_eod") is False:
            findings.append("HEARTBEAT-INVISIBLE: close_at_eod attr is False — the "
                            "EOD heartbeat eligible-count never included this row")
        if t.get("fill_price") is None:
            findings.append("HEARTBEAT-INVISIBLE: fill_price is None")

        if findings:
            suspects.append((tid, findings))
            for f in findings:
                print(f"  ⚠️  {f}")
        else:
            print("  ✓ row looks fully visible to all three guards — escape must "
                  "be SCHEDULER-side (see section 4) or pre-date the guards")

    # ── 3. lifecycle events ──────────────────────────────────────────────
    print("\n" + "=" * 100)
    print(f"3. bracket_lifecycle_events for {sym} — last {args.days}d")
    print("=" * 100)
    evs = list(db["bracket_lifecycle_events"].find(
        {"symbol": sym}, {"_id": 0},
    ).sort([("ts", -1), ("created_at", -1)]).limit(60))
    if not evs:
        print("  (none)")
    for e in reversed(evs):
        ts = _s(e.get("ts") or e.get("created_at"), 19)
        print(f"  {ts}  phase={_s(e.get('phase'))} ok={_s(e.get('success'))}"
              f" trade={_s(e.get('trade_id'), 8)} reason={_s(e.get('reason'))}")

    # ── 4. per-EOD-day scheduler evidence ────────────────────────────────
    print("\n" + "=" * 100)
    print("4. Scheduler evidence on each EOD window the trade(s) survived")
    print("=" * 100)
    # collect the union of (executed, closed) windows across rows
    days = set()
    for t in rows:
        ex, cl = _dt(t.get("executed_at")), _dt(t.get("closed_at"))
        if not ex:
            continue
        cur = _et(ex).date()
        end = _et(cl or datetime.now(timezone.utc)).date()
        while cur <= end:
            if cur.weekday() < 5:
                days.add(cur)
            cur += timedelta(days=1)
    if not days:
        print("  (no executed rows → no hold window)")
    for d in sorted(days):
        ds = d.strftime("%Y-%m-%d")
        print(f"\n  {ds} ({d.strftime('%A')})")
        # 4a. did the EOD close pass persist an event?
        eod_evs = list(db["bot_events"].find(
            {"event_type": "eod_auto_close", "date": ds}, {"_id": 0}))
        if not eod_evs:
            print("    eod_auto_close event : NONE — close pass never persisted "
                  "(backend down / loop dead / pre-v152?)")
        for e in eod_evs:
            failed = e.get("failed_symbols") or []
            extra = e.get("early_exit_reason")
            mark = " ⚠️ THIS SYMBOL FAILED" if sym in failed else ""
            print(f"    eod_auto_close event : closed={_s(e.get('positions_closed'))}"
                  f" failed={failed}"
                  f"{f' early_exit={extra}' if extra else ''}{mark}")
        # 4b. heartbeats in the EOD window that day
        hb_q = {
            "$or": [{"category": "eod_heartbeat"},
                    {"metadata.category": "eod_heartbeat"}],
            "timestamp": {"$gte": f"{ds}T00:00:00", "$lte": f"{ds}T23:59:59"},
        }
        hbs = list(db["sentcom_thoughts"].find(hb_q, {"_id": 0}).sort("timestamp", 1))
        if not hbs:
            print("    eod heartbeats       : NONE — manage loop NOT alive in the "
                  "EOD window this day")
        else:
            first, last = hbs[0], hbs[-1]
            eligibles = {(h.get("metadata") or {}).get("eligible_positions")
                         for h in hbs}
            print(f"    eod heartbeats       : {len(hbs)} "
                  f"({_s(first.get('timestamp'), 19)} → {_s(last.get('timestamp'), 19)} UTC)"
                  f" eligible_counts_seen={sorted(x for x in eligibles if x is not None)}")
        # 4c. state integrity events for the symbol
        sie = list(db["state_integrity_events"].find(
            {"symbol": sym, "ts": {"$gte": f"{ds}T00:00:00",
                                   "$lte": f"{ds}T23:59:59"}}, {"_id": 0}))
        for e in sie:
            print(f"    integrity event      : {_s(e.get('event'))} "
                  f"sev={_s(e.get('severity'))} detail={_s(e.get('detail'), 90)}")

    # ── 5. verdict ───────────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("5. Verdict")
    print("=" * 100)
    if suspects:
        for tid, findings in suspects:
            print(f"\n  trade {tid}:")
            for f in findings:
                print(f"    → {f}")
    else:
        print("  No row-level invisibility found — correlate section 4: days with "
              "no heartbeats / no eod_auto_close event mean the scheduler itself "
              "was down (or the trade pre-dates v19.34.301/302 guards).")
    print()


if __name__ == "__main__":
    main()
