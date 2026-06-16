#!/usr/bin/env python3
"""
v320s — OPEN-POSITION STYLE AUDIT (READ-ONLY): which open trades are mislabeled?

For every status=open bot_trades row, resolves the setup's NATURAL trade-style
from the SSOT (`setup_taxonomy.style_of` -> trade_style_classifier) and compares
it to the STAMPED trade_style. Flags:
  • MISLABELED_CARRY  — stamped multi_day/swing/position/investment but the setup
                        is natively scalp/intraday  (← the A+→multi_day hijack class;
                        these are carrying overnight when they should flatten at EOD)
  • MISLABELED_INTRA  — stamped scalp/intraday but the setup is natively a carry
  • OK / ADOPTED(skip) / UNKNOWN
Also shows smb_is_a_plus (the v320p hijack trigger) + whether the row would close
at EOD, so you can decide whether to re-stamp + EOD-flatten the mislabeled carries.

NOTHING is written.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v320s_open_position_style_audit.py
"""
import sys
from collections import Counter

from pymongo import MongoClient

sys.path.insert(0, "backend")
try:
    from services.setup_taxonomy import style_of, canonicalize
except Exception:  # pragma: no cover
    from backend.services.setup_taxonomy import style_of, canonicalize

INTRADAY = {"scalp", "intraday"}
CARRY = {"multi_day", "swing", "position", "investment"}
ADOPTED_MARKERS = ("reconciled", "imported_from_ib", "adopted", "orphan")


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _natural(setup_type):
    try:
        return style_of(setup_type) or "unknown"
    except Exception:
        return "unknown"


def main():
    db = _load_db()
    opens = list(db.bot_trades.find({"status": "open"}, {"_id": 0}))
    print(f"\n=== v320s OPEN-POSITION STYLE AUDIT — {len(opens)} open ===\n")

    rows = []
    verdict_ct = Counter()
    for t in opens:
        sym = t.get("symbol", "?")
        stamped = (t.get("trade_style") or "?").strip().lower()
        setup = (t.get("setup_type") or "?").strip().lower()
        eb = (t.get("entered_by") or "").lower()
        aplus = bool(t.get("smb_is_a_plus"))
        nat = _natural(setup)

        if any(m in eb for m in ADOPTED_MARKERS) or any(m in setup for m in ADOPTED_MARKERS):
            verdict = "ADOPTED(skip)"
        elif nat == "unknown":
            verdict = "UNKNOWN"
        elif nat in INTRADAY and stamped in CARRY:
            verdict = "MISLABELED_CARRY→INTRADAY"
        elif nat in CARRY and stamped in INTRADAY:
            verdict = "MISLABELED_INTRA→CARRY"
        elif nat == stamped:
            verdict = "OK"
        else:
            verdict = f"OK~ (nat={nat})"
        verdict_ct[verdict.split(" ")[0]] += 1
        rows.append((sym, stamped, setup, canonicalize(setup), nat, aplus, verdict))

    # mislabeled carries first (the user's target)
    order = {"MISLABELED_CARRY→INTRADAY": 0, "MISLABELED_INTRA→CARRY": 1,
             "UNKNOWN": 2, "ADOPTED(skip)": 4}
    rows.sort(key=lambda r: order.get(r[6], 3))

    print(f"  {'SYM':<6} {'STAMPED':<11} {'SETUP':<26} {'NATURAL':<10} {'A+':<3} VERDICT")
    for sym, stamped, setup, canon, nat, aplus, verdict in rows:
        flag = "★" if verdict.startswith("MISLABELED_CARRY") else " "
        print(f"{flag} {sym:<6} {stamped:<11} {setup:<26} {nat:<10} "
              f"{'Y' if aplus else '·':<3} {verdict}")

    print("\nSUMMARY:")
    for v, n in verdict_ct.most_common():
        print(f"  {v:<26} {n}")

    mis = [r for r in rows if r[6].startswith("MISLABELED_CARRY")]
    print(f"\n★ {len(mis)} open position(s) labeled CARRY but natively SCALP/INTRADAY:")
    for sym, stamped, setup, canon, nat, aplus, _v in mis:
        print(f"    {sym:<6} stamped={stamped:<10} setup={setup:<22} should_be={nat}"
              + ("   (smb_A+ hijack)" if aplus else ""))
    print("\nThese are the A+→multi_day hijack class (gap_fade/squeeze/etc.) stamped")
    print("BEFORE v320p. v320p prevents NEW ones; these existing rows keep the old")
    print("label + overnight-carry behavior until re-stamped. Decide: leave, or")
    print("re-stamp trade_style + set close_at_eod so they flatten at today's EOD.\n")


if __name__ == "__main__":
    main()
