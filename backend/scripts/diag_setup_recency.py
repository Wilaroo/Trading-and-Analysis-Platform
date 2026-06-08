#!/usr/bin/env python3
"""
diag_setup_recency.py  (READ-ONLY)
==================================
Your caveat: the early closed trades were on a larger-size account, oversized /
orphaned / overnight / pre-pipeline noise. So a setup's lifetime mean-R may be
dragged down by legacy junk even if it trades fine NOW.

This splits each setup's REAL closed trades into time segments and compares
expectancy, so we can tell "legacy bleed" from "still bleeding today":

    clean_R = realized_pnl / risk_amount   (risk_amount>0, |R|<=10)
    segments: LAST 30d  |  31-90d  |  OLDER than 90d

Artifacts removed: reconciled_orphan, reconciled_excess_slice, synthetic_source,
imported_from_ib.

Highlights setups whose RECENT (last 30d, n>=6) mean_R < -0.10 — the ones worth
acting on now — vs those that only bled in the legacy period.

Writes NOTHING.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_setup_recency.py
"""
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc)


def fnum(v):
    try:
        f = float(v)
        return f if f == f else None
    except Exception:
        return None


def parse_dt(v):
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


ARTIFACTS = {"reconciled_orphan", "reconciled_excess_slice", "imported_from_ib"}

rows = list(db.bot_trades.find(
    {"status": "closed"},
    {"_id": 0, "realized_pnl": 1, "risk_amount": 1, "setup_type": 1,
     "synthetic_source": 1, "closed_at": 1, "created_at": 1},
))

# segment buckets per setup
per = defaultdict(lambda: {"30": [], "90": [], "old": [], "30pnl": 0.0, "90pnl": 0.0, "oldpnl": 0.0})
no_date = 0
for r in rows:
    st = str(r.get("setup_type", "?"))
    if st in ARTIFACTS or r.get("synthetic_source"):
        continue
    pnl = fnum(r.get("realized_pnl"))
    ra = fnum(r.get("risk_amount"))
    if pnl is None or not ra or ra <= 0:
        continue
    cr = pnl / ra
    if not (-10 <= cr <= 10):
        continue
    dt = parse_dt(r.get("closed_at")) or parse_dt(r.get("created_at"))
    if dt is None:
        no_date += 1
        continue
    age = (now - dt).days
    d = per[st]
    if age <= 30:
        d["30"].append(cr); d["30pnl"] += pnl
    elif age <= 90:
        d["90"].append(cr); d["90pnl"] += pnl
    else:
        d["old"].append(cr); d["oldpnl"] += pnl


def m(lst):
    return statistics.mean(lst) if lst else None


print("=" * 92)
print("PER-SETUP EXPECTANCY BY RECENCY (real strategy trades, clean R)")
print(f"(rows without parseable date skipped: {no_date})")
print("=" * 92)
print(f"\n{'setup':<22}{'LAST30d':>20}{'31-90d':>18}{'>90d (legacy)':>20}")
print(f"{'':<22}{'n  meanR':>20}{'n  meanR':>18}{'n  meanR':>20}")
print("-" * 92)

still_bleeding = []
healed = []
for st, d in sorted(per.items(), key=lambda kv: (m(kv[1]['30']) if kv[1]['30'] else 0)):
    n30, n90, nold = len(d["30"]), len(d["90"]), len(d["old"])
    if n30 + n90 + nold == 0:
        continue
    r30, r90, rold = m(d["30"]), m(d["90"]), m(d["old"])

    def cell(n, r):
        return f"{n:>3} {('%+.3f' % r) if r is not None else '  -   ':>7}"
    print(f"{st:<22}{cell(n30, r30):>20}{cell(n90, r90):>18}{cell(nold, rold):>20}")

    if n30 >= 6 and r30 is not None and r30 < -0.10:
        still_bleeding.append((st, n30, r30, d["30pnl"]))
    # healed: bad legacy but fine recently
    if (nold >= 10 and rold is not None and rold < -0.10
            and n30 >= 6 and r30 is not None and r30 >= -0.05):
        healed.append((st, n30, r30, nold, rold))

print("\n" + "=" * 92)
print("🔴 STILL BLEEDING in last 30d (n>=6, meanR<-0.10) — act on these NOW:")
if still_bleeding:
    for st, n, r, pnl in sorted(still_bleeding, key=lambda x: x[2]):
        print(f"   {st:<22} last30d: n={n:>3} meanR={r:+.3f} pnl=${pnl:,.0f}")
else:
    print("   (none — recent expectancy is not clearly negative for any setup)")

print("\n🟩 HEALED (bad >90d ago, fine in last 30d) — legacy noise, do NOT disable:")
if healed:
    for st, n30, r30, nold, rold in healed:
        print(f"   {st:<22} legacy n={nold} meanR={rold:+.3f}  →  last30d n={n30} meanR={r30:+.3f}")
else:
    print("   (none clearly fit this pattern)")

# Recent portfolio expectancy
all30 = [x for d in per.values() for x in d["30"]]
all_old = [x for d in per.values() for x in d["old"]]
print("\n" + "=" * 92)
if all30:
    print(f"PORTFOLIO last 30d : n={len(all30)}  meanR={statistics.mean(all30):+.3f}  "
          f"median={statistics.median(all30):+.3f}")
if all_old:
    print(f"PORTFOLIO >90d ago : n={len(all_old)}  meanR={statistics.mean(all_old):+.3f}  "
          f"median={statistics.median(all_old):+.3f}")
print("  (if last-30d mean is much better than >90d, the pipeline fixes are working)")
print("\nDONE — paste this whole block back.")
