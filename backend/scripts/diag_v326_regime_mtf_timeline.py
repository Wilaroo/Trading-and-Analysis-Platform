#!/usr/bin/env python3
"""
v326 — REGIME / MULTI-TF CONTEXT TIMELINE (READ-ONLY)

WHY THIS SUPERSEDES v325:
  v324 proved the FIRE funnel's TOP gate is a 100%-CAUTIOUS posture
  (regime_state=HOLD, composite_score pinned 68 → GO bar 50 + regime_suppression).
  BUT a code read shows the mode is NOT decided by composite_score: when SPY's
  multi_tf is present, `_update_trading_mode` PREFERS multi_tf.context over the
  legacy 68→NORMAL map (confidence_gate.py L2090-2104). And a MIXED context maps
  BOTH long & short to 'cautious' (multi_tf_regime.py L200-201).

  v325 read confidence_gate_log, which stores regime_score + trading_mode but NOT
  the multi_tf CONTEXT or the per-lane scores — so it cannot tell us WHY the mode
  is cautious. This diag reads `market_regime_state` (one upserted doc/day, which
  DOES persist the whole multi_tf block) so we can see, day by day:
    composite_score, state, multi_tf.context, long-anchor lane score+bias,
    blended intraday score+bias, mid/short/micro lane bias, and the per-direction
    modes — then attribute WHICH lane forces MIXED.

READING THE RESULT:
  • MIXED dominant + the LONG-anchor lane stuck NEUTRAL (41-59) every day
      → the daily-anchor SMA score sits in the tolerance band; caution is the
        DEFAULT. If composite (68) says bullish but the anchor lane says NEUTRAL,
        that mismatch is the lever (anchor-lane calibration or the context map).
  • MIXED dominant because the INTRADAY lane is UNKNOWN/None (intraday SPY bars
      not backfilled) → classify_context falls back to anchor-only; if the anchor
      is NEUTRAL it returns MIXED. Lever = ensure SPY 1h/5m/1m bars are present.
  • context VARIES across days (ALIGNED_UP / PULLBACK / MIXED…) and lane scores
      move → caution is a legitimate real-time call; leave it, accept selectivity.
  • Few distinct composite/long scores + same context every single day → STUCK.

Usage (DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v326_regime_mtf_timeline.py --days 21
"""
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

ET = ZoneInfo("America/New_York")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bias(score):
    """Mirror multi_tf_regime.lane_bias for display when bias not stored."""
    if score is None:
        return "UNK"
    if score >= 60:
        return "UP"
    if score <= 40:
        return "DN"
    return "NEU"


