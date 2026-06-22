#!/usr/bin/env python3
"""
patch_tqs2_scheme_b_renorm.py
=============================
TQS scheme-B (PRESENT-ONLY RENORMALIZATION) — DORMANT / env-gated / reversible.

WHY: on sanitized bot-own recent trades, B was the best outcome-separator
(diag_schemes_vs_outcomes 21d: corr +0.133 / high-low win% spread 9.4 vs the
current weighted-average's +0.034 / 1.2). It's also correct on first principles:
don't dilute the composite with phantom neutral-50s for data we don't have.

WHAT: one anchored block in tqs_engine.calculate_tqs, right after the composite
is computed. When (and ONLY when) env TQS_RENORM_PRESENT=on, it recomputes each
pillar's score over PRESENT sub-scores only — dropping genuinely-ABSENT ("No
data") inputs and renormalizing the remaining sub-weights — then recomputes the
composite. Real-but-neutral readings (e.g. the live VIX, a neutral RSI) are KEPT;
only "No data" is dropped. Grade is percentile-calibrated so it auto-adapts;
ACTION thresholds are unchanged.

SAFETY:
  • DORMANT BY DEFAULT — with the env unset/off, behaviour is byte-identical to
    today. Applying the patch changes nothing until you flip the env var.
  • Reversible: `export TQS_RENORM_PRESENT=off` (or unset) + restart -> baseline.
  • Anchored to the exact composite block (count==1); aborts cleanly on drift.
  • Idempotent (marker v19.34.393). Writes .bak. py_compile-gated.
  ⚠ WHEN YOU FLIP IT ON: scores de-compress upward, so MORE trades may cross the
    auto-exec grade floors -> watch the auto-exec rate. Recommend flipping on for
    one RTH, compare via diag_schemes_vs_outcomes, then decide.

USAGE (DGX, repo root):
    curl -sS -o /tmp/patch_tqs2.py https://paste.rs/XXXXX
    .venv/bin/python /tmp/patch_tqs2.py --check
    .venv/bin/python /tmp/patch_tqs2.py --apply       # dormant; no behaviour change
    ./start_backend.sh --force
    # to A/B it live later:
    #   export TQS_RENORM_PRESENT=on   (in the backend env) ; restart ; observe
    .venv/bin/python /tmp/patch_tqs2.py --rollback
"""

import argparse
import hashlib
import os
import sys
import py_compile

TARGET = "backend/services/tqs/tqs_engine.py"
BAK = TARGET + ".bak.tqs2"
MARKER = "v19.34.393"

OLD = '''            # Calculate weighted total using TIMEFRAME-AWARE WEIGHTS
            result.score = (
                result.setup_score.score * weights["setup"] +
                result.technical_score.score * weights["technical"] +
                result.fundamental_score.score * weights["fundamental"] +
                result.context_score.score * weights["context"] +
                result.execution_score.score * weights["execution"]
            )
'''

NEW = '''            # Calculate weighted total using TIMEFRAME-AWARE WEIGHTS
            result.score = (
                result.setup_score.score * weights["setup"] +
                result.technical_score.score * weights["technical"] +
                result.fundamental_score.score * weights["fundamental"] +
                result.context_score.score * weights["context"] +
                result.execution_score.score * weights["execution"]
            )

            # v19.34.393 (TQS scheme-B) — PRESENT-ONLY RENORMALIZATION (dormant).
            # Best outcome-separator on sanitized bot-own trades (corr +0.13 vs
            # the plain average's +0.03). Recompute each pillar over PRESENT
            # sub-scores only (drop genuinely-absent "No data" inputs, renormalize
            # remaining sub-weights) so phantom neutral-50s stop crushing the
            # composite. Real-but-neutral readings (live VIX, neutral RSI) are
            # KEPT. ONLY active when env TQS_RENORM_PRESENT=on; fully reversible.
            import os as _os
            if _os.environ.get("TQS_RENORM_PRESENT", "off").strip().lower() == "on":
                try:
                    _SUBW = {
                        "setup": {"pattern": .20, "win_rate": .15, "expected_value": .30, "tape": .20, "smb": .15},
                        "technical": {"trend": .25, "rsi": .20, "levels": .20, "volatility": .15, "volume": .20},
                        "fundamental": {"catalyst": .25, "short_interest": .20, "float": .15, "institutional": .10, "earnings": .10, "financial": .20},
                        "context": {"regime": .22, "relative_strength": .20, "time": .18, "sector": .15, "vix": .12, "ai_model": .10, "day": .03},
                        "execution": {"history": .25, "tilt": .30, "entry_tendency": .15, "exit_tendency": .15, "streak": .15},
                    }

                    def _renorm_pillar(_pobj, _w):
                        _pd = _pobj.to_dict()
                        _comps = _pd.get("components") or {}
                        _disp = _pd.get("display") or {}
                        _num = _den = 0.0
                        for _s, _wi in _w.items():
                            if _s not in _comps:
                                continue
                            _vd = str((_disp.get(_s) or {}).get("verdict", "")).strip().lower()
                            if _vd == "no data":
                                continue  # drop genuinely-absent
                            try:
                                _c = float(_comps[_s])
                            except (TypeError, ValueError):
                                continue
                            _num += _wi * _c
                            _den += _wi
                        return (_num / _den) if _den > 0 else None

                    _pmap = {
                        "setup": result.setup_score, "technical": result.technical_score,
                        "fundamental": result.fundamental_score, "context": result.context_score,
                        "execution": result.execution_score,
                    }
                    _new = 0.0
                    for _pn, _po in _pmap.items():
                        _ps = _renorm_pillar(_po, _SUBW[_pn])
                        if _ps is None:
                            _ps = _po.score
                        else:
                            _po.score = round(_ps, 2)  # reflect in persisted breakdown
                        _new += _ps * weights[_pn]
                    result.score_baseline_avg = round(result.score, 2)
                    result.score = round(_new, 2)
                    logger.info("[tqs-renorm v393 ON] %s %s avg=%.1f -> renorm=%.1f",
                                symbol, setup_type, result.score_baseline_avg, result.score)
                except Exception as _rn_e:
                    logger.warning("[tqs-renorm v393] failed, kept baseline avg: %s", _rn_e)
'''


