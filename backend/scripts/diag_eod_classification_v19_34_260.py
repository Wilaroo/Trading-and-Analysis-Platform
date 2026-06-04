"""
diag_eod_classification_v19_34_260.py
─────────────────────────────────────────────────────────────────────────────
EOD root-cause diagnostic for 2026-06-03.

The eod_auto_close event reported 19 closed / 0 failed but 16 IB positions
remained. On BOT_ORDER_PATH=direct, closes only succeed when IB confirms
filled + flat (v19.34.64), so the 16 are almost certainly positions the
v19.34.245 trade-style policy HELD overnight (close_at_eod=False).

This script replays the AUTHORITATIVE policy (should_close_at_eod) over every
trade that was open at / closed after the EOD window yesterday, so we can see
exactly which trades were held vs closed and WHY (trade_style / setup_type →
resolved style → close_at_eod).

Run from the backend dir so imports + .env resolve:
    cd ~/Trading-and-Analysis-Platform/backend
    python3 scripts/diag_eod_classification_v19_34_260.py 2026-06-03
"""
import os
import sys
from datetime import datetime, timezone

# Make backend modules importable when run from backend/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _load_env(path):
    """Minimal .env parser — no python-dotenv dependency."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


_load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from pymongo import MongoClient  # type: ignore
from services.order_policy_registry import should_close_at_eod, get_policy_for_trade  # type: ignore

DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-06-03"

mongo_url = os.environ["MONGO_URL"]
db_name = os.environ["DB_NAME"]
db = MongoClient(mongo_url)[db_name]

# All trades whose closed_at falls on DATE (ISO string match on the date prefix).
rows = list(
    db["bot_trades"].find(
        {"closed_at": {"$regex": f"^{DATE}"}},
        {
            "_id": 0, "symbol": 1, "setup_type": 1, "trade_style": 1,
            "close_reason": 1, "closed_at": 1, "close_at_eod": 1,
            "status": 1, "shares": 1,
        },
    )
)

print(f"\n=== Trades closed on {DATE}: {len(rows)} ===\n")
print(f"{'SYMBOL':<8}{'CLOSE_REASON':<24}{'TRADE_STYLE':<14}{'SETUP_TYPE':<22}"
      f"{'STORED_eod':<12}{'POLICY_close_at_eod':<20}{'RESOLVED_STYLE':<14}{'CLOSED_AT'}")
held_by_policy = []
eod_closed = []
manual_closed = []
mismatch = []

for r in sorted(rows, key=lambda x: (x.get("close_reason") or "", x.get("symbol") or "")):
    sym = r.get("symbol") or "?"
    reason = (r.get("close_reason") or "")[:22]
    style = r.get("trade_style") or "(none)"
    setup = (r.get("setup_type") or "(none)")[:20]
    stored = r.get("close_at_eod")
    policy_close = should_close_at_eod(r)
    resolved_style = get_policy_for_trade(r).style
    closed_at = r.get("closed_at") or ""
    print(f"{sym:<8}{reason:<24}{str(style):<14}{setup:<22}"
          f"{str(stored):<12}{str(policy_close):<20}{resolved_style:<14}{closed_at}")

    if "eod" in (r.get("close_reason") or "").lower():
        eod_closed.append(sym)
    elif (r.get("close_reason") or "").lower() in ("manual", "operator", "manual_close", "operator_close"):
        manual_closed.append(sym)

    # Was it HELD by policy (close_at_eod=False) but the operator closed it manually?
    if not policy_close and "eod" not in (r.get("close_reason") or "").lower():
        held_by_policy.append((sym, resolved_style, style, setup))

    # Did stored close_at_eod disagree with the policy?
    if stored is not None and bool(stored) != bool(policy_close):
        mismatch.append((sym, stored, policy_close, style, setup))

print(f"\n--- SUMMARY ---")
print(f"EOD-auto-closed (close_reason~eod): {len(eod_closed)}  {eod_closed}")
print(f"Manually closed by operator:        {len(manual_closed)}  {manual_closed}")
print(f"\nHELD overnight by policy (close_at_eod=False) but operator closed manually: {len(held_by_policy)}")
for sym, rstyle, style, setup in held_by_policy:
    print(f"   {sym:<8} resolved_style={rstyle:<12} trade_style={style!r:<14} setup_type={setup!r}")
print(f"\nStored close_at_eod DISAGREES with policy (the v245 fix target): {len(mismatch)}")
for sym, stored, policy_close, style, setup in mismatch:
    print(f"   {sym:<8} stored={stored} policy={policy_close} trade_style={style!r} setup_type={setup!r}")
print()
