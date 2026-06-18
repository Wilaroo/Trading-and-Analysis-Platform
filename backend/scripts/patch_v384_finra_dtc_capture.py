#!/usr/bin/env python3
"""patch_v384 — unified_fundamentals_cache.py: capture FINRA days_to_cover + short shares
REGARDLESS of float (was float-gated → dropped for ~65% of names). Pure data-capture
(coverage) change; no scoring touched. Anchored + py_compile-gated + .bak + --rollback.
Run from repo root:
  .venv/bin/python backend/scripts/patch_v384_finra_dtc_capture.py --check
  .venv/bin/python backend/scripts/patch_v384_finra_dtc_capture.py
  .venv/bin/python backend/scripts/patch_v384_finra_dtc_capture.py --rollback
"""
import hashlib, py_compile, sys
from pathlib import Path

F = Path("services/unified_fundamentals_cache.py")
MARKER = "v384: days_to_cover and raw"

OLD = '''    # 3.5 Short-interest % — FINRA short-interest shares ÷ shares-outstanding.
    # Float/shares come from IB ReportSnapshot above; FINRA gives raw short
    # shares (no %). FINRA is bi-monthly (the accurate cadence). (v19.34.202)
    shares_out = merged.get("shares_outstanding") or merged.get("float_shares")
    if shares_out and float(shares_out) > 0 and db is not None:
        try:
            from services.short_interest_service import ShortInterestService
            si = await ShortInterestService(db).get_short_data_for_symbol(symbol)
            si_shares = (si or {}).get("short_interest")
            pct = compute_short_interest_pct(si_shares, shares_out)
            if pct is not None:
                merged["short_interest_percent"] = pct
                if (si or {}).get("days_to_cover") is not None:
                    merged["days_to_cover"] = si["days_to_cover"]
                source_chain.append("finra_short")
        except Exception as exc:
            logger.debug("Short-interest lookup failed for %s: %s", symbol, exc)'''

NEW = '''    # 3.5 Short interest — FINRA (bi-monthly, free). v384: days_to_cover and raw
    # short shares need NO float, so capture them for the full ~80% FINRA universe
    # (the squeeze signal for explosive movers); compute SI% only when float is
    # known. Previously the whole block was gated on float → days_to_cover was
    # silently dropped for the ~65% of names without a known float.
    if db is not None:
        try:
            from services.short_interest_service import ShortInterestService
            si = await ShortInterestService(db).get_short_data_for_symbol(symbol)
            si_shares = (si or {}).get("short_interest")
            if (si or {}).get("days_to_cover") is not None:
                merged["days_to_cover"] = si["days_to_cover"]
            if si_shares:
                merged["short_interest_shares"] = si_shares
            shares_out = merged.get("shares_outstanding") or merged.get("float_shares")
            if shares_out and float(shares_out) > 0:
                pct = compute_short_interest_pct(si_shares, shares_out)
                if pct is not None:
                    merged["short_interest_percent"] = pct
            if si_shares or (si or {}).get("days_to_cover") is not None:
                source_chain.append("finra_short")
        except Exception as exc:
            logger.debug("Short-interest lookup failed for %s: %s", symbol, exc)'''


def sha(t): return hashlib.sha256(t.encode()).hexdigest()[:16]


def main():
    if "--rollback" in sys.argv:
        bak = F.with_suffix(".py.bak.v384")
        if bak.exists():
            F.write_text(bak.read_text()); bak.unlink(); print("ROLLED BACK", F)
        else:
            print("no .bak.v384 backup")
        return
    if not F.exists():
        print("ABORT: run from repo root (services/... not found)"); return
    t = F.read_text()
    print(f"PRE-SHA {sha(t)}")
    if MARKER in t:
        print("already applied — skip"); return
    if OLD not in t:
        print("ABORT: anchor not found (DGX drift). Upload your copy:")
        print("  curl --data-binary @services/unified_fundamentals_cache.py https://paste.rs/")
        return
    new = t.replace(OLD, NEW, 1)
    if "--check" in sys.argv:
        print(f"POST-SHA(predicted) {sha(new)}  — would write. Re-run without --check."); return
    F.with_suffix(".py.bak.v384").write_text(t)
    F.write_text(new)
    try:
        py_compile.compile(str(F), doraise=True)
    except py_compile.PyCompileError as e:
        F.write_text(t); print("COMPILE FAILED — reverted:", e); return
    print(f"WROTE {F}  POST-SHA {sha(new)}  (backup .py.bak.v384). Restart backend to load.")


if __name__ == "__main__":
    main()