def _sha(b):
    return hashlib.sha256(b).hexdigest()

def _read(path):
    if not os.path.exists(path):
        print(f"ERROR: target not found: {path} (run from repo root)")
        sys.exit(2)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _grep_hint():
    print("\n  Rebase hint — send me the live block:")
    print(f"    grep -n -A7 'Calculate weighted total using TIMEFRAME-AWARE' {TARGET}")

def cmd_check(src, applied):
    print(f"  target : {TARGET}")
    print(f"  sha256 : {_sha(src.encode())}")
    if applied:
        print("  STATUS : ALREADY PATCHED (marker present) — apply would no-op.")
        return 0
    n = src.count(OLD)
    if n != 1:
        print(f"  ERROR  : anchor block found {n} times (need exactly 1) — DRIFT.")
        _grep_hint()
        return 3
    print("  anchor : found (count==1) ✓")
    print(f"  POST   : {_sha(src.replace(OLD, NEW, 1).encode())}  (predicted)")
    print("  DORMANT: behaviour identical until env TQS_RENORM_PRESENT=on.")
    print("  --check OK. Re-run with --apply to write.")
    return 0

def cmd_apply(src, applied):
    if applied:
        print("  ALREADY PATCHED — no-op.")
        return 0
    n = src.count(OLD)
    if n != 1:
        print(f"  ERROR: anchor found {n} times (need 1) — DRIFT. Aborting.")
        _grep_hint()
        return 3
    pre = _sha(src.encode())
    new_src = src.replace(OLD, NEW, 1)
    with open(BAK, "w", encoding="utf-8") as f:
        f.write(src)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_src)
    try:
        py_compile.compile(TARGET, doraise=True)
    except py_compile.PyCompileError as e:
        with open(TARGET, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"  ERROR: py_compile failed, reverted. {e}")
        return 4
    print(f"  PRE  sha256: {pre}")
    print(f"  POST sha256: {_sha(new_src.encode())}")
    print(f"  backup     : {BAK}")
    print("  ✅ APPLIED (DORMANT) + py_compile OK. No behaviour change until you set")
    print("     TQS_RENORM_PRESENT=on in the backend env and restart.")
    return 0

def cmd_rollback():
    if not os.path.exists(BAK):
        print(f"  ERROR: no backup at {BAK}")
        return 2
    with open(BAK, "r", encoding="utf-8") as f:
        src = f.read()
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    os.remove(BAK)
    print(f"  ✅ ROLLED BACK. sha256: {_sha(src.encode())}")
    return 0

def main():
    global TARGET, BAK
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    ap.add_argument("--target", default=TARGET)
    args = ap.parse_args()
    TARGET = args.target
    BAK = TARGET + ".bak.tqs2"

    if args.rollback:
        sys.exit(cmd_rollback())
    src = _read(TARGET)
    applied = (MARKER in src and "_renorm_pillar" in src)
    if args.apply:
        sys.exit(cmd_apply(src, applied))
    sys.exit(cmd_check(src, applied))

if __name__ == "__main__":
    main()
