#!/usr/bin/env python3
"""
diag_silent_fill_forensic.py — READ-ONLY. Pins the exact order path for the
"ADOPTED but bot-REJECTED" shorts (CRDO/FOXA/KR/LULU class).

For each target symbol it lays the three tapes side by side and reconstructs
what happened, by order_id and by time:

  • order_queue   — what the BOT submitted (action, qty, status, queued_at,
                    order_id, trade_id, refusal/cancel reason). Shows whether
                    the bot tried to open it and whether the parent was
                    later cancelled / rejected / expired.
  • ib_executions — the ACTUAL broker fills (side, shares, price, time,
                    order_id). The ground truth of what filled.
  • bot_trades    — what the bot ended up tracking (status, entered_by,
                    synthetic_source, prior_verdicts, close_reason).

VERDICT per symbol:
  CANCELLED_BUT_FILLED (NWSA-class) — a bot order_queue row went
      cancelled/rejected/expired BUT a matching ib_executions fill exists
      (same order_id, or same symbol+side within the window) → the cancel
      lost the race to the fill; the bot is now in a position it tried to abort.
  BOT_FILLED_THEN_LOST — bot order filled normally, but no live _open_trade /
      bot_trade tracked it at reconcile time (restart wiped memory) → re-adopted.
  EXTERNAL_OR_PRIOR_SESSION — IB fill with NO bot order_queue intent at all →
      truly external (manual) or a leftover from a previous session.
  NO_FILL_FOUND — no ib_executions row in window (inspect manually).

Targets default to the reconciled orphans in the current open book; override
with --symbols A,B,C.  NOTHING IS WRITTEN.

USAGE (repo root, DGX):
  .venv/bin/python backend/scripts/diag_silent_fill_forensic.py
  .venv/bin/python backend/scripts/diag_silent_fill_forensic.py --symbols CRDO,FOXA,KR,LULU
  .venv/bin/python backend/scripts/diag_silent_fill_forensic.py --hours 36
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CANCEL_STATES = {"cancelled", "canceled", "rejected", "expired", "timeout", "refused"}
FILL_WINDOW_S = 1800


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


def _t(d):
    return d.strftime("%m-%d %H:%M:%S") if d else "—"


def _norm_side(s):
    s = str(s or "").upper()
    if s.startswith("B"):
        return "BUY"
    if s.startswith("S"):
        return "SELL"
    return s or "?"


def main():
    _load_env()
    hours = 36
    symbols = None
    if "--hours" in sys.argv:
        try:
            hours = int(sys.argv[sys.argv.index("--hours") + 1])
        except Exception:
            pass
    if "--symbols" in sys.argv:
        try:
            symbols = [s.strip().upper() for s in
                       sys.argv[sys.argv.index("--symbols") + 1].split(",") if s.strip()]
        except Exception:
            pass

    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"],
                     serverSelectionTimeoutMS=20000)[os.environ["DB_NAME"]]
    since_iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    # default targets: reconciled orphans in the open book
    if not symbols:
        symbols = []
        for t in db["bot_trades"].find({"status": "open"}):
            ec = t.get("entry_context") or {}
            recon = (ec.get("reconciled") or t.get("synthetic_source")
                     or str(t.get("entered_by") or "").startswith("reconciled"))
            if recon and t.get("symbol"):
                symbols.append(str(t["symbol"]).upper())
        symbols = sorted(set(symbols))

    print("=" * 100)
    print(f"SILENT-FILL FORENSIC  (READ-ONLY)   now={datetime.now(timezone.utc).isoformat()[:19]}Z"
          f"   window={hours}h")
    print(f"  targets: {symbols or '(none — no reconciled orphans in open book)'}")
    print("=" * 100)

    verdicts = {}
    for sym in symbols:
        oq = sorted(db["order_queue"].find(
            {"symbol": sym, "queued_at": {"$gte": since_iso}}),
            key=lambda r: str(r.get("queued_at") or ""))
        fills = sorted(db["ib_executions"].find(
            {"symbol": sym, "time": {"$gte": since_iso}}),
            key=lambda r: str(r.get("time") or ""))
        bts = sorted(db["bot_trades"].find(
            {"symbol": sym, "$or": [{"created_at": {"$gte": since_iso}},
                                    {"executed_at": {"$gte": since_iso}}]}),
            key=lambda r: str(r.get("created_at") or ""))

        print(f"\n{'─'*100}\n■ {sym}")

        print("  order_queue (bot intents):")
        if not oq:
            print("    (none — bot submitted NO order for this symbol in window)")
        for o in oq:
            print(f"    {_t(_dt(o.get('queued_at'))):<15} action={str(o.get('action')):<6} "
                  f"qty={str(o.get('quantity')):<6} type={str(o.get('order_type')):<8} "
                  f"status={str(o.get('status')):<10} order_id={o.get('order_id')} "
                  f"trade_id={str(o.get('trade_id'))[:12]} "
                  f"{('reason='+str(o.get('refusal_reason') or o.get('error') or '')[:40]) if (o.get('refusal_reason') or o.get('error')) else ''}")

        print("  ib_executions (real fills):")
        if not fills:
            print("    (none — NO broker fill on the tape in window)")
        for e in fills:
            print(f"    {_t(_dt(e.get('time'))):<15} side={_norm_side(e.get('side')):<4} "
                  f"shares={str(e.get('shares')):<6} price={e.get('price')} "
                  f"order_id={e.get('order_id')} perm_id={e.get('perm_id')}")

        print("  bot_trades (tracked):")
        for t in bts:
            ec = t.get("entry_context") or {}
            print(f"    {_t(_dt(t.get('created_at'))):<15} dir={str(t.get('direction')):<6} "
                  f"status={str(t.get('status')):<8} entered_by={str(t.get('entered_by')):<20} "
                  f"syn={t.get('synthetic_source') or '—'} recon={bool(ec.get('reconciled'))} "
                  f"close={str(t.get('close_reason') or '')[:18]}")

        # ---- verdict reconstruction ----
        # order_queue is TTL-pruned, so the PRIMARY bot-path signal is the
        # bot_trades tape (entered_by) + the ib_executions order_id sequence,
        # NOT order_queue presence.
        oq_order_ids = {o.get("order_id") for o in oq if o.get("order_id")}
        fill_order_ids = {e.get("order_id") for e in fills if e.get("order_id")}
        cancelled_oq = [o for o in oq if str(o.get("status") or "").lower() in CANCEL_STATES]
        shared_ids = oq_order_ids & fill_order_ids

        bot_path = any(str(t.get("entered_by") or "").lower() in {"bot_fired", "bot"}
                       for t in bts)
        broker_rejected = [t for t in bts if "broker_reject" in str(t.get("close_reason") or "").lower()]
        oca_closed = [t for t in bts
                      if str(t.get("status")) == "closed"
                      and "oca_closed_extern" in str(t.get("close_reason") or "").lower()]
        adopted = [t for t in bts
                   if str(t.get("status")) == "open"
                   and ((t.get("entry_context") or {}).get("reconciled")
                        or str(t.get("entered_by") or "").startswith("reconciled"))]

        if not fills:
            v = "NO_FILL_FOUND"
        elif oca_closed and adopted:
            v = "OCA_CLOSED_THEN_READOPTED (bot-path)"
        elif cancelled_oq and shared_ids:
            v = "CANCELLED_BUT_FILLED (NWSA-class)"
        elif bot_path and adopted:
            v = "BOT_PATH_THEN_READOPTED"
        elif bot_path and fills:
            v = "BOT_FILLED_THEN_LOST"
        elif fills and not bot_path:
            v = "EXTERNAL_OR_PRIOR_SESSION"
        else:
            v = "REVIEW"
        verdicts[sym] = v
        print(f"  ⮕ VERDICT: {v}")
        notes = []
        if broker_rejected:
            notes.append(f"{len(broker_rejected)} broker_rejected attempt(s) earlier today")
        if oca_closed:
            notes.append(f"{len(oca_closed)} oca_closed_externally close(s) right before adoption")
        if shared_ids:
            notes.append(f"order_id(s) on BOTH queue+fill: {sorted(shared_ids)}")
        if notes:
            print("     " + " | ".join(notes))

    print("\n" + "=" * 100)
    print("VERDICT SUMMARY")
    for s, v in verdicts.items():
        print(f"   {s:<8} {v}")
    print("\nREAD:")
    print("  OCA_CLOSED_THEN_READOPTED → bot-path: a bot_fired trade was marked closed via the")
    print("                         oca_closed_externally sweep while the IB position stayed OPEN, then")
    print("                         the reconciler re-adopted the live position as an 'external' orphan")
    print("                         with a synthetic 2%% stop + a misleading 'I did NOT open this' warning.")
    print("                         Root fix = don't mark closed while IB still holds the size, and/or")
    print("                         re-link the adoption to the just-closed bot_trade instead of synthesizing.")
    print("  CANCELLED_BUT_FILLED → the bot's cancel/reject lost the race to an IB fill (NWSA-class).")
    print("  BOT_FILLED_THEN_LOST → normal bot fill, tracking wiped by restart → re-adopted as orphan.")
    print("  EXTERNAL_OR_PRIOR    → NO bot_trade references the symbol → genuinely external / prior-session.")
    print("  (order_queue is TTL-pruned, so its absence does NOT mean the bot didn't trade the symbol —")
    print("   the bot_trades 'entered_by' tape is the authoritative bot-path signal.)")
    print("=" * 100)


if __name__ == "__main__":
    main()
