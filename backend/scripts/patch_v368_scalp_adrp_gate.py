#!/usr/bin/env python3
"""patch_v368_scalp_adrp_gate.py — close the known-liquid bypass + add a
scalp/intraday ADRP (Average Daily Range %) movement floor.

WHY (operator audit 2026-06, diag v370/v372/v374):
  • `_known_liquid_symbols` unconditionally `return True`d the liquidity gate,
    so 92 high-$/thin-share megacaps (HON 2.2M sh, BLK 277k, …) SKIPPED the
    v322m scalp share-ADV floor entirely.
  • Index ETFs (EWT/IWF/FXI) PASS every volume floor but barely move
    (ADRP 1.2–2.3% vs 7–17% for real movers) — no $/share threshold catches
    them; only a movement (ADRP) floor does.

WHAT (all edits in backend/services/enhanced_scanner.py):
  1. Known-liquid no longer FULLY bypasses the gate; it only WAIVES the dollar
     floor on a genuine cache MISS. Scalp share/ADRP/RVOL proof ALWAYS runs.
  2. New `_scalp_min_adrp` knob (env SCALP_MIN_ADRP, default 2.0; 0 disables).
  3. New scalp/intraday ADRP check in the gate (after the share-ADV check).
  4. New `_get_adrp_for_gate` + `_compute_adrp_from_bars` (reads
     symbol_adv_cache.adrp_20d, falls back to a 20-bar ib_historical_data
     compute, memoized per (symbol, UTC-date)).

Decisions locked: ADRP floor 2.0%, KEEP the 3M share floor and $50M dollar
floor (all three must pass for scalp/intraday). Fully reversible via
SCALP_MIN_ADRP=0. Known-liquid set literal left intact (the bypass removal
already neutralizes its stale entries; cosmetic cleanup deferred).

Usage (repo root, DGX):
  .venv/bin/python patch_v368_scalp_adrp_gate.py --check     # dry-run, no write
  .venv/bin/python patch_v368_scalp_adrp_gate.py --apply     # writes + .bak + compile
"""
import hashlib
import os
import sys
import py_compile

TARGET = "backend/services/enhanced_scanner.py"
PRE_SHA = "0d9b24b150296d2bf252da31b2c3da9fe44bce47439d2ef2f958a1781327482a"

# ── EDIT 1 — drop the unconditional bypass ───────────────────────────────
E1_OLD = (
    "            # Known-liquid bypass (operator decision 2026-06-XX): a transient\n"
    "            # ADV cache miss on AAPL/SPY must not block a legit signal.\n"
    "            if symbol in self._known_liquid_symbols:\n"
    "                return True\n"
    "\n"
    "            tier, floor = self._liquidity_tier_floor(alert)"
)
E1_NEW = (
    "            # v368 — known-liquid no longer FULLY bypasses the gate. The old\n"
    "            # `return True` let high-$/thin-share megacaps (HON 2.2M sh, plus\n"
    "            # 92 names < 3M sh) skip the scalp share/ADRP proof entirely. It\n"
    "            # now only WAIVES the dollar floor on a genuine cache MISS\n"
    "            # (adv_dollar <= 0, handled below); the scalp share/ADRP/RVOL\n"
    "            # proof ALWAYS runs.\n"
    "            _known_liquid = symbol in self._known_liquid_symbols\n"
    "\n"
    "            tier, floor = self._liquidity_tier_floor(alert)"
)

# ── EDIT 2 — dollar floor: waive only on known-liquid cache MISS ──────────
E2_OLD = (
    "            if adv_dollar < floor:\n"
    "                reason = (\n"
    "                    f\"liquidity floor: avg_dollar_vol \""
)
E2_NEW = (
    "            if adv_dollar < floor and not (_known_liquid and adv_dollar <= 0):\n"
    "                reason = (\n"
    "                    f\"liquidity floor: avg_dollar_vol \""
)

