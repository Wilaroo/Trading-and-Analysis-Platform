#!/usr/bin/env python3
"""
audit_brackets.py  --  v19.34.30 Open-Position Bracket Audit
=============================================================
Read-only safety check against `tradecommand.bot_trades`.

Flags every open trade where ANY of the following is true:
  • len(target_order_ids) > 1               -> stacked target legs
  • stop_order_id is falsy                  -> naked (no stop)
  • duplicate `id` rows in DB               -> duplicate canonical row
  • symbol appears in multiple open rows    -> same-symbol bot duplicates
  • DB quantity != IB-reported size         -> share drift (optional)

Run:
    cd ~/Trading-and-Analysis-Platform
    python3 scripts/audit_brackets.py

Exit code 0 = clean book.  Exit code 1 = at least one anomaly found.
"""

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

try:
    from pymongo import MongoClient
except ImportError:
    print("[!] pymongo not installed in this venv. Activate the backend venv and retry.")
    sys.exit(2)

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME   = os.environ.get("DB_NAME",   "tradecommand")

TARGET_LEG_THRESHOLD = 1       # flag if len(target_order_ids) > this

# Optional: live IB position map for drift check.
# Set USE_IB_DRIFT=1 and have the pusher reachable to enable.
USE_IB_DRIFT = os.environ.get("USE_IB_DRIFT", "0") == "1"
PUSHER_URL   = os.environ.get("IB_PUSHER_URL", "http://localhost:8200")

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def fmt_age(created_at):
    if not created_at:
        return "?"
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            return "?"
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    delta = now - created_at
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m = rem // 60
    return f"{h:>3}h{m:02d}m"


def fetch_ib_positions():
    """Hit the pusher snapshot endpoint; return {symbol: signed_qty}."""
    try:
        import urllib.request, json
        with urllib.request.urlopen(f"{PUSHER_URL}/positions", timeout=4) as r:
            data = json.loads(r.read().decode())
        # Pusher returns either a list[{symbol, position}] or a dict.
        positions = {}
        if isinstance(data, list):
            for row in data:
                positions[row.get("symbol", "").upper()] = float(row.get("position", 0) or 0)
        elif isinstance(data, dict):
            for sym, qty in data.items():
                positions[str(sym).upper()] = float(qty or 0)
        return positions
    except Exception as e:
        print(f"[!] IB drift check disabled (pusher unreachable: {e})")
        return None


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=4000)
    db = client[DB_NAME]
    coll = db["bot_trades"]

    open_trades = list(coll.find(
        {"status": "open"},
        {
            "_id": 0,
            "id": 1,
            "symbol": 1,
            "side": 1,
            "quantity": 1,
            "entry_price": 1,
            "stop_order_id": 1,
            "target_order_ids": 1,
            "oca_group": 1,
            "entered_by": 1,
            "created_at": 1,
            "parent_order_id": 1,
        },
    ))

    total = len(open_trades)
    print("=" * 100)
    print(f"  SentCom Bracket Audit  --  {DB_NAME}.bot_trades  --  status=open")
    print(f"  {total} open trade rows  |  ts={datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print("=" * 100)

    ib_positions = fetch_ib_positions() if USE_IB_DRIFT else None

    # ---- duplicates & symbol collisions ----------------------------------- #
    id_counter      = Counter(t.get("id") for t in open_trades)
    symbol_counter  = Counter(t.get("symbol", "").upper() for t in open_trades)
    db_qty_by_sym   = defaultdict(float)
    for t in open_trades:
        sign = 1 if (t.get("side") or "").lower() in ("buy", "long") else -1
        db_qty_by_sym[t.get("symbol", "").upper()] += sign * float(t.get("quantity") or 0)

    dup_ids       = {k for k, v in id_counter.items() if v > 1}
    dup_symbols   = {k for k, v in symbol_counter.items() if v > 1}

    # ---- per-row flagging -------------------------------------------------- #
    header = f"{'SYMBOL':<7} {'SIDE':<5} {'QTY':>7}  {'TGTS':>4}  {'STOP':<8}  {'AGE':>8}  ENTERED_BY                     FLAGS"
    print(header)
    print("-" * len(header))

    flagged_rows = 0
    for t in sorted(open_trades, key=lambda x: (x.get("symbol", ""), x.get("created_at") or "")):
        sym   = (t.get("symbol") or "?").upper()
        side  = (t.get("side") or "?")[:4]
        qty   = float(t.get("quantity") or 0)
        tgts  = list(t.get("target_order_ids") or [])
        stop  = t.get("stop_order_id")
        ent   = (t.get("entered_by") or "?")[:30]
        age   = fmt_age(t.get("created_at"))

        flags = []
        if len(tgts) > TARGET_LEG_THRESHOLD:
            flags.append(f"STACKED_TGTS({len(tgts)})")
        if not stop:
            flags.append("NAKED_NO_STOP")
        if t.get("id") in dup_ids:
            flags.append("DUP_ID")
        if sym in dup_symbols:
            flags.append("DUP_SYMBOL")

        if ib_positions is not None:
            ib_qty = ib_positions.get(sym, 0.0)
            # Compare aggregated DB signed qty vs IB once per symbol; only print on first row of symbol.
            if abs(ib_qty - db_qty_by_sym[sym]) > 0.5:
                flags.append(f"DRIFT(db={db_qty_by_sym[sym]:+.0f} ib={ib_qty:+.0f})")

        if flags:
            flagged_rows += 1
            flag_str = " ".join(flags)
        else:
            flag_str = "ok"

        print(
            f"{sym:<7} {side:<5} {qty:>7.0f}  {len(tgts):>4}  "
            f"{(stop or '-'):<8}  {age:>8}  {ent:<30} {flag_str}"
        )

    # ---- per-symbol qty rollup ------------------------------------------- #
    print("-" * len(header))
    print("Per-symbol DB qty rollup (sign-aware):")
    for sym, q in sorted(db_qty_by_sym.items()):
        ib_str = ""
        if ib_positions is not None:
            ib_q = ib_positions.get(sym, 0.0)
            delta = ib_q - q
            ib_str = f"  | IB={ib_q:+.0f}  Δ={delta:+.0f}"
        print(f"   {sym:<7} db={q:+.0f}{ib_str}")

    # ---- summary ---------------------------------------------------------- #
    print("=" * 100)
    print(f"  Open rows : {total}")
    print(f"  Flagged   : {flagged_rows}")
    print(f"  Dup IDs   : {len(dup_ids)}  ->  {sorted(dup_ids)[:5]}{'...' if len(dup_ids)>5 else ''}")
    print(f"  Dup syms  : {len(dup_symbols)}  ->  {sorted(dup_symbols)[:5]}{'...' if len(dup_symbols)>5 else ''}")
    print("=" * 100)

    if flagged_rows == 0 and not dup_ids and not dup_symbols:
        print("  ✅ Clean book.")
        return 0
    print("  ⚠️  Anomalies above. Cross-check TWS BEFORE we patch.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
