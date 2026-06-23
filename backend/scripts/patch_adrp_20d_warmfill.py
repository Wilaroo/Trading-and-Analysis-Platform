#!/usr/bin/env python3
"""patch_adrp_20d_warmfill.py — fast-path warm-fill for the scalp/intraday
ADRP (Average Daily Range %) movement floor.

WHY (operator backlog P1; v368 deferred this as the "fast-path"):
  v368 added a scalp/intraday ADRP floor. The gate's _get_adrp_for_gate reads
  `symbol_adv_cache.adrp_20d` FIRST (the fast-path), then falls back to an
  on-the-fly 20-bar ib_historical_data compute. But NOTHING ever wrote
  `adrp_20d` into the cache, so the fast-path was permanently dark: every
  scalp/intraday symbol paid a per-symbol synchronous Mongo compute each UTC
  day, and that fallback does NOT strip pre-listing / mistagged-bar pollution,
  so polluted names could read a wrong (often artificially low) ADRP → some
  valid scalp setups read "unmeasured"/below-floor and got rejected.

WHAT (1 file: backend/services/ib_historical_collector.py, rebuild_adv_from_ib_data):
  E1 — compute `adrp_20d` from the SAME cleaned 20-bar cohort already used for
       atr_pct (highs/lows/closes = pre-listing-filtered f_*[:20]):
       mean((high-low)/close)*100. Pollution-filtered → authoritative.
  E2 — persist it: add `"adrp_20d": round(adrp_20d, 4)` to the cache upsert.

  No scoring/exec/order/close path touched. The gate already prefers
  symbol_adv_cache.adrp_20d; once the rebuild writes it, the fast-path lights
  up and the (noisy) on-the-fly fallback is only used for cache misses. Fully
  additive + reversible (--rollback, or just ignore the new field).

AFTER APPLY: the nightly EOD ADV-cache rebuild (trading_scheduler
_run_adv_cache_rebuild) warm-fills adrp_20d automatically; to fill it NOW run
  POST /api/ib-collector/rebuild-adv-from-ib

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/patch_adrp_20d_warmfill.py --check     # dry-run, no write
  .venv/bin/python backend/scripts/patch_adrp_20d_warmfill.py --apply     # writes + .bak + compile
  .venv/bin/python backend/scripts/patch_adrp_20d_warmfill.py --rollback  # restore .bak
"""
import hashlib
import os
import sys
import py_compile

TARGET = "backend/services/ib_historical_collector.py"
PRE_SHA = "e44ee544d6ccceb28d7974850544d16d771f58af36ae9f2491b489b02ed72fec"
BAK_EXT = ".adrp_warmfill.bak"

# ── EDIT 1 — compute adrp_20d from the cleaned cohort (before tier calc) ──
E1_OLD = "\n".join([
    "                # Determine tier",
    "                tier = self.get_symbol_tier(avg_vol, avg_dollar_volume, atr_pct, symbol=symbol)",
])
E1_NEW = "\n".join([
    "                # adrp_20d warm-fill (fast-path) — Average Daily Range % over",
    "                # the cleaned 20-bar cohort: mean((high-low)/close)*100. Powers",
    "                # the scalp/intraday ADRP gate fast-path (enhanced_scanner.",
    "                # _get_adrp_for_gate reads symbol_adv_cache.adrp_20d before its",
    "                # on-the-fly ib_historical_data fallback). Reuses the SAME",
    "                # pre-listing-filtered cohort as atr_pct above, so it is",
    "                # pollution-clean (unlike the fallback) and authoritative.",
    "                adrp_20d = 0.0",
    "                _adrp_rngs = []",
    "                for _i in range(min(len(highs), len(lows), len(closes), 20)):",
    "                    _h = highs[_i] or 0",
    "                    _l = lows[_i] or 0",
    "                    _c = closes[_i] or 0",
    "                    if _h > 0 and _l > 0 and _c > 0:",
    "                        _adrp_rngs.append((_h - _l) / _c)",
    "                if _adrp_rngs:",
    "                    adrp_20d = 100.0 * sum(_adrp_rngs) / len(_adrp_rngs)",
    "",
    "                # Determine tier",
    "                tier = self.get_symbol_tier(avg_vol, avg_dollar_volume, atr_pct, symbol=symbol)",
])

