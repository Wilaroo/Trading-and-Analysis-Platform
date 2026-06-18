#!/usr/bin/env python3
"""patch_v386 — IB-native fundamentals warm-fill (institutional 3%→high, float/valuation from IB
instead of Finnhub). Two files:
  A) unified_fundamentals_cache.py — add force_refresh param + bypass cache-hit (re-fetch from IB).
  B) routers/short_data.py — POST /api/short-data/warm-fundamentals (+ /status): in-process sweep of
     the evaluated universe calling get_cached_fundamentals(force_refresh) [IB ReportSnapshot] +
     refresh_institutional_ownership [IB ReportsOwnership]. SI stays FINRA (IB doesn't publish it).
Anchored, py_compile-gated, .bak + --rollback. Run from repo root:
  .venv/bin/python backend/scripts/patch_v386_ib_native_warmfill.py --check | (apply) | --rollback
"""
import hashlib, py_compile, sys
from pathlib import Path


def _f(*cands):
    for c in cands:
        if Path(c).exists():
            return Path(c)
    return Path(cands[0])


CACHE = _f("backend/services/unified_fundamentals_cache.py", "services/unified_fundamentals_cache.py")
ROUTER = _f("backend/routers/short_data.py", "routers/short_data.py")

EDITS = {
    CACHE: ("v386 — force_refresh bypasses", [
        ("async def get_cached_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:",
         "async def get_cached_fundamentals(symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:"),
        ("    # 1. Mongo cache hit?\n    if db is not None:",
         "    # 1. Mongo cache hit? (v386 — force_refresh bypasses to re-fetch from IB)\n    if db is not None and not force_refresh:"),
    ]),
    ROUTER: ("warm-fundamentals", [
        ("""class FINRAFetchRequest(BaseModel):
    symbols: Optional[List[str]] = None
    settlement_date: Optional[str] = None
    force: bool = False""",
         """class FINRAFetchRequest(BaseModel):
    symbols: Optional[List[str]] = None
    settlement_date: Optional[str] = None
    force: bool = False


class WarmFundamentalsRequest(BaseModel):
    days: float = 5
    limit: int = 0
    throttle: float = 0.8
    institutional: bool = True


_warm_progress = {"running": False, "done": 0, "total": 0, "ib_float": 0,
                  "institutional": 0, "started_at": None, "finished_at": None}


@router.post("/warm-fundamentals")
async def warm_fundamentals(request: WarmFundamentalsRequest):
    \"\"\"v386 IB-native fundamentals warm-fill (runs in-process → live clientId-11
    socket). Sweeps the evaluated universe (distinct live_alerts symbols):
    get_cached_fundamentals(force_refresh) → IB ReportSnapshot float/valuation/
    margins + FINRA short interest; and (institutional=True) refresh_institutional_
    ownership → IB ReportsOwnership. Heavy → off-hours. Poll /warm-fundamentals/status.\"\"\"
    from server import db as mongo_db
    if mongo_db is None:
        raise HTTPException(status_code=503, detail="Database not connected")
    if _warm_progress["running"]:
        return {"started": False, "reason": "already running", **_warm_progress}
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=request.days)).strftime("%Y-%m-%d")
    uni = sorted(mongo_db.live_alerts.distinct(
        "symbol", {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}}))
    if request.limit:
        uni = uni[:request.limit]

    async def _sweep():
        import asyncio
        from datetime import datetime, timezone
        from services.unified_fundamentals_cache import (
            get_cached_fundamentals, refresh_institutional_ownership)
        _warm_progress.update({"running": True, "done": 0, "total": len(uni),
                               "ib_float": 0, "institutional": 0,
                               "started_at": datetime.now(timezone.utc).isoformat(),
                               "finished_at": None})
        for sym in uni:
            try:
                merged = await get_cached_fundamentals(sym, force_refresh=True)
                if merged and merged.get("float_shares"):
                    _warm_progress["ib_float"] += 1
            except Exception as exc:
                logger.debug("warm float %s: %s", sym, exc)
            if request.institutional:
                try:
                    pct = await refresh_institutional_ownership(sym, db=mongo_db)
                    if pct is not None:
                        _warm_progress["institutional"] += 1
                except Exception as exc:
                    logger.debug("warm institutional %s: %s", sym, exc)
            _warm_progress["done"] += 1
            await asyncio.sleep(request.throttle)
        _warm_progress["running"] = False
        _warm_progress["finished_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("[warm-fundamentals] complete: %s", dict(_warm_progress))

    import asyncio
    asyncio.get_event_loop().create_task(_sweep())
    return {"started": True, "total": len(uni),
            "institutional": request.institutional, "throttle": request.throttle}


@router.get("/warm-fundamentals/status")
def warm_fundamentals_status():
    return {"success": True, **_warm_progress}"""),
    ]),
}


def sha(t): return hashlib.sha256(t.encode()).hexdigest()[:16]


def main():
    if "--rollback" in sys.argv:
        for f in EDITS:
            bak = f.with_suffix(f.suffix + ".bak.v386")
            if bak.exists():
                f.write_text(bak.read_text()); bak.unlink(); print("ROLLED BACK", f)
        return
    check = "--check" in sys.argv
    plans = []
    for f, (marker, chunks) in EDITS.items():
        if not f.exists():
            print(f"ABORT: {f} not found (run from repo root)"); return
        t = f.read_text()
        print(f"{f.name}  PRE-SHA {sha(t)}")
        if marker in t:
            print(f"  already applied — skip"); continue
        new = t
        for i, (old, rep) in enumerate(chunks, 1):
            if old not in new:
                print(f"  ABORT: {f.name} chunk {i} anchor not found (DGX drift). Upload:")
                print(f"    curl --data-binary @{f} https://paste.rs/"); return
            new = new.replace(old, rep, 1)
        print(f"  POST-SHA(predicted) {sha(new)}")
        plans.append((f, t, new))
    if check:
        print("\n--check OK. Re-run without --check to apply."); return
    for f, old, new in plans:
        f.with_suffix(f.suffix + ".bak.v386").write_text(old)
        f.write_text(new)
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            f.write_text(old); print(f"COMPILE FAILED {f.name} — reverted:", e); return
        print(f"WROTE {f.name}")
    print("DONE. Restart backend, then POST /api/short-data/warm-fundamentals")


if __name__ == "__main__":
    main()
