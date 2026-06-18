#!/usr/bin/env python3
"""patch_v388 — fix warm-fundamentals sweep ORDER so institutional lands in the pillar's doc.
Was: get_cached_fundamentals (merges institutional) ran BEFORE refresh_institutional_ownership
(writes it) → institutional merged one pass late (lived only in institutional_ownership_cache,
not symbol_fundamentals_cache → live pillar blind until 48h TTL). Now: refresh institutional
FIRST (skip if <7d fresh → cheap re-runs, no multi-MB re-pull), THEN get_cached_fundamentals merges
it the same pass. Anchored, py_compile-gated, .bak + --rollback. Run from repo root:
  .venv/bin/python backend/scripts/patch_v388_warmfill_order.py --check | (apply) | --rollback
"""
import hashlib, py_compile, sys
from pathlib import Path

F = next((p for p in (Path("backend/routers/short_data.py"),
                      Path("routers/short_data.py")) if p.exists()),
         Path("backend/routers/short_data.py"))
MARKER = "v388 — refresh institutional FIRST"

OLD = '''        for sym in uni:
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
            await asyncio.sleep(request.throttle)'''

NEW = '''        for sym in uni:
            # v388 — refresh institutional FIRST so get_cached_fundamentals merges
            # it into symbol_fundamentals_cache on the SAME pass; skip if already
            # fresh (<7d) so re-runs are cheap and don't re-pull multi-MB reports.
            if request.institutional:
                try:
                    ex = mongo_db.institutional_ownership_cache.find_one(
                        {"symbol": sym}, {"fetched_at": 1})
                    fa = ex.get("fetched_at") if ex else None
                    fresh = fa is not None and (datetime.now(timezone.utc) - fa).days < 7
                    if fresh:
                        _warm_progress["institutional"] += 1
                    else:
                        pct = await refresh_institutional_ownership(sym, db=mongo_db)
                        if pct is not None:
                            _warm_progress["institutional"] += 1
                except Exception as exc:
                    logger.debug("warm institutional %s: %s", sym, exc)
            try:
                merged = await get_cached_fundamentals(sym, force_refresh=True)
                if merged and merged.get("float_shares"):
                    _warm_progress["ib_float"] += 1
            except Exception as exc:
                logger.debug("warm float %s: %s", sym, exc)
            _warm_progress["done"] += 1
            await asyncio.sleep(request.throttle)'''


def sha(t): return hashlib.sha256(t.encode()).hexdigest()[:16]


def main():
    if "--rollback" in sys.argv:
        bak = F.with_suffix(".py.bak.v388")
        if bak.exists():
            F.write_text(bak.read_text()); bak.unlink(); print("ROLLED BACK", F)
        else:
            print("no .bak.v388 backup")
        return
    if not F.exists():
        print("ABORT: run from repo root (short_data.py not found)"); return
    t = F.read_text()
    print(f"PRE-SHA {sha(t)}")
    if MARKER in t:
        print("already applied — skip"); return
    if OLD not in t:
        print("ABORT: anchor not found (DGX drift). Upload:")
        print("  curl --data-binary @backend/routers/short_data.py https://paste.rs/"); return
    new = t.replace(OLD, NEW, 1)
    if "--check" in sys.argv:
        print(f"POST-SHA(predicted) {sha(new)} — Re-run without --check."); return
    F.with_suffix(".py.bak.v388").write_text(t)
    F.write_text(new)
    try:
        py_compile.compile(str(F), doraise=True)
    except py_compile.PyCompileError as e:
        F.write_text(t); print("COMPILE FAILED — reverted:", e); return
    print(f"WROTE {F}  POST-SHA {sha(new)} (backup .py.bak.v388). Restart backend to load.")


if __name__ == "__main__":
    main()
