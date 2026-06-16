#!/usr/bin/env python3
"""
v320t — CORRECTIVE RE-STAMP for open positions mislabeled CARRY but natively
SCALP/INTRADAY (the pre-v320p A+→multi_day hijack class: gap_fade, squeeze, ...).

For each status=open bot_trades row whose SSOT natural style (setup_taxonomy.
style_of) is scalp/intraday but whose STAMPED trade_style is a carry bucket
(multi_day/swing/position/investment), this re-stamps trade_style to the natural
value and sets close_at_eod=True so the order-policy EOD flatten
(should_close_at_eod -> get_policy_for_trade) closes them at today's EOD instead
of carrying overnight.

SAFETY
------
• DRY-RUN by default. Mutates ONLY trade_style + close_at_eod on the matched rows.
• Re-derives the mislabel verdict LIVE per row (won't touch anything that no longer
  matches). Optional --allow SYM,SYM restricts to an explicit allowlist.
• Writes a full before/after audit to bot_trades_restyle_audit_v320t. --rollback
  restores from it.
• Does NOT cancel/modify any IB order. Re-stamping an OPEN trade does NOT strip its
  GTC bracket: the EOD intraday sweep skips status=open rows and only targets
  pending DAY *entry* orders (orphan_gtc_reconciler L436), and bracket legs that
  match an open bot_trade are not orphans.

CLOBBER-RACE: the live bot persists in-memory trade_style back to Mongo, so you
MUST restart immediately after --apply so restore reads the new value into memory:
    .venv/bin/python backend/scripts/patch_v320t_restyle_open.py --apply && ./start_backend.sh --force
Then re-run diag_v320s to CONFIRM the rows now read intraday/scalp (if a persist
clobbered the write in the gap, v320s will still show multi_day -> just re-run).

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/patch_v320t_restyle_open.py            # dry-run
  .venv/bin/python backend/scripts/patch_v320t_restyle_open.py --apply    # write
  .venv/bin/python backend/scripts/patch_v320t_restyle_open.py --rollback # undo
  optional: --allow DKNG,XOM,CVX,COP,DVN
"""
import sys
from datetime import datetime, timezone

from pymongo import MongoClient

sys.path.insert(0, "backend")
try:
    from services.setup_taxonomy import style_of
except Exception:  # pragma: no cover
    from backend.services.setup_taxonomy import style_of

INTRADAY = {"scalp", "intraday"}
CARRY = {"multi_day", "swing", "position", "investment"}
ADOPTED = ("reconciled", "imported_from_ib", "adopted", "orphan")
AUDIT = "bot_trades_restyle_audit_v320t"


def _db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def _targets(db, allow):
    out = []
    for t in db.bot_trades.find({"status": "open"}, {"_id": 0}):
        sym = t.get("symbol", "?")
        stamped = (t.get("trade_style") or "").strip().lower()
        setup = (t.get("setup_type") or "").strip().lower()
        eb = (t.get("entered_by") or "").lower()
        if any(m in eb for m in ADOPTED) or any(m in setup for m in ADOPTED):
            continue
        try:
            nat = style_of(setup) or "unknown"
        except Exception:
            nat = "unknown"
        if nat in INTRADAY and stamped in CARRY:
            if allow and sym.upper() not in allow:
                print(f"  (skip {sym}: mislabeled but not in --allow list)")
                continue
            out.append((t.get("id"), sym, stamped, setup, nat,
                        bool(t.get("close_at_eod"))))
    return out


def main():
    mode = "apply" if "--apply" in sys.argv else ("rollback" if "--rollback" in sys.argv else "dry")
    allow = None
    if _arg("--allow"):
        allow = {s.strip().upper() for s in _arg("--allow").split(",") if s.strip()}
    db = _db()

    if mode == "rollback":
        docs = list(db[AUDIT].find({"rolled_back": {"$ne": True}}, {"_id": 1}))
        print(f"=== v320t ROLLBACK — {len(docs)} audited change(s) ===")
        n = 0
        for d in db[AUDIT].find({"rolled_back": {"$ne": True}}):
            before = d["before"]
            r = db.bot_trades.update_one(
                {"id": d["trade_id"], "status": "open"},
                {"$set": {"trade_style": before["trade_style"],
                          "close_at_eod": before["close_at_eod"]}},
            )
            db[AUDIT].update_one({"_id": d["_id"]}, {"$set": {"rolled_back": True}})
            print(f"  {d['symbol']:<6} -> trade_style={before['trade_style']} "
                  f"(matched={r.matched_count})")
            n += 1
        print(f"restored {n}. RESTART to reload memory: ./start_backend.sh --force")
        return

    targets = _targets(db, allow)
    print(f"\n=== v320t RE-STAMP {'(APPLY)' if mode=='apply' else '(DRY-RUN)'} — "
          f"{len(targets)} mislabeled CARRY->INTRADAY ===\n")
    if not targets:
        print("  nothing to do (no open carry-labeled rows resolve to scalp/intraday).")
        return
    for tid, sym, stamped, setup, nat, cae in targets:
        print(f"  {sym:<6} id={tid:<10} {setup:<22} "
              f"trade_style: {stamped} -> {nat}   close_at_eod: {cae} -> True")

    if mode == "dry":
        print("\nDRY-RUN. Re-run with --apply (then IMMEDIATELY ./start_backend.sh --force).")
        return

    now = datetime.now(timezone.utc).isoformat()
    applied = 0
    for tid, sym, stamped, setup, nat, cae in targets:
        db[AUDIT].insert_one({
            "trade_id": tid, "symbol": sym, "setup_type": setup,
            "before": {"trade_style": stamped, "close_at_eod": cae},
            "after": {"trade_style": nat, "close_at_eod": True},
            "applied_at": now, "patch": "v320t", "rolled_back": False,
        })
        r = db.bot_trades.update_one(
            {"id": tid, "status": "open"},
            {"$set": {"trade_style": nat, "close_at_eod": True}},
        )
        print(f"  ✓ {sym:<6} trade_style->{nat} (matched={r.matched_count}, mod={r.modified_count})")
        applied += 1
    print(f"\nAPPLIED {applied}. Audit -> {AUDIT}.")
    print(">>> RESTART NOW so restore loads the new style into memory:")
    print("    ./start_backend.sh --force")
    print(">>> Then CONFIRM: .venv/bin/python backend/scripts/diag_v320s_open_position_style_audit.py")


if __name__ == "__main__":
    main()