def main():
    days = 21
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception:
            days = 21

    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = list(db.market_regime_state.find(
        {"timestamp": {"$gte": cutoff}}, {"_id": 0}).sort("timestamp", 1))

    print(f"\n=== v326 REGIME / MULTI-TF CONTEXT TIMELINE — last {days}d ===\n")
    if not rows:
        print("  No market_regime_state docs in window.")
        print("  (collection upserts one doc/day; if empty the engine may not be")
        print("   persisting — check market_regime_engine._store_regime / db handle.)\n")
        return

    hdr = (f"  {'date':<11} {'comp':>5} {'state':<13} {'context':<18} "
           f"{'longSc/bias':>12} {'intraSc/bias':>13} {'mid':>4} {'sht':>4} "
           f"{'mic':>4}  {'mode L/S':<20}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    comp_scores, long_scores, contexts, modeL, modeS = set(), set(), Counter(), Counter(), Counter()
    mixed_days = []
    n_days = 0

    for r in rows:
        n_days += 1
        date = str(r.get("date", "?"))[:11]
        comp = _f(r.get("composite_score"))
        state = str(r.get("state", "?"))
        mtf = r.get("multi_tf") or {}
        ctx = str(mtf.get("context", "?"))
        lanes = mtf.get("lanes") or {}
        ln = lanes.get("long") or {}
        long_sc = _f(ln.get("score"))
        long_b = ln.get("bias") or _bias(long_sc)
        intra_sc = _f(mtf.get("intraday_score"))
        intra_b = mtf.get("intraday_bias") or _bias(intra_sc)
        mid_b = (lanes.get("mid") or {}).get("bias") or _bias(_f((lanes.get("mid") or {}).get("score")))
        sht_b = (lanes.get("short") or {}).get("bias") or _bias(_f((lanes.get("short") or {}).get("score")))
        mic_b = (lanes.get("micro") or {}).get("bias") or _bias(_f((lanes.get("micro") or {}).get("score")))
        modes = mtf.get("modes") or {}
        ml = str(modes.get("long", "?"))
        ms = str(modes.get("short", "?"))

        if comp is not None:
            comp_scores.add(round(comp, 1))
        if long_sc is not None:
            long_scores.add(round(long_sc, 1))
        contexts[ctx] += 1
        modeL[ml] += 1
        modeS[ms] += 1
        if ctx == "MIXED":
            mixed_days.append((date, long_b, intra_b))

        long_cell = f"{long_sc:.0f}/{long_b}" if long_sc is not None else f"-/{long_b}"
        intra_cell = f"{intra_sc:.0f}/{intra_b}" if intra_sc is not None else f"-/{intra_b}"
        comp_cell = f"{comp:.0f}" if comp is not None else "-"
        print(f"  {date:<11} {comp_cell:>5} {state:<13} {ctx:<18} "
              f"{long_cell:>12} {intra_cell:>13} {mid_b:>4} {sht_b:>4} "
              f"{mic_b:>4}  {ml}/{ms:<14}")

    print("\n" + "=" * 72)
    print("STUCK-CLASSIFIER CHECK")
    print("=" * 72)
    print(f"  days in window                    : {n_days}")
    print(f"  distinct composite scores         : {len(comp_scores)}  {sorted(comp_scores)[:12]}")
    print(f"  distinct long-anchor lane scores  : {len(long_scores)}  {sorted(long_scores)[:12]}")
    print(f"  context distribution              : " + ", ".join(f"{k}={v}" for k, v in contexts.most_common()))
    print(f"  mode(long) distribution           : " + ", ".join(f"{k}={v}" for k, v in modeL.most_common()))
    print(f"  mode(short) distribution          : " + ", ".join(f"{k}={v}" for k, v in modeS.most_common()))

    if mixed_days:
        long_neu = sum(1 for _, lb, _ in mixed_days if lb in ("NEU", "NEUTRAL"))
        intra_unk = sum(1 for _, _, ib in mixed_days if ib in ("UNK", "UNKNOWN", "None", "?"))
        intra_neu = sum(1 for _, _, ib in mixed_days if ib in ("NEU", "NEUTRAL"))
        print("\n" + "=" * 72)
        print(f"WHY MIXED? (attribution over {len(mixed_days)} MIXED days)")
        print("=" * 72)
        print(f"  long-anchor lane NEUTRAL          : {long_neu}/{len(mixed_days)}")
        print(f"  intraday lane UNKNOWN (no bars)   : {intra_unk}/{len(mixed_days)}")
        print(f"  intraday lane NEUTRAL             : {intra_neu}/{len(mixed_days)}")

    print("\n=== READING THE RESULT ===")
    print("• MIXED dominant + long-anchor NEUTRAL every day → the daily-anchor SMA")
    print("    score sits in the tolerance band → caution is the DEFAULT. If composite")
    print("    says bullish (68) but the anchor lane reads NEUTRAL, that mismatch is the")
    print("    lever (anchor-lane calibration OR the MIXED→cautious context mapping).")
    print("• MIXED because intraday lane UNKNOWN → SPY 1h/5m/1m bars not backfilled;")
    print("    classify_context falls back to anchor-only. Lever = backfill SPY intraday.")
    print("• context + scores VARY day-to-day → caution is a real-time call; leave it.")
    print("• Few distinct scores + same context every day → STUCK (stale/coarse).\n")


if __name__ == "__main__":
    main()
