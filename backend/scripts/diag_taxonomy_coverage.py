#!/usr/bin/env python3
"""
diag_taxonomy_coverage.py  (READ-ONLY)
======================================
First pass of the taxonomy-alignment audit. The SSOT (services.setup_taxonomy)
classifies setups, but any setup NOT in its sets falls to setup_class='unknown'
and ai_feature_family()='MOMENTUM' (the silent default) — meaning it is scored by
the WRONG AI model. This finds those gaps using LIVE data + the live registries.

Checks:
  A. Every distinct setup_type that has actually TRADED (bot_trades) — classify
     via the SSOT; flag any that resolve to setup_class='unknown' or
     strategy_family='unknown' (→ misrouted to MOMENTUM). Weighted by trade count.
  B. Same for live_alerts / scanner candidates (what the scanner emits).
  C. SCANNER_TO_ENSEMBLE_KEY coverage: do all canonical setups map to an ensemble?
  D. CNN SETUP_CLASSES vs taxonomy (chart_pattern_cnn).
  E. market_setup_classifier matrix keys not in the SSOT roster (code drift).

Writes NOTHING.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_taxonomy_coverage.py
"""
import os
from collections import Counter

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402
from services.setup_taxonomy import (  # noqa: E402
    canonicalize, setup_class, strategy_family, ai_feature_family,
    is_edge_excluded, ALL_CANONICAL_SETUPS,
)

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def classify_collection(coll_name, field="setup_type"):
    c = Counter()
    if coll_name not in db.list_collection_names():
        return c
    for r in db[coll_name].find({}, {field: 1, "_id": 0}):
        v = r.get(field)
        if v:
            c[str(v)] += 1
    return c


print("=" * 84)
print("A. SETUPS THAT HAVE TRADED (bot_trades) — SSOT coverage")
print("=" * 84)
bt = Counter()
for r in db.bot_trades.find({}, {"setup_type": 1, "_id": 0}):
    v = r.get("setup_type")
    if v:
        bt[str(v)] += 1

unknown_traded = []
print(f"\n{'raw setup_type':<28}{'canonical':<22}{'class':<10}{'family':<13}{'ai_key':<16}{'n':>6}")
print("-" * 95)
for raw, n in bt.most_common():
    if is_edge_excluded(raw):
        continue
    cls = setup_class(raw)
    fam = strategy_family(raw)
    aik = ai_feature_family(raw)
    flag = "  ⚠️" if (cls == "unknown" or fam == "unknown") else ""
    print(f"{raw:<28}{canonicalize(raw):<22}{cls:<10}{fam:<13}{aik:<16}{n:>6}{flag}")
    if cls == "unknown" or fam == "unknown":
        unknown_traded.append((raw, n, aik))

print("\n  ⚠️  UNKNOWN-class traded setups (misrouted → scored as MOMENTUM):")
if unknown_traded:
    for raw, n, aik in sorted(unknown_traded, key=lambda x: -x[1]):
        print(f"      {raw:<28} n={n:<5} → ai_feature_family='{aik}'")
    print(f"      TOTAL trades on misrouted setups: {sum(n for _, n, _ in unknown_traded)}")
else:
    print("      (none — every traded setup is covered by the SSOT)")

print("\n" + "=" * 84)
print("B. SCANNER CANDIDATES (live_alerts) — SSOT coverage")
print("=" * 84)
la = classify_collection("live_alerts")
if not la:
    la = classify_collection("alerts")
unknown_alerts = []
for raw, n in la.most_common():
    if is_edge_excluded(raw):
        continue
    if setup_class(raw) == "unknown" or strategy_family(raw) == "unknown":
        unknown_alerts.append((raw, n))
if unknown_alerts:
    print("  ⚠️  unknown-class scanner setups:")
    for raw, n in sorted(unknown_alerts, key=lambda x: -x[1]):
        print(f"      {raw:<28} n={n}")
else:
    print("  (no live_alerts data, or all covered)")

print("\n" + "=" * 84)
print("C. ENSEMBLE-KEY COVERAGE (SCANNER_TO_ENSEMBLE_KEY)")
print("=" * 84)
try:
    from services.ai_modules.ensemble_live_inference import SCANNER_TO_ENSEMBLE_KEY
    from services.ai_modules.ensemble_model import ENSEMBLE_MODEL_CONFIGS
    mapped = set(k.upper() for k in SCANNER_TO_ENSEMBLE_KEY)
    fam_keys = set(ENSEMBLE_MODEL_CONFIGS.keys())
    missing = []
    for base in sorted(ALL_CANONICAL_SETUPS):
        aik = ai_feature_family(base)  # the family key
        if aik not in fam_keys and base.upper() not in mapped:
            missing.append((base, aik))
    print(f"  ensemble configs available: {sorted(fam_keys)}")
    if missing:
        print("  ⚠️  canonical setups whose ai_feature_family has NO ensemble model:")
        for base, aik in missing:
            print(f"      {base:<24} → {aik}")
    else:
        print("  ✅ every canonical setup's ai_feature_family has an ensemble model")
except Exception as e:
    print(f"  (could not check: {e})")

print("\n" + "=" * 84)
print("D. CNN SETUP_CLASSES vs taxonomy")
print("=" * 84)
try:
    from services.ai_modules.chart_pattern_cnn import SETUP_CLASSES
    cnn = set(s.lower() for s in SETUP_CLASSES)
    canon = set(ALL_CANONICAL_SETUPS)
    print(f"  CNN classes ({len(cnn)}): {sorted(cnn)}")
    only_cnn = cnn - canon - {"unknown"}
    if only_cnn:
        print(f"  ⚠️  in CNN but not in taxonomy roster: {sorted(only_cnn)}")
    else:
        print("  ✅ CNN classes subset of taxonomy")
except Exception as e:
    print(f"  (could not check: {e})")

print("\n" + "=" * 84)
print("E. market_setup_classifier matrix keys not in SSOT roster")
print("=" * 84)
try:
    from services.market_setup_classifier import TRADE_SETUP_MATRIX
    keys = set(canonicalize(k) for k in TRADE_SETUP_MATRIX)
    drift = keys - set(ALL_CANONICAL_SETUPS)
    if drift:
        print(f"  ⚠️  matrix setups missing from taxonomy roster: {sorted(drift)}")
    else:
        print("  ✅ matrix keys all covered by taxonomy")
except Exception as e:
    print(f"  (could not check: {e})")

print("\nDONE — paste this whole block back. (This is audit pass 1 of N.)")