# ── EDIT 3 — append ADRP movement check after the share-ADV check ─────────
E3_OLD = (
    "                    if reason is None and self._scalp_min_share_adv > 0:\n"
    "                        share_adv = await self._get_share_adv_for_gate(symbol)\n"
    "                        if share_adv < self._scalp_min_share_adv:\n"
    "                            reason = (\n"
    "                                f\"scalp share-ADV floor: \"\n"
    "                                f\"{'unknown/0' if share_adv <= 0 else f'{share_adv:,} sh/day'} \"\n"
    "                                f\"< {self._scalp_min_share_adv:,} sh/day\"\n"
    "                            )\n"
    "                            ctx_extra = {\"check\": \"scalp_share_adv\",\n"
    "                                         \"share_adv\": share_adv,\n"
    "                                         \"min_share_adv\": self._scalp_min_share_adv,\n"
    "                                         \"fail_closed\": share_adv <= 0}"
)
E3_NEW = E3_OLD + (
    "\n"
    "                    if reason is None and self._scalp_min_adrp > 0:\n"
    "                        adrp = await self._get_adrp_for_gate(symbol)\n"
    "                        if adrp < self._scalp_min_adrp:\n"
    "                            reason = (\n"
    "                                f\"scalp ADRP floor: \"\n"
    "                                f\"{'unmeasured' if adrp <= 0 else f'{adrp:.2f}%'} \"\n"
    "                                f\"< {self._scalp_min_adrp:g}% (low intraday \"\n"
    "                                f\"range \\u2014 poor scalp candidate)\"\n"
    "                            )\n"
    "                            ctx_extra = {\"check\": \"scalp_adrp\", \"adrp\": adrp,\n"
    "                                         \"min_adrp\": self._scalp_min_adrp,\n"
    "                                         \"fail_closed\": adrp <= 0}"
)

# ── EDIT 4 — add the SCALP_MIN_ADRP knob + cache in __init__ ──────────────
E4_OLD = (
    "        try:\n"
    "            self._scalp_min_rvol = float(\n"
    "                os.environ.get(\"SCALP_MIN_RVOL\", \"1.0\"))\n"
    "        except (TypeError, ValueError):\n"
    "            self._scalp_min_rvol = 1.0"
)
E4_NEW = E4_OLD + (
    "\n"
    "        # v368 — scalp/intraday ADRP (Average Daily Range %) floor. Index\n"
    "        # ETFs (EWT/IWF/FXI) & sleepy megacaps pass the volume floors but do\n"
    "        # NOT move enough to scalp. 0 disables. Sourced from\n"
    "        # symbol_adv_cache.adrp_20d with an ib_historical_data fallback.\n"
    "        try:\n"
    "            self._scalp_min_adrp = float(\n"
    "                os.environ.get(\"SCALP_MIN_ADRP\", \"2.0\"))\n"
    "        except (TypeError, ValueError):\n"
    "            self._scalp_min_adrp = 2.0\n"
    "        self._adrp_cache: Dict[str, Any] = {}"
)

# ── EDIT 5 — add _get_adrp_for_gate + _compute_adrp_from_bars helpers ─────
E5_OLD = (
    "        shares = await asyncio.to_thread(_sync_lookup)\n"
    "        if shares <= 0:\n"
    "            try:\n"
    "                shares = await self._fetch_single_adv(symbol)\n"
    "            except Exception:\n"
    "                shares = 0\n"
    "        return int(shares or 0)"
)
E5_NEW = E5_OLD + (
    "\n"
    "\n"
    "    async def _get_adrp_for_gate(self, symbol: str) -> float:\n"
    "        \"\"\"v368 \\u2014 Average Daily Range % (ADRP) for the scalp/intraday\n"
    "        movement floor. Reads symbol_adv_cache.adrp_20d first (warm-filled by\n"
    "        the IB collector), else computes on the fly. Memoized per\n"
    "        (symbol, UTC-date). Returns 0.0 when unprovable (caller treats that\n"
    "        as fail-closed for scalp/intraday).\"\"\"\n"
    "        from datetime import datetime, timezone\n"
    "        day = datetime.now(timezone.utc).strftime(\"%Y-%m-%d\")\n"
    "        cached = self._adrp_cache.get(symbol)\n"
    "        if cached and cached[0] == day:\n"
    "            return cached[1]\n"
    "\n"
    "        def _sync_lookup():\n"
    "            try:\n"
    "                from database import get_database\n"
    "                db = get_database()\n"
    "                if db is None:\n"
    "                    return None\n"
    "                doc = db[\"symbol_adv_cache\"].find_one(\n"
    "                    {\"symbol\": symbol}, {\"_id\": 0, \"adrp_20d\": 1})\n"
    "                v = (doc or {}).get(\"adrp_20d\")\n"
    "                return float(v) if isinstance(v, (int, float)) and v > 0 else None\n"
    "            except Exception:\n"
    "                return None\n"
    "\n"
    "        adrp = await asyncio.to_thread(_sync_lookup)\n"
    "        if adrp is None:\n"
    "            adrp = await self._compute_adrp_from_bars(symbol)\n"
    "        adrp = float(adrp or 0.0)\n"
    "        self._adrp_cache[symbol] = (day, adrp)\n"
    "        return adrp\n"
    "\n"
    "    async def _compute_adrp_from_bars(self, symbol: str, days: int = 20) -> float:\n"
    "        \"\"\"On-the-fly ADRP from the last `days` daily bars in\n"
    "        ib_historical_data: mean((high-low)/close)*100. 0.0 on miss.\"\"\"\n"
    "        def _sync():\n"
    "            try:\n"
    "                from database import get_database\n"
    "                db = getattr(self, \"db\", None) or get_database()\n"
    "                if db is None:\n"
    "                    return 0.0\n"
    "                bars = list(db[\"ib_historical_data\"].find(\n"
    "                    {\"symbol\": symbol, \"bar_size\": \"1 day\"},\n"
    "                    {\"_id\": 0, \"high\": 1, \"low\": 1, \"close\": 1, \"date\": 1}\n"
    "                ).sort([(\"date\", -1)]).limit(days))\n"
    "                rngs = []\n"
    "                for b in bars:\n"
    "                    h, lo, c = b.get(\"high\"), b.get(\"low\"), b.get(\"close\")\n"
    "                    if all(isinstance(x, (int, float)) for x in (h, lo, c)) and c > 0:\n"
    "                        rngs.append((h - lo) / c)\n"
    "                return (100.0 * sum(rngs) / len(rngs)) if rngs else 0.0\n"
    "            except Exception:\n"
    "                return 0.0\n"
    "        try:\n"
    "            return float(await asyncio.to_thread(_sync))\n"
    "        except Exception:\n"
    "            return 0.0"
)

