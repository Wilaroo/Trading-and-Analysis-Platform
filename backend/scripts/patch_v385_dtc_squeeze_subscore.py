#!/usr/bin/env python3
"""patch_v385 (F2a) — fundamental_quality.py: use FINRA days_to_cover as the short-interest
squeeze sub-score when SI% is genuinely absent (~80% universe coverage, no float needed).
Was: absent SI → flat neutral-50. Now: absent SI but DTC present → real squeeze score.
3 anchored chunks, py_compile-gated, .bak + --rollback. Run from repo root:
  .venv/bin/python backend/scripts/patch_v385_dtc_squeeze_subscore.py --check
  .venv/bin/python backend/scripts/patch_v385_dtc_squeeze_subscore.py
  .venv/bin/python backend/scripts/patch_v385_dtc_squeeze_subscore.py --rollback
"""
import hashlib, py_compile, sys
from pathlib import Path

F = next((p for p in (Path("backend/services/tqs/fundamental_quality.py"),
                      Path("services/tqs/fundamental_quality.py")) if p.exists()),
         Path("backend/services/tqs/fundamental_quality.py"))
MARKER = "v385 — FINRA days-to-cover"

CHUNKS = [
    ("""        result = FundamentalQualityScore()
        is_long = direction.lower() == "long"
        """,
     """        result = FundamentalQualityScore()
        is_long = direction.lower() == "long"
        _dtc = None  # v385 — FINRA days-to-cover (squeeze fallback when SI% absent)
        """),
    ("""                if institutional_pct is None:
                    institutional_pct = cached.get("institutional_ownership_percent")""",
     """                if institutional_pct is None:
                    institutional_pct = cached.get("institutional_ownership_percent")
                _dtc = cached.get("days_to_cover")  # v385"""),
    ("""        if _si_absent:
            result.short_interest_score = 50.0
            result.factors.append("Short-interest data absent → neutral 50")""",
     """        if _si_absent:
            # v385 — before neutralising, fall back to FINRA days-to-cover (needs
            # NO float, ~80% universe coverage). High DTC = squeeze fuel for longs /
            # crowded-short risk for shorts. Only when SI% is genuinely unavailable.
            if _dtc and _dtc > 0:
                if is_long:
                    result.short_interest_score = (95 if _dtc >= 10 else 85 if _dtc >= 7
                                                   else 70 if _dtc >= 5 else 60 if _dtc >= 3
                                                   else 52 if _dtc >= 1.5 else 45)
                    result.factors.append(f"Days-to-cover {_dtc:.1f} — squeeze fuel (+)")
                else:
                    result.short_interest_score = (30 if _dtc >= 10 else 42 if _dtc >= 7
                                                   else 55 if _dtc >= 5 else 65 if _dtc >= 3
                                                   else 75 if _dtc >= 1.5 else 80)
                    result.factors.append(f"Days-to-cover {_dtc:.1f} — crowded short (-)")
            else:
                result.short_interest_score = 50.0
                result.factors.append("Short-interest data absent → neutral 50")"""),
]


def sha(t): return hashlib.sha256(t.encode()).hexdigest()[:16]


def main():
    if "--rollback" in sys.argv:
        bak = F.with_suffix(".py.bak.v385")
        if bak.exists():
            F.write_text(bak.read_text()); bak.unlink(); print("ROLLED BACK", F)
        else:
            print("no .bak.v385 backup")
        return
    if not F.exists():
        print("ABORT: run from repo root (fundamental_quality.py not found)"); return
    t = F.read_text()
    print(f"PRE-SHA {sha(t)}")
    if MARKER in t:
        print("already applied — skip"); return
    new = t
    for i, (old, rep) in enumerate(CHUNKS, 1):
        if old not in new:
            print(f"ABORT: chunk {i} anchor not found (DGX drift). Upload your copy:")
            print("  curl --data-binary @backend/services/tqs/fundamental_quality.py https://paste.rs/")
            return
        new = new.replace(old, rep, 1)
    if "--check" in sys.argv:
        print(f"POST-SHA(predicted) {sha(new)} — 3/3 anchors OK. Re-run without --check."); return
    F.with_suffix(".py.bak.v385").write_text(t)
    F.write_text(new)
    try:
        py_compile.compile(str(F), doraise=True)
    except py_compile.PyCompileError as e:
        F.write_text(t); print("COMPILE FAILED — reverted:", e); return
    print(f"WROTE {F}  POST-SHA {sha(new)} (backup .py.bak.v385). Restart backend to load.")


if __name__ == "__main__":
    main()
