#!/usr/bin/env python3
"""
diag_v366_pwire_readiness.py  (READ-ONLY P-WIRE Phase-2 readiness + regime calibration).

Answers, from live data, whether P-WIRE Phase 2 (regime-specialized vs generic model
edge eval) is unblocked yet, and what's still starving it:

  1. SHADOW CORPUS  — count of confidence_gate_log docs carrying a regime_shadow record,
     total + RESOLVED (joined to a trade outcome), broken down by regime / bar_size /
     regime_model_available / directions_agree. Phase-2 eval (pwire_shadow_eval.py --min 200)
     needs ~200 RESOLVED.
  2. REGIME SKEW    — confirms the "~91% high_vol" complaint: % of shadow records per regime.
  3. THRESHOLD CALIB— recomputes SPY's vol_expansion (atr_5/atr_20) distribution over the last
     --cal-days daily bars (EXACT classify_regime math) and shows, for candidate thresholds
     [1.3,1.4,1.5,1.6,1.7], what % of days would be tagged high_vol — so the recalibration of
     regime_conditional_model.classify_regime (currently >1.3) is picked from data, not guessed.
  4. BAR-SIZE SKEW  — confirms shadow logging only fires at 5min (the multi-TF gap).

NOTHING IS WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v366_pwire_readiness.py
  .venv/bin/python backend/scripts/diag_v366_pwire_readiness.py --days 60 --cal-days 250 --min 200
"""
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import median, mean


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _to_dt(v):
    try:
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _shadow_of(doc):
    """Locate the regime_shadow record across the candidate persisted paths."""
    for path in (("live_prediction", "regime_shadow"), ("prediction", "regime_shadow"),
                 ("regime_shadow",)):
        cur = doc
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and isinstance(cur, dict):
            return cur
    return None


def _is_resolved(doc):
    """Mirror pwire_shadow_eval: resolved if a trade outcome is attached."""
    out = doc.get("trade_outcome")
    pnl = doc.get("outcome_pnl")
    if isinstance(out, str) and out.strip():
        return True
    if isinstance(pnl, (int, float)):
        return True
    return False