EDITS = [
    ("E1 drop bypass", E1_OLD, E1_NEW),
    ("E2 dollar-floor waiver", E2_OLD, E2_NEW),
    ("E3 ADRP gate check", E3_OLD, E3_NEW),
    ("E4 SCALP_MIN_ADRP knob", E4_OLD, E4_NEW),
    ("E5 ADRP helpers", E5_OLD, E5_NEW),
]


def _resolve():
    if os.path.exists(TARGET):
        return TARGET
    alt = TARGET.replace("backend/", "")
    if os.path.exists(alt):
        return alt
    sys.exit(f"ERROR: cannot find {TARGET}")


def main():
    mode = "--check" if "--check" in sys.argv or "--apply" not in sys.argv else "--apply"
    path = _resolve()
    src = open(path, encoding="utf-8").read()
    cur = hashlib.sha256(src.encode("utf-8")).hexdigest()
    print(f"target        : {path}")
    print(f"whole-file SHA: {cur}")
    print(f"expected PRE  : {PRE_SHA}")
    if cur != PRE_SHA:
        if "--force" not in sys.argv:
            sys.exit("ABORT: PRE-SHA mismatch (DGX drifted). Re-extract & rebuild, "
                     "or pass --force if you've verified the anchors are intact.")
        print("WARN: PRE-SHA mismatch but --force given; proceeding on anchor counts.")

    ok = True
    for name, old, new in EDITS:
        n = src.count(old)
        flag = "OK" if n == 1 else "FAIL"
        if n != 1:
            ok = False
        print(f"  [{flag}] {name:<26} anchor count = {n} (need 1)")
    if not ok:
        sys.exit("ABORT: one or more anchors not found exactly once. No write.")

    if mode == "--check":
        # produce the would-be POST SHA without writing
        out = src
        for _, old, new in EDITS:
            out = out.replace(old, new, 1)
        post = hashlib.sha256(out.encode("utf-8")).hexdigest()
        try:
            compile(out, path, "exec")
            comp = "compile OK"
        except SyntaxError as e:
            comp = f"COMPILE ERROR: {e}"
        print(f"\n--check: all 5 anchors matched. would-be POST SHA = {post}")
        print(f"--check: syntax of patched source: {comp}")
        print("Re-run with --apply to write.")
        return

    out = src
    for _, old, new in EDITS:
        out = out.replace(old, new, 1)
    bak = path + ".v368.bak"
    open(bak, "w", encoding="utf-8").write(src)
    open(path, "w", encoding="utf-8").write(out)
    post = hashlib.sha256(out.encode("utf-8")).hexdigest()
    print(f"\nAPPLIED. backup: {bak}")
    print(f"POST SHA: {post}")
    try:
        py_compile.compile(path, doraise=True)
        print("py_compile: OK")
    except py_compile.PyCompileError as e:
        print(f"py_compile FAILED — restoring backup\n{e}")
        open(path, "w", encoding="utf-8").write(src)
        sys.exit("ABORT: restored original; patch produced invalid syntax.")
    print("\nNext: set SCALP_MIN_ADRP in backend env if you want a non-default "
          "floor (default 2.0), then restart the scanner/backend.")


if __name__ == "__main__":
    main()
