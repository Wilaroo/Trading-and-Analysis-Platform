#!/usr/bin/env python3
"""patch_v390 (F2b) — fundamental_quality.py: score recent earnings BEAT/MISS surprise (post-earnings
drift) from earnings_calendar (eps_result/eps_surprise_pct/revenue_result, already captured). A fresh
BEAT (esp. with a revenue beat) lifts the earnings sub-score (momentum tailwind); a MISS drags it.
Looks back ~10 days; absent → unchanged (proximity/neutral). 4 anchored chunks, py_compile-gated,
.bak + --rollback. Run from repo root:
  .venv/bin/python backend/scripts/patch_v390_earnings_surprise.py --check | (apply) | --rollback
"""
import hashlib, py_compile, sys
from pathlib import Path

F = next((p for p in (Path("backend/services/tqs/fundamental_quality.py"),
                      Path("services/tqs/fundamental_quality.py")) if p.exists()),
         Path("backend/services/tqs/fundamental_quality.py"))
MARKER = "v390 — recent earnings SURPRISE"

CHUNKS = [
    ("""        _fin = {}  # v389 — IB ReportSnapshot financials (roe/margin/growth/leverage)""",
     """        _fin = {}  # v389 — IB ReportSnapshot financials (roe/margin/growth/leverage)
        _post_earn = None  # v390 — most recent reported earnings surprise (drift)"""),
    ("""            except Exception as e:
                logger.debug(f"Could not check earnings: {e}")
                """,
     """            except Exception as e:
                logger.debug(f"Could not check earnings: {e}")

        # v390 — recent earnings SURPRISE (post-earnings drift): a fresh BEAT is a
        # strong momentum tailwind; a MISS is a drag. Looks back ~10 calendar days.
        if self._db is not None:
            try:
                from datetime import datetime, timezone, timedelta
                _now = datetime.now(timezone.utc)
                recent = self._db["earnings_calendar"].find_one({
                    "symbol": symbol, "is_reported": True,
                    "date": {"$gte": (_now - timedelta(days=10)).isoformat(),
                             "$lte": _now.isoformat()},
                }, sort=[("date", -1)])
                if recent and recent.get("eps_result"):
                    _post_earn = {"result": recent.get("eps_result"),
                                  "eps_surp": recent.get("eps_surprise_pct"),
                                  "rev_result": recent.get("revenue_result")}
            except Exception as e:
                logger.debug(f"Could not check recent earnings: {e}")
                """),
    ("""        else:
            result.earnings_score = 60  # No earnings soon - neutral
""",
     """        else:
            result.earnings_score = 60  # No earnings soon - neutral

        # v390 — post-earnings drift overrides proximity when a fresh report exists:
        # a recent BEAT (esp. with revenue beat) is a momentum tailwind; MISS a drag.
        if _post_earn:
            _res = (_post_earn.get("result") or "").upper()
            _sp = _post_earn.get("eps_surp")
            _rev = (_post_earn.get("rev_result") or "").upper()
            if _res == "BEAT":
                _b = 78 if (_sp is not None and _sp >= 10) else 70
                if _rev == "BEAT":
                    _b += 6
                result.earnings_score = min(92, _b)
                result.factors.append(
                    f"Recent earnings BEAT{' + rev beat' if _rev == 'BEAT' else ''} — drift (+)")
            elif _res == "MISS":
                _b = 30 if (_sp is not None and _sp <= -10) else 38
                if _rev == "MISS":
                    _b -= 5
                result.earnings_score = max(22, _b)
                result.factors.append("Recent earnings MISS — drift (-)")
"""),
    ("""        if _earnings_absent:
            result.earnings_score = 50.0""",
     """        if _earnings_absent and not _post_earn:  # v390 — keep post-earnings drift score
            result.earnings_score = 50.0"""),
]


def sha(t): return hashlib.sha256(t.encode()).hexdigest()[:16]


def main():
    if "--rollback" in sys.argv:
        bak = F.with_suffix(".py.bak.v390")
        if bak.exists():
            F.write_text(bak.read_text()); bak.unlink(); print("ROLLED BACK", F)
        else:
            print("no .bak.v390 backup")
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
        print(f"POST-SHA(predicted) {sha(new)} — 4/4 anchors OK. Re-run without --check."); return
    F.with_suffix(".py.bak.v390").write_text(t)
    F.write_text(new)
    try:
        py_compile.compile(str(F), doraise=True)
    except py_compile.PyCompileError as e:
        F.write_text(t); print("COMPILE FAILED — reverted:", e); return
    print(f"WROTE {F}  POST-SHA {sha(new)} (backup .py.bak.v390). Restart backend to load.")


if __name__ == "__main__":
    main()
