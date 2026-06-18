#!/usr/bin/env python3
"""patch_v389 (F2c) — fundamental_quality.py: score the IB ReportSnapshot financials we now capture.
Adds a financial_score sub-pillar (ROE, net margin, EPS growth, debt/equity), weighted 0.20, absent→
neutral 50 (no penalty for names IB doesn't cover). Re-weights the fundamental composite:
  catalyst .30→.25, float .20→.15, institutional .15→.10, earnings .15→.10, short_interest .20 (kept),
  + financial .20 (new). 5 anchored chunks, py_compile-gated, .bak + --rollback. Run from repo root:
  .venv/bin/python backend/scripts/patch_v389_financial_subscore.py --check | (apply) | --rollback
"""
import hashlib, py_compile, sys
from pathlib import Path

F = next((p for p in (Path("backend/services/tqs/fundamental_quality.py"),
                      Path("services/tqs/fundamental_quality.py")) if p.exists()),
         Path("backend/services/tqs/fundamental_quality.py"))
MARKER = "v389 — Financial-quality sub-score"

CHUNKS = [
    ("""        _dtc = None  # v385 — FINRA days-to-cover (squeeze fallback when SI% absent)""",
     """        _dtc = None  # v385 — FINRA days-to-cover (squeeze fallback when SI% absent)
        _fin = {}  # v389 — IB ReportSnapshot financials (roe/margin/growth/leverage)"""),
    ("""    institutional_score: float = 50.0
    earnings_score: float = 50.0
    """,
     """    institutional_score: float = 50.0
    earnings_score: float = 50.0
    financial_score: float = 50.0  # v389 — ROE/margin/growth/leverage
    """),
    ("""                "institutional": round(self.institutional_score, 1),
                "earnings": round(self.earnings_score, 1)
            },""",
     """                "institutional": round(self.institutional_score, 1),
                "earnings": round(self.earnings_score, 1),
                "financial": round(self.financial_score, 1)
            },"""),
    ("""                _dtc = cached.get("days_to_cover")  # v385""",
     """                _dtc = cached.get("days_to_cover")  # v385
                _fin = {  # v389 — IB ReportSnapshot financials
                    "roe": cached.get("roe_pct"),
                    "margin": cached.get("net_margin_pct"),
                    "growth": cached.get("eps_change_pct"),
                    "d2e": cached.get("debt_to_equity"),
                }"""),
    ("""        # Calculate weighted total
        result.score = (
            result.catalyst_score * 0.30 +
            result.short_interest_score * 0.20 +
            result.float_score * 0.20 +
            result.institutional_score * 0.15 +
            result.earnings_score * 0.15
        )""",
     """        # v389 — Financial-quality sub-score from IB ReportSnapshot (ROE, net
        # margin, EPS growth, leverage). Average the available components; absent
        # → neutral 50 (no penalty for names IB doesn't cover).
        _fc = []
        _roe = _fin.get("roe")
        if _roe is not None:
            _fc.append(90 if _roe >= 20 else 78 if _roe >= 15 else 66 if _roe >= 10
                       else 56 if _roe >= 5 else 48 if _roe >= 0 else 35)
        _mg = _fin.get("margin")
        if _mg is not None:
            _fc.append(90 if _mg >= 20 else 75 if _mg >= 10 else 62 if _mg >= 5
                       else 50 if _mg >= 0 else 35)
        _gr = _fin.get("growth")
        if _gr is not None:
            _fc.append(88 if _gr >= 25 else 72 if _gr >= 10 else 58 if _gr >= 0
                       else 45 if _gr >= -10 else 32)
        _de = _fin.get("d2e")
        if _de is not None:
            _fc.append(80 if _de <= 0.3 else 68 if _de <= 0.7 else 55 if _de <= 1.5
                       else 45 if _de <= 3 else 35)
        if _fc:
            result.financial_score = sum(_fc) / len(_fc)
            result.factors.append(
                f"Financials {result.financial_score:.0f} (ROE/margin/growth/lev, {len(_fc)}/4)")
        else:
            result.financial_score = 50.0

        # Calculate weighted total (v389 — added financial 0.20; trimmed others)
        result.score = (
            result.catalyst_score * 0.25 +
            result.short_interest_score * 0.20 +
            result.float_score * 0.15 +
            result.institutional_score * 0.10 +
            result.earnings_score * 0.10 +
            result.financial_score * 0.20
        )"""),
]


def sha(t): return hashlib.sha256(t.encode()).hexdigest()[:16]


def main():
    if "--rollback" in sys.argv:
        bak = F.with_suffix(".py.bak.v389")
        if bak.exists():
            F.write_text(bak.read_text()); bak.unlink(); print("ROLLED BACK", F)
        else:
            print("no .bak.v389 backup")
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
            print(f"ABORT: chunk {i} anchor not found (DGX drift). Upload:")
            print("  curl --data-binary @backend/services/tqs/fundamental_quality.py https://paste.rs/"); return
        new = new.replace(old, rep, 1)
    if "--check" in sys.argv:
        print(f"POST-SHA(predicted) {sha(new)} — 5/5 anchors OK. Re-run without --check."); return
    F.with_suffix(".py.bak.v389").write_text(t)
    F.write_text(new)
    try:
        py_compile.compile(str(F), doraise=True)
    except py_compile.PyCompileError as e:
        F.write_text(t); print("COMPILE FAILED — reverted:", e); return
    print(f"WROTE {F}  POST-SHA {sha(new)} (backup .py.bak.v389). Restart backend to load.")


if __name__ == "__main__":
    main()