# ── EDIT 2 — persist adrp_20d in the symbol_adv_cache upsert ──────────────
E2_OLD = "\n".join([
    '                        "atr_pct": round(atr_pct, 6),',
    '                        "latest_close": round(latest_close, 2),',
])
E2_NEW = "\n".join([
    '                        "atr_pct": round(atr_pct, 6),',
    '                        "adrp_20d": round(adrp_20d, 4),',
    '                        "latest_close": round(latest_close, 2),',
])

EDITS = [
    ("E1 compute adrp_20d", E1_OLD, E1_NEW),
    ("E2 persist adrp_20d", E2_OLD, E2_NEW),
]


def _resolve():
    if os.path.exists(TARGET):
        return TARGET
    alt = TARGET.replace("backend/", "")
    if os.path.exists(alt):
        return alt
    sys.exit(f"ERROR: cannot find {TARGET}")


def _rollback(path):
    bak = path + BAK_EXT
    if not os.path.exists(bak):
        sys.exit(f"ABORT: no backup found at {bak}")
    src = open(bak, encoding="utf-8").read()
    open(path, "w", encoding="utf-8").write(src)
    os.remove(bak)
    print(f"ROLLED BACK from {bak}")
    print(f"restored SHA: {hashlib.sha256(src.encode('utf-8')).hexdigest()}")


def main():
    path = _resolve()

    if "--rollback" in sys.argv:
        _rollback(path)
        return

    mode = "--apply" if "--apply" in sys.argv else "--check"
    src = open(path, encoding="utf-8").read()
    cur = hashlib.sha256(src.encode("utf-8")).hexdigest()
    print(f"target        : {path}")
    print(f"whole-file SHA: {cur}")
    print(f"expected PRE  : {PRE_SHA}")
    if cur != PRE_SHA:
        if "--force" not in sys.argv:
            sys.exit("ABORT: PRE-SHA mismatch (DGX drifted). Upload the live "
                     "rebuild_adv_from_ib_data extract so I can rebuild, or pass "
                     "--force if you've verified the anchors below are intact.")
        print("WARN: PRE-SHA mismatch but --force given; proceeding on anchor counts.")

    ok = True
    for name, old, new in EDITS:
        n = src.count(old)
        flag = "OK" if n == 1 else "FAIL"
        if n != 1:
            ok = False
        print(f"  [{flag}] {name:<22} anchor count = {n} (need 1)")
    if not ok:
        sys.exit("ABORT: one or more anchors not found exactly once. No write.")

    out = src
    for _, old, new in EDITS:
        out = out.replace(old, new, 1)
    post = hashlib.sha256(out.encode("utf-8")).hexdigest()

    if mode == "--check":
        try:
            compile(out, path, "exec")
            comp = "compile OK"
        except SyntaxError as e:
            comp = f"COMPILE ERROR: {e}"
        print(f"\n--check: all anchors matched. would-be POST SHA = {post}")
        print(f"--check: syntax of patched source: {comp}")
        print("Re-run with --apply to write.")
        return

    bak = path + BAK_EXT
    open(bak, "w", encoding="utf-8").write(src)
    open(path, "w", encoding="utf-8").write(out)
    print(f"\nAPPLIED. backup: {bak}")
    print(f"POST SHA: {post}")
    try:
        py_compile.compile(path, doraise=True)
        print("py_compile: OK")
    except py_compile.PyCompileError as e:
        print(f"py_compile FAILED — restoring backup\n{e}")
        open(path, "w", encoding="utf-8").write(src)
        sys.exit("ABORT: restored original; patch produced invalid syntax.")
    print("\nNext: commit, then warm-fill the cache:")
    print("  git add backend/services/ib_historical_collector.py && \\")
    print("    git commit -m 'adrp_20d warm-fill: collector writes scalp ADRP fast-path' && git push origin main")
    print("  ./start_backend.sh --force   # (or just restart the backend)")
    print("  curl -s -X POST http://localhost:8001/api/ib-collector/rebuild-adv-from-ib")
    print("Then verify with diag_adrp_warmfill.py — adrp_20d coverage should jump.")


if __name__ == "__main__":
    main()