def _atr(highs, lows, closes, period):
    """EXACT replica of classify_regime._atr (most-recent-first arrays)."""
    n = len(closes)
    vals = []
    for i in range(min(period, n - 1)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
            abs(lows[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
        )
        vals.append(tr)
    return (sum(vals) / len(vals)) if vals else 0.0


def main():
    days = _arg("--days", 60, int)
    cal_days = _arg("--cal-days", 250, int)
    need = _arg("--min", 200, int)
    db = _load_db()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    print(f"\n=== v366 P-WIRE Phase-2 readiness — now {now.isoformat(timespec='seconds')} ===")
    print(f"    shadow window: last {days}d   |   Phase-2 resolved target: {need}\n")

    # ── 1+2+4: shadow corpus ────────────────────────────────────────────────
    total = 0; with_shadow = 0; resolved = 0; resolved_with_regime_model = 0
    by_regime = Counter(); by_barsize = Counter()
    regime_avail = Counter(); agree = Counter()
    resolved_by_regime = Counter()
    for d in db.confidence_gate_log.find(
            {}, {"_id": 0, "live_prediction": 1, "prediction": 1, "regime_shadow": 1,
                 "trade_outcome": 1, "outcome_pnl": 1, "timestamp": 1, "trigger_time": 1}):
        ts = _to_dt(d.get("timestamp") or d.get("trigger_time"))
        if ts and ts < cutoff:
            continue
        total += 1
        sh = _shadow_of(d)
        if not sh:
            continue
        with_shadow += 1
        reg = sh.get("regime", "?")
        by_regime[reg] += 1
        by_barsize[sh.get("bar_size", "?")] += 1
        regime_avail["available" if sh.get("regime_model_available") else "missing"] += 1
        agree["agree" if sh.get("directions_agree") else "disagree/na"] += 1
        if _is_resolved(d):
            resolved += 1
            resolved_by_regime[reg] += 1
            if sh.get("regime_model_available"):
                resolved_with_regime_model += 1

    print(f"--- 1) SHADOW CORPUS (confidence_gate_log, last {days}d) ---")
    print(f"    gate docs scanned        : {total}")
    print(f"    carrying regime_shadow   : {with_shadow}")
    print(f"    RESOLVED (trade outcome) : {resolved}    (Phase-2 needs ~{need})")
    print(f"    resolved & regime-model  : {resolved_with_regime_model}")
    verdict = "GO ✅" if resolved >= need else f"WAIT ⏳ (need {need - resolved} more)"
    print(f"    >>> Phase-2 eval gate    : {verdict}\n")

    print(f"--- 2) REGIME SKEW (all shadow records) ---")
    for reg, n in by_regime.most_common():
        pct = 100.0 * n / with_shadow if with_shadow else 0
        print(f"    {reg:<14} {n:>6}  ({pct:>4.1f}%)   resolved={resolved_by_regime.get(reg,0)}")
    hv = by_regime.get("high_vol", 0)
    print(f"    high_vol share           : {100.0*hv/with_shadow if with_shadow else 0:.1f}%  "
          f"(complaint was ~91% — starves trend buckets)\n")

    print(f"--- 4) BAR-SIZE SKEW ---")
    for bs, n in by_barsize.most_common():
        print(f"    {bs:<10} {n:>6}  ({100.0*n/with_shadow if with_shadow else 0:.1f}%)")
    print(f"    regime_model_available   : {dict(regime_avail)}")
    print(f"    directions_agree         : {dict(agree)}\n")

    # ── 3: SPY vol_expansion threshold calibration ──────────────────────────
    print(f"--- 3) REGIME THRESHOLD CALIBRATION (SPY 1-day, last {cal_days} bars) ---")
    rows = list(db.ib_historical_data.find(
        {"symbol": "SPY", "bar_size": "1 day"},
        {"_id": 0, "date": 1, "high": 1, "low": 1, "close": 1}).sort("date", 1))
    rows = [r for r in rows if r.get("high") and r.get("low") and r.get("close")]
    if len(rows) < 30:
        print(f"    not enough SPY daily bars ({len(rows)}) — skip calibration\n")
    else:
        rows = rows[-cal_days:]
        closes = [r["close"] for r in rows]
        highs = [r["high"] for r in rows]
        lows = [r["low"] for r in rows]
        ve = []
        for i in range(24, len(rows)):  # need >=25 bars of history
            c = closes[:i + 1][::-1]; h = highs[:i + 1][::-1]; lo = lows[:i + 1][::-1]
            a5 = _atr(h, lo, c, 5); a20 = _atr(h, lo, c, 20)
            if a20 > 0:
                ve.append(a5 / a20)
        if not ve:
            print("    could not compute vol_expansion series\n")
        else:
            print(f"    vol_expansion over {len(ve)} days: "
                  f"min={min(ve):.2f} med={median(ve):.2f} mean={mean(ve):.2f} max={max(ve):.2f}")
            print(f"    {'threshold':<12}{'% days high_vol':>16}")
            for thr in (1.3, 1.4, 1.5, 1.6, 1.7):
                pct = 100.0 * sum(1 for x in ve if x > thr) / len(ve)
                flag = "  <-- CURRENT (>1.3)" if abs(thr - 1.3) < 1e-9 else ""
                print(f"    >{thr:<11.1f}{pct:>15.1f}%{flag}")
            print("    Target: a high_vol that fires on genuine fear/expansion (~10-25% of days),")
            print("    NOT the majority. Pick the lowest threshold whose high_vol%% is in that band.\n")

    print("=== READING ===")
    print("• If RESOLVED >= target -> run pwire_shadow_eval.py for the Phase-2 edge verdict.")
    print("• If high_vol% is the majority -> recalibrate classify_regime threshold (P0-CLASSIFIER)")
    print("  to the calibrated value above; trend buckets then accrue shadow data.")
    print("• If bar-size is ~100% '5 mins' -> multi-TF shadow logging (P1-MULTI-TF) will widen the")
    print("  corpus across 1min/15min so per-(bar_size,regime) cells reach trainable N faster.\n")


if __name__ == "__main__":
    main()
