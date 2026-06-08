#!/usr/bin/env python3
"""
diag_setup_x_regime.py  (READ-ONLY)
===================================
HYPOTHESIS (operator + SPY/QQQ charts): fade / counter-trend setups bleed because
the market has been a strong grind-up since April. Test it directly — every
bot_trade stores market_regime + regime_score AT TRADE TIME, so we can condition
each setup's clean expectancy on the regime it was taken in.

    clean_R = realized_pnl / risk_amount   (risk_amount>0, |R|<=10)
    regime_score bands:  BULL >60   |   NEUTRAL 46-60   |   BEARISH <=45

If fades are deeply negative in BULL but flat/positive in NEUTRAL/BEARISH, the fix
is regime-aware setup gating (suppress counter-trend setups in strong trends),
NOT disabling them outright.

Artifacts removed: reconciled_orphan, reconciled_excess_slice, imported_from_ib,
synthetic_source.

Writes NOTHING.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_setup_x_regime.py
"""
import os
import statistics
from collections import defaultdict

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def fnum(v):
    try:
        f = float(v)
        return f if f == f else None
    except Exception:
        return None


ARTIFACTS = {"reconciled_orphan", "reconciled_excess_slice", "imported_from_ib"}

# Heuristic setup categories (counter-trend vs with-trend) for the rollup.
FADE = {"vwap_fade_short", "vwap_fade_long", "vwap_bounce", "mean_reversion_short",
        "mean_reversion_long", "fading_bounce", "bouncy_ball", "rubber_band",
        "rubber_band_short", "backside", "off_sides_short", "gap_fade", "big_dog"}
TREND = {"daily_breakout", "accumulation_entry", "breakout", "breakout_confirmed",
         "power_trend_stack", "stage_2_breakout", "rs_leader_break", "orb",
         "trend_continuation_short", "hod_breakout", "premarket_high_break",
         "pocket_pivot", "three_week_tight", "gap_give_go", "puppy_dog",
         "approaching_breakout"}


def band(score):
    if score is None:
        return None
    if score > 60:
        return "BULL>60"
    if score >= 46:
        return "NEUT46-60"
    return "BEAR<=45"


rows = list(db.bot_trades.find(
    {"status": "closed"},
    {"_id": 0, "realized_pnl": 1, "risk_amount": 1, "setup_type": 1,
     "synthetic_source": 1, "regime_score": 1, "market_regime": 1},
))

per = defaultdict(lambda: defaultdict(list))   # setup -> band -> [R]
cat = defaultdict(lambda: defaultdict(list))   # category -> band -> [R]
regime_str = defaultdict(lambda: defaultdict(list))  # category -> market_regime -> [R]
n_no_score = 0

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
    sc = fnum(r.get("regime_score"))
    b = band(sc)
    if b is None:
        n_no_score += 1
    else:
        per[st][b].append(cr)
        c = "FADE" if st in FADE else ("TREND" if st in TREND else "OTHER")
        cat[c][b].append(cr)
    mr = r.get("market_regime")
    if mr:
        c = "FADE" if st in FADE else ("TREND" if st in TREND else "OTHER")
        regime_str[c][str(mr)].append(cr)


def cell(lst):
    if not lst:
        return f"{'-':>14}"
    return f"n={len(lst):<4} {statistics.mean(lst):+.3f}".rjust(14)


print("=" * 88)
print("CATEGORY × REGIME_SCORE BAND  (clean mean R)")
print(f"(trades without regime_score: {n_no_score})")
print("=" * 88)
print(f"\n{'category':<10}{'BEAR<=45':>16}{'NEUT46-60':>16}{'BULL>60':>16}")
print("-" * 60)
for c in ("FADE", "TREND", "OTHER"):
    print(f"{c:<10}{cell(cat[c]['BEAR<=45']):>16}{cell(cat[c]['NEUT46-60']):>16}{cell(cat[c]['BULL>60']):>16}")

print("\n" + "=" * 88)
print("CATEGORY × market_regime STRING  (clean mean R)")
print("=" * 88)
all_regimes = sorted({rg for c in regime_str for rg in regime_str[c]})
for c in ("FADE", "TREND", "OTHER"):
    print(f"\n{c}:")
    for rg in all_regimes:
        lst = regime_str[c].get(rg, [])
        if lst:
            print(f"   {rg:<22} n={len(lst):<4} meanR={statistics.mean(lst):+.3f}")

print("\n" + "=" * 88)
print("PER-SETUP × REGIME_SCORE BAND (setups with n>=20 total)")
print("=" * 88)
print(f"\n{'setup':<22}{'BEAR<=45':>16}{'NEUT46-60':>16}{'BULL>60':>16}")
print("-" * 72)
for st in sorted(per.keys(), key=lambda s: sum(len(v) for v in per[s].values()), reverse=True):
    tot = sum(len(v) for v in per[st].values())
    if tot < 20:
        continue
    tag = "F" if st in FADE else ("T" if st in TREND else " ")
    print(f"{tag} {st:<20}{cell(per[st]['BEAR<=45']):>16}{cell(per[st]['NEUT46-60']):>16}{cell(per[st]['BULL>60']):>16}")

print("\n" + "=" * 88)
print("READ: if FADE row is sharply negative under BULL>60 but ~flat/positive under")
print("BEAR/NEUT, regime-aware gating (suppress fades in strong uptrends) is confirmed.")
print("\nDONE — paste this whole block back.")
