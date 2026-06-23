#!/usr/bin/env python3
"""
diag_oca_close_transient_vs_reentry.py — READ-ONLY. Decides which orphan fix
the FOXA/KR/LULU class needs (B-d), by reconstructing the running NET IB
position from the fill tape across each oca_closed_externally close mark.

For every recent bot_trade closed with reason `oca_closed_externally`, it pulls
the FULL ib_executions fill tape for that symbol, computes the running signed
position (BUY +shares, SELL −shares), and asks: at the moment the v19.31 sweep
marked the trade CLOSED (because it saw "IB = 0 shares both directions"), was
the position ACTUALLY flat?

  TRANSIENT_SNAPSHOT_GAP  → the fills show the position was NEVER 0 across the
        close mark (no opposite/cover fill flattened it). The sweep acted on a
        bad/transient IB snapshot → favors ROOT FIX (b: debounce the close,
        require 2 consecutive 0-share reads).
  REAL_FLAT_THEN_REENTRY  → a cover fill took net to 0 at/near the mark, then a
        NEW same-side fill re-opened it → favors SYMPTOM FIX (a: reconciler
        re-link, since it really is a fresh untracked position).
  INCOMPLETE_TAPE         → running net at 'now' doesn't reconcile to the known
        current orphan size → fill history is windowed/partial; widen --days.

NOTHING IS WRITTEN.

USAGE (repo root, DGX):
  .venv/bin/python backend/scripts/diag_oca_close_transient_vs_reentry.py
  .venv/bin/python backend/scripts/diag_oca_close_transient_vs_reentry.py --hours 48 --days 21
"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

NEAR_MARK_S = 120  # ± window to look for a cover fill around the close mark


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


def _signed(e):
    s = str(e.get("side") or "").upper()
    sh = float(e.get("shares") or 0)
    return sh if s.startswith("B") else -sh


def main():
    _load_env()
    hours, days = 36, 14
    if "--hours" in sys.argv:
        try:
            hours = int(sys.argv[sys.argv.index("--hours") + 1])
        except Exception:
            pass
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception:
            pass

    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"],
                     serverSelectionTimeoutMS=20000)[os.environ["DB_NAME"]]
    close_since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    tape_since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    closes = list(db["bot_trades"].find({
        "close_reason": {"$regex": "oca_closed_extern", "$options": "i"},
        "$or": [{"closed_at": {"$gte": close_since}},
                {"created_at": {"$gte": close_since}}],
    }))

    print("=" * 100)
    print(f"OCA-CLOSE: TRANSIENT vs RE-ENTRY  (READ-ONLY)  now={datetime.now(timezone.utc).isoformat()[:19]}Z"
          f"  close_window={hours}h  tape={days}d")
    print(f"  oca_closed_externally trades in window: {len(closes)}")
    print("=" * 100)

    # current open orphan sizes (signed), for tape-completeness reconciliation
    orphan_net = {}
    for t in db["bot_trades"].find({"status": "open"}):
        ec = t.get("entry_context") or {}
        if ec.get("reconciled") or str(t.get("entered_by") or "").startswith("reconciled"):
            sym = str(t.get("symbol") or "").upper()
            sh = float(t.get("remaining_shares") or t.get("shares") or 0)
            d = str(t.get("direction") or "").lower()
            orphan_net[sym] = orphan_net.get(sym, 0.0) + (sh if d.startswith("l") else -sh)

    verdicts = Counter()
    syms = sorted({str(c.get("symbol") or "").upper() for c in closes})
    for sym in syms:
        tape = sorted(db["ib_executions"].find(
            {"symbol": sym, "time": {"$gte": tape_since}}),
            key=lambda e: str(e.get("time") or ""))
        sym_closes = [c for c in closes if str(c.get("symbol") or "").upper() == sym]

        print(f"\n{'─'*100}\n■ {sym}   (fills in tape: {len(tape)})")
        # running net at end of tape
        run = 0.0
        rows = []
        for e in tape:
            run += _signed(e)
            rows.append((_dt(e.get("time")), _signed(e), run, e))
        end_net = run
        known = orphan_net.get(sym)
        complete = (known is None) or (abs(end_net - known) < 1e-6)
        print(f"  tape end net position: {end_net:+.0f}   current orphan net: "
              f"{'n/a' if known is None else f'{known:+.0f}'}   "
              f"tape_complete={'YES' if complete else 'NO (widen --days)'}")
        # print tape compactly
        for ts, sg, rn, e in rows[-12:]:
            print(f"    {_t(ts):<15} {('BUY ' if sg>0 else 'SELL'):<4} {abs(sg):>6.0f}  "
                  f"net={rn:+.0f}  order_id={e.get('order_id')}")

        for c in sym_closes:
            mark = _dt(c.get("closed_at")) or _dt(c.get("created_at"))
            direction = str(c.get("direction") or "").lower()
            # net just before and after the mark
            net_before = sum(_signed(e) for ts, sg, rn, e in
                             [(r[0], r[1], r[2], r[3]) for r in rows] if ts and ts <= mark) if mark else None
            # cover fill near the mark? (opposite side of the tracked direction)
            cover = []
            for ts, sg, rn, e in rows:
                if not (ts and mark):
                    continue
                if abs((ts - mark).total_seconds()) <= NEAR_MARK_S:
                    is_cover = (sg > 0) if direction.startswith("s") else (sg < 0)
                    if is_cover:
                        cover.append((ts, sg))
            flat_at_mark = (net_before is not None and abs(net_before) < 1e-6)

            if not complete:
                v = "INCOMPLETE_TAPE"
            elif flat_at_mark or cover:
                v = "REAL_FLAT_THEN_REENTRY"
            else:
                v = "TRANSIENT_SNAPSHOT_GAP"
            verdicts[v] += 1
            print(f"  close mark {_t(mark)} dir={direction or '?'}  "
                  f"net_at_mark={'?' if net_before is None else f'{net_before:+.0f}'}  "
                  f"cover_fills_near_mark={len(cover)}  ⮕ {v}")

    print("\n" + "=" * 100)
    print("VERDICT TALLY")
    for k, v in verdicts.most_common():
        print(f"   {k:<26} {v}")
    print("\nDECISION:")
    print("  mostly TRANSIENT_SNAPSHOT_GAP → ROOT FIX (b): debounce the v19.31 OCA sweep —")
    print("                                  require 2 consecutive 0-share reads before closing.")
    print("  mostly REAL_FLAT_THEN_REENTRY → SYMPTOM FIX (a): reconciler re-link to the just-")
    print("                                  closed bot_trade instead of synthesizing an orphan.")
    print("  INCOMPLETE_TAPE               → re-run with a larger --days so the fill tape spans")
    print("                                  the original entry; verdict is unreliable until complete.")
    print("=" * 100)


if __name__ == "__main__":
    main()
