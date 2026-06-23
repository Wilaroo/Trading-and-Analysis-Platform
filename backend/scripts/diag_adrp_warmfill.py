#!/usr/bin/env python3
"""diag_adrp_warmfill.py (READ-ONLY) — scope + verify the scalp/intraday
ADRP (Average Daily Range %) fast-path warm-fill.

Answers four questions, writing NOTHING:

  A) FAST-PATH COVERAGE — how many symbol_adv_cache docs already carry a
     positive `adrp_20d` (the gate's fast-path field). Pre-patch this is ~0%
     (the field was never written) → every scalp/intraday symbol pays the
     per-symbol on-the-fly compute each UTC day. Post-patch + rebuild it jumps.

  B) WOULD-BE WARM-FILL — for the scalp-relevant universe (tier
     intraday/swing), recompute the clean-cohort ADRP the rebuild WILL write
     (newest 20 *real* daily bars, date-len==10, pollution-filtered) and
     compare to the gate's CURRENT on-the-fly value (newest 20 bars, NO
     date filter). Reports coverage, percentiles, below/above the floor, and
     how many DIVERGE materially — i.e. names the fast-path actually fixes.

  C) REJECTION SIZING — recent `trade_drops` for the universal liquidity gate
     with check=scalp_adrp, split into fail-closed ("unmeasured", adrp<=0) vs
     measured-below-floor. For the fail-closed ones, checks whether clean daily
     bars exist → how many the warm-fill would RESCUE vs genuinely no-data.

  D) READING — plain-language interpretation.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_adrp_warmfill.py \
      --hours 24 --adrp-floor 2.0 --limit 800
"""
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def _arg(flag, d, c):
    if flag in sys.argv:
        try:
            return c(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return d
    return d


def _db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    i = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def _adrp_from_bars(bars, clean_only):
    """mean((high-low)/close)*100 over the newest 20 usable bars. When
    clean_only, restrict to *real* daily bars (date string length == 10),
    mirroring the rebuild's cleaned cohort; otherwise mirror the gate's
    on-the-fly fallback (no date filter)."""
    rngs = []
    for b in bars:
        if clean_only and len(str(b.get("date") or "")) != 10:
            continue
        h, lo, c = b.get("high"), b.get("low"), b.get("close")
        if all(isinstance(x, (int, float)) for x in (h, lo, c)) and c and c > 0 and h > 0 and lo > 0:
            rngs.append((h - lo) / c)
        if len(rngs) >= 20:
            break
    return (100.0 * sum(rngs) / len(rngs)) if rngs else 0.0


def main():
    hours = _arg("--hours", 24, int)
    floor = _arg("--adrp-floor", 2.0, float)
    limit = _arg("--limit", 800, int)
    db = _db()

    # ── A) fast-path coverage ────────────────────────────────────────────
    print("\n=== A) symbol_adv_cache.adrp_20d FAST-PATH COVERAGE ===")
    total = db["symbol_adv_cache"].count_documents({})
    with_adrp = db["symbol_adv_cache"].count_documents(
        {"adrp_20d": {"$gt": 0}})
    pct = (100.0 * with_adrp / total) if total else 0.0
    print(f"  cache docs total        : {total}")
    print(f"  with positive adrp_20d  : {with_adrp}  ({pct:.1f}%)")
    if with_adrp == 0:
        print("  → FAST-PATH IS DARK: the field is never written; the gate falls")
        print("    back to a per-symbol on-the-fly compute every UTC day.")
    # freshness
    newest = list(db["symbol_adv_cache"].find(
        {}, {"_id": 0, "updated_at": 1, "source": 1}).sort(
        [("updated_at", -1)]).limit(1))
    if newest:
        print(f"  cache last updated_at   : {newest[0].get('updated_at')}")
        print(f"  (rebuild it via POST /api/ib-collector/rebuild-adv-from-ib or the")
        print(f"   nightly EOD adv_cache_rebuild task to warm-fill adrp_20d.)")

    # ── B) would-be warm-fill simulation (scalp-relevant universe) ───────
    print(f"\n=== B) WOULD-BE WARM-FILL — clean-cohort ADRP @ floor {floor:g}% ===")
    cur = db["symbol_adv_cache"].find(
        {"tier": {"$in": ["intraday", "swing"]}},
        {"_id": 0, "symbol": 1, "tier": 1}).limit(limit if limit > 0 else 0)
    syms = [d["symbol"] for d in cur if d.get("symbol")]
    print(f"  scalp-relevant symbols (tier intraday/swing): {len(syms)}"
          + (f"  [capped at --limit {limit}]" if limit and len(syms) >= limit else ""))
    clean_vals, n_zero, n_below, n_above, diverge = [], 0, 0, 0, 0
    examples_div = []
    for s in syms:
        bars = list(db["ib_historical_data"].find(
            {"symbol": s, "bar_size": "1 day"},
            {"_id": 0, "high": 1, "low": 1, "close": 1, "date": 1}
        ).sort([("date", -1)]).limit(40))
        clean = _adrp_from_bars(bars, clean_only=True)
        raw = _adrp_from_bars(bars, clean_only=False)
        if clean <= 0:
            n_zero += 1
        else:
            clean_vals.append(clean)
            if clean < floor:
                n_below += 1
            else:
                n_above += 1
        if clean > 0 and abs(clean - raw) >= 0.5:
            diverge += 1
            if len(examples_div) < 12:
                examples_div.append((s, raw, clean))
    clean_vals.sort()
    print(f"  computable (clean adrp_20d > 0) : {len(clean_vals)}")
    print(f"  unmeasured (no clean bars)      : {n_zero}")
    if clean_vals:
        print(f"  ADRP% distribution  p10={_pct(clean_vals,0.10):.2f}  "
              f"p25={_pct(clean_vals,0.25):.2f}  p50={_pct(clean_vals,0.50):.2f}  "
              f"p75={_pct(clean_vals,0.75):.2f}  p90={_pct(clean_vals,0.90):.2f}")
        print(f"  ≥ floor (scalp-eligible on ADRP): {n_above}")
        print(f"  <  floor (correctly blocked)    : {n_below}")
    print(f"  clean vs on-the-fly DIVERGE ≥0.5% : {diverge}  "
          f"(names the pollution-clean fast-path actually corrects)")
    for s, raw, clean in examples_div:
        verdict = "fast-path RESCUES" if (raw < floor <= clean) else (
            "fast-path BLOCKS" if (clean < floor <= raw) else "shift only")
        print(f"      {s:<7} on-the-fly={raw:6.2f}%  clean={clean:6.2f}%  → {verdict}")

    # ── C) rejection sizing from trade_drops ─────────────────────────────
    print(f"\n=== C) scalp_adrp REJECTIONS (trade_drops), last {hours}h ===")
    cut = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    fail_closed = defaultdict(int)
    measured = defaultdict(int)
    for d in db["trade_drops"].find(
            {"gate": "universal_liquidity_gate", "ts": {"$gte": cut}},
            {"_id": 0, "symbol": 1, "context": 1}):
        ctx = d.get("context") or {}
        if ctx.get("check") != "scalp_adrp":
            continue
        sym = d.get("symbol") or "?"
        adrp = ctx.get("adrp")
        is_fc = bool(ctx.get("fail_closed")) or (isinstance(adrp, (int, float)) and adrp <= 0)
        (fail_closed if is_fc else measured)[sym] += 1
    n_fc = sum(fail_closed.values())
    n_meas = sum(measured.values())
    print(f"  fail-closed ('unmeasured', adrp<=0): {n_fc}")
    print(f"  measured-below-floor               : {n_meas}")
    if fail_closed:
        top = sorted(fail_closed.items(), key=lambda kv: -kv[1])[:15]
        print("    fail-closed top: " + "  ".join(f"{s}:{c}" for s, c in top))
        # rescuable? do clean bars exist for the fail-closed names
        rescuable, nodata = 0, 0
        for s in fail_closed:
            bars = list(db["ib_historical_data"].find(
                {"symbol": s, "bar_size": "1 day"},
                {"_id": 0, "high": 1, "low": 1, "close": 1, "date": 1}
            ).sort([("date", -1)]).limit(40))
            if _adrp_from_bars(bars, clean_only=True) > 0:
                rescuable += 1
            else:
                nodata += 1
        print(f"    of {len(fail_closed)} fail-closed symbols: {rescuable} have clean")
        print(f"    daily bars (warm-fill RESCUES) · {nodata} genuinely no-data")
    if measured:
        top = sorted(measured.items(), key=lambda kv: -kv[1])[:15]
        print("    measured top  : " + "  ".join(f"{s}:{c}" for s, c in top))
    if n_fc == 0 and n_meas == 0:
        print("  (no scalp_adrp drops in this window — re-run during/after RTH.)")

    # ── D) reading ───────────────────────────────────────────────────────
    print("\n=== READING ===")
    print("• A 0% coverage = fast-path dark; apply patch_adrp_20d_warmfill.py +")
    print("  rebuild the ADV cache → adrp_20d gets written and the gate stops")
    print("  recomputing it per symbol every day.")
    print("• B 'DIVERGE' + 'RESCUES' = symbols where the noisy on-the-fly compute")
    print("  (mistagged/pre-listing bars) read a wrong ADRP; the clean fast-path")
    print("  fixes them. 'BLOCKS' = correctly tightened (pollution had inflated it).")
    print("• C fail-closed with clean bars = real scalp setups the warm-fill")
    print("  unblocks; genuinely no-data names stay blocked (correct).\n")


if __name__ == "__main__":
    main()
