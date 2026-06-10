#!/usr/bin/env python3
"""
verify_v322.py — post-deploy verification for the v322 Regime-First Funnel.

Run on the DGX after `git apply` + backend restart:

    cd backend && PYTHONPATH=. ../.venv/bin/python scripts/verify_v322.py

Checks (read-only, no orders, no training):
  1. New endpoints respond: /api/market-regime/symbol/{sym},
     /api/scanner/rs-leadership, /api/scanner/regime-focus-list
  2. RS leadership table state (empty until first compute — instructions printed)
  3. Confidence-gate funnel constants importable + pure scorers sane
  4. P7 sample-count fix present in training_pipeline.py
"""
import json
import sys
import urllib.request

BASE = "http://localhost:8001"
PASS, FAIL = "✅", "❌"
results = []


def _get(path, timeout=20):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def check(name, fn):
    try:
        detail = fn()
        results.append((True, name, detail))
        print(f"{PASS} {name} — {detail}")
    except Exception as e:
        results.append((False, name, str(e)))
        print(f"{FAIL} {name} — {e}")


def c1_symbol_regime():
    d = _get("/api/market-regime/symbol/SPY")
    ctx = d.get("context")
    assert ctx, f"no context in response: {d}"
    lanes = d.get("lanes") or {}
    return f"SPY context={ctx}, lanes={ {k: (v or {}).get('bias') for k, v in lanes.items()} }"


def c2_rs_leadership():
    d = _get("/api/scanner/rs-leadership?top=5")
    assert d.get("success"), d
    n = d.get("count", 0)
    if n == 0:
        return ("table EMPTY (expected pre-first-compute) — populate with: "
                "curl -sS -X POST http://localhost:8001/api/scanner/rs-leadership/compute")
    top = [(r["symbol"], r["rs_rating"]) for r in d["ratings"][:5]]
    return f"{n} ratings loaded, top: {top}"


def c3_focus_list():
    d = _get("/api/scanner/regime-focus-list")
    assert d.get("success"), d
    return (f"{len(d.get('longs', []))} longs / {len(d.get('shorts', []))} shorts "
            f"(context={d.get('market_context')}, rated={d.get('universe_rated')})")


def c4_gate_constants():
    from services.ai_modules.confidence_gate import (
        ConfidenceGate, FUNNEL_V322_ENABLED, FUNNEL_MAX_ABS_POINTS,
        SECTOR_STRONG_BONUS, SYMTF_ALIGNED_BONUS_MAX, RS_STRONG_BONUS,
    )
    pts, _ = ConfidenceGate._score_sector_regime("strong", "long")
    assert pts == SECTOR_STRONG_BONUS
    pts2, mult, _ = ConfidenceGate._score_symbol_mtf(
        {"context": "ALIGNED_UP", "tf_alignment": {"ratio": 1.0, "lanes_counted": 4}}, "long")
    assert pts2 == SYMTF_ALIGNED_BONUS_MAX and mult == 1.0
    pts3, _ = ConfidenceGate._score_rs_leadership({"rs_rating": 95}, "long")
    assert pts3 == RS_STRONG_BONUS
    return (f"enabled={FUNNEL_V322_ENABLED}, clamp=±{FUNNEL_MAX_ABS_POINTS}, "
            f"scorers sane (sector +{pts}, symtf +{pts2}, rs +{pts3})")


def c5_p7_fix():
    import os
    p = os.path.join(os.path.dirname(__file__), "..", "services", "ai_modules",
                     "training_pipeline.py")
    src = open(p).read()
    assert "if len(X_list) < MIN_REGIME_SAMPLES" not in src, "old symbol-count check still present"
    assert "n_regime_samples < MIN_REGIME_SAMPLES" in src, "new sample-count check missing"
    return "P7 counts SAMPLES (not symbol-chunks) — regime models will train on full retrain"


if __name__ == "__main__":
    print("── v322 Regime-First Funnel verification ──")
    check("1. /api/market-regime/symbol/{sym} (c2 endpoint)", c1_symbol_regime)
    check("2. /api/scanner/rs-leadership (c3/T7)", c2_rs_leadership)
    check("3. /api/scanner/regime-focus-list", c3_focus_list)
    check("4. gate funnel scorers + constants", c4_gate_constants)
    check("5. P7 regime-conditional sample-count fix", c5_p7_fix)
    ok = sum(1 for r in results if r[0])
    print(f"\n{ok}/{len(results)} checks passed")
    sys.exit(0 if ok == len(results) else 1)
