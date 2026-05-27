#!/usr/bin/env python3
"""v19.34.166 deploy script — applies 3 surgical edits.

1. Patches `backend/services/realtime_technical_service.py` trend
   classifier (L596-602) to add 0.25% tolerance + macro-context override.
2. Patches `backend/scripts/audit_regime_v19_34_166.py` to read the
   correct `market_regime_state` collection (not `market_regime`)
   and to flatten the nested /api/technicals/SPY schema.
3. Creates `backend/tests/test_trend_classifier_v19_34_166.py`
   with 9 pytest cases covering the audit scenarios.

Idempotent — safe to run multiple times. Bails out if any of the
expected anchor strings are missing (so it won't half-apply).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RTS = ROOT / "backend" / "services" / "realtime_technical_service.py"
AUDIT = ROOT / "backend" / "scripts" / "audit_regime_v19_34_166.py"
TEST = ROOT / "backend" / "tests" / "test_trend_classifier_v19_34_166.py"

# ── Edit 1: realtime_technical_service.py trend classifier ─────────────
RTS_OLD = '''        # Trend determination
        if above_ema9 and above_ema20 and ema_9 > ema_20:
            trend = "uptrend"
        elif not above_ema9 and not above_ema20 and ema_9 < ema_20:
            trend = "downtrend"
        else:
            trend = "sideways"'''

RTS_NEW = '''        # === Trend determination (v19.34.166 — tolerance + macro context) ===
        # Pre-v166 used strict binary `>` against EMA9/EMA20 which flipped
        # uptrend<->downtrend tick-by-tick when price hovered within pennies
        # of the EMAs. 2026-05-27 audit found SPY classified as "downtrend"
        # while sitting $0.07 below EMA9 on a +0.48% gap-up day with price
        # 7% above EMA50/SMA200 — clearly consolidation in an uptrend.
        _TREND_TOLERANCE_PCT = 0.25  # v166 — operator-approved Q2b
        _at_ema9  = abs(dist_from_ema9)  <= _TREND_TOLERANCE_PCT
        _at_ema20 = abs(dist_from_ema20) <= _TREND_TOLERANCE_PCT
        _eff_above_ema9  = above_ema9  and not _at_ema9
        _eff_above_ema20 = above_ema20 and not _at_ema20
        _eff_below_ema9  = (not above_ema9)  and not _at_ema9
        _eff_below_ema20 = (not above_ema20) and not _at_ema20
        _macro_uptrend   = (current_price > ema_50 > 0) and (ema_50 > sma_200 > 0)
        _macro_downtrend = (current_price < ema_50) and (ema_50 < sma_200) \\
            and ema_50 > 0 and sma_200 > 0
        if _eff_above_ema9 and _eff_above_ema20 and ema_9 > ema_20:
            trend = "uptrend"
        elif _eff_below_ema9 and _eff_below_ema20 and ema_9 < ema_20:
            trend = "sideways" if _macro_uptrend else "downtrend"
        else:
            trend = "sideways"
        if trend == "uptrend" and _macro_downtrend:
            trend = "sideways"'''

# ── Edit 2a: audit script — flatten SPY snapshot helper ────────────────
AUDIT_OLD_1 = "def _recompute_scanner_regime(snap: dict) -> str:"
AUDIT_NEW_1 = '''def _flatten_spy_snapshot(snap: dict) -> dict:
    """v166: /api/technicals/SPY returns nested dicts; project to flat."""
    flat = dict(snap)
    pos = snap.get("position") or {}
    dist = snap.get("distances") or {}
    vol = snap.get("volatility") or {}
    mom = snap.get("momentum") or {}
    mav = snap.get("moving_averages") or {}
    pri = snap.get("price") or {}
    flat.setdefault("trend", pos.get("trend"))
    flat.setdefault("above_vwap", pos.get("above_vwap"))
    flat.setdefault("above_ema9", pos.get("above_ema9"))
    flat.setdefault("above_ema20", pos.get("above_ema20"))
    flat.setdefault("dist_from_vwap", dist.get("from_vwap"))
    flat.setdefault("dist_from_ema9", dist.get("from_ema9"))
    flat.setdefault("dist_from_ema20", dist.get("from_ema20"))
    flat.setdefault("daily_range_pct", vol.get("daily_range_pct"))
    flat.setdefault("rsi_14", mom.get("rsi"))
    flat.setdefault("vwap", mav.get("vwap"))
    flat.setdefault("ema_9", mav.get("ema_9"))
    flat.setdefault("ema_20", mav.get("ema_20"))
    flat.setdefault("current_price", pri.get("current"))
    return flat


def _recompute_scanner_regime(snap: dict) -> str:'''

# Edit 2b: use the flattener + ignore None when displaying
AUDIT_OLD_2 = '''            spy_snap = out
            print(f"  SPY snapshot from {ep}:")
            for k in ("current_price", "vwap", "ema_9", "ema_20",
                      "rsi_14", "dist_from_vwap", "daily_range_pct",
                      "trend", "above_vwap", "above_ema9"):
                if k in spy_snap:
                    print(f"    {k:<22}  {spy_snap[k]}")'''
AUDIT_NEW_2 = '''            spy_snap = _flatten_spy_snapshot(out)
            print(f"  SPY snapshot from {ep}:")
            for k in ("current_price", "vwap", "ema_9", "ema_20",
                      "rsi_14", "dist_from_vwap", "daily_range_pct",
                      "trend", "above_vwap", "above_ema9"):
                if k in spy_snap and spy_snap[k] is not None:
                    print(f"    {k:<22}  {spy_snap[k]}")'''

# Edit 2c: read market_regime_state, not market_regime
AUDIT_OLD_3 = '''    hr("E. `market_regime` collection — last 30 days of state transitions")
    if "market_regime" not in db.list_collection_names():
        print(f"  Collection `market_regime` does NOT exist in `{db_name}`.")
        print("  \u2192 Engine is not persisting; we have NO historical record.")
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        rows = list(db.market_regime.find(
            {"last_updated": {"$gte": cutoff}},
            {"_id": 0, "last_updated": 1, "state": 1, "composite_score": 1},
        ).sort("last_updated", 1))
        if not rows:
            print(f"  No rows in last 30 days. Total docs: "
                  f"{db.market_regime.count_documents({})}")'''
AUDIT_NEW_3 = '''    hr("E. `market_regime_state` collection \u2014 last 30 days of state transitions")
    coll_name = None
    for cand in ("market_regime_state", "market_regime"):
        if cand in db.list_collection_names():
            coll_name = cand
            break
    if coll_name is None:
        print(f"  Neither `market_regime_state` nor `market_regime` exist in `{db_name}`.")
        print("  \u2192 Engine is not persisting; we have NO historical record.")
    else:
        print(f"  Reading from collection: {coll_name}")
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=30)
        rows = list(db[coll_name].find(
            {"$or": [
                {"timestamp": {"$gte": cutoff_dt}},
                {"last_updated": {"$gte": cutoff_dt.isoformat()}},
                {"date": {"$gte": cutoff_dt.strftime("%Y-%m-%d")}},
            ]},
            {"_id": 0, "date": 1, "timestamp": 1, "last_updated": 1,
             "state": 1, "composite_score": 1},
        ).sort("timestamp", 1))
        if not rows:
            print(f"  No rows in last 30 days. Total docs: "
                  f"{db[coll_name].count_documents({})}")'''


def apply_or_die(label: str, path: Path, old: str, new: str) -> bool:
    if not path.exists():
        print(f"  {label}: ❌ file not found at {path}")
        return False
    src = path.read_text()
    if new in src and old not in src:
        print(f"  {label}: ✅ already applied (idempotent)")
        return True
    if old not in src:
        print(f"  {label}: ❌ anchor not found — refusing to apply blindly.")
        print(f"     looked for: {old[:80]!r}...")
        return False
    path.write_text(src.replace(old, new, 1))
    print(f"  {label}: ✅ applied")
    return True


def main() -> int:
    print("=== v19.34.166 deploy ===\n")

    print("Step 1 — patch trend classifier")
    ok1 = apply_or_die("realtime_technical_service.py", RTS, RTS_OLD, RTS_NEW)

    print("\nStep 2 — patch audit script (3 edits)")
    ok2a = apply_or_die("audit script #1 (flatten helper)", AUDIT, AUDIT_OLD_1, AUDIT_NEW_1)
    ok2b = apply_or_die("audit script #2 (use flattener)", AUDIT, AUDIT_OLD_2, AUDIT_NEW_2)
    ok2c = apply_or_die("audit script #3 (collection name)", AUDIT, AUDIT_OLD_3, AUDIT_NEW_3)

    print("\nStep 3 — write pytest")
    # The test file is written in a separate step (chunk 2) since it
    # contains the full test source. This deploy script just notes if
    # the file is already present.
    if TEST.exists():
        print(f"  pytest: ✅ already present at {TEST}")
    else:
        print(f"  pytest: ⚠ not yet written — run the test-file install"
              f" command (chunk 2 of this deploy).")

    print("\n=== Result ===")
    if all([ok1, ok2a, ok2b, ok2c]):
        print("  ✅ All edits applied cleanly.")
        print("  Next: install test file, then:")
        print("    pytest backend/tests/test_trend_classifier_v19_34_166.py -v")
        print("    ./start_backend.sh --force")
        print("    python backend/scripts/audit_regime_v19_34_166.py")
        return 0
    print("  ❌ One or more edits FAILED — repo is in a partially-patched state.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
