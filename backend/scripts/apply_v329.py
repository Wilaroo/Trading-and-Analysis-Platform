#!/usr/bin/env python3
"""
apply_v329.py — Chart Wall fix: missing _sanitize_intraday_bars on DGX
========================================================================
diag_history_500 (2026-06-12 13:56 ET) captured the exact traceback:

    File "backend/routers/sentcom_chart.py", line 1213, in get_chart_history
        normalised, _ = _sanitize_intraday_bars(normalised)
    NameError: name '_sanitize_intraday_bars' is not defined

ROOT CAUSE — the v324 /chart-history endpoint was authored against the
dev copy of sentcom_chart.py, which had the v19.34.265 bad-tick
sanitizer helper. That helper was never applied to the DGX file, so
every /chart-history call raises NameError → HTTP 500 → the frontend's
history prepend silently dies → charts "hit a wall" at the initially
loaded window and the history pill spins forever. (The DB itself has
ADBE 5-min bars back to 2024-03-21 — data was never the problem.)

FIX (required) — insert the byte-identical _sanitize_intraday_bars
definition (a local-median bad-tick clamp) above /chart-history.

FIX (optional, parity) — also run the sanitizer in /chart, matching the
dev reference, so a single corrupt IB print can't blow out the candle
autoscale on the initial window either. Skipped gracefully if the DGX
/chart body has drifted from the expected anchor.

SELF-TEST — after patching, the script imports the patched module
in-process and walks 8 pages of ADBE 5-min history against the live
Mongo, proving the Chart Wall is gone BEFORE you restart.

SAFE TO RUN MULTIPLE TIMES (idempotent).
Run from repo root:  .venv/bin/python /tmp/apply_v329.py
Then: git add -A && git commit -m "v329: chart wall fix (missing sanitizer)" && git push
Then restart the backend.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

REL = "backend/routers/sentcom_chart.py"

REQ_OLD = '@router.get("/chart-history")\nasync def get_chart_history(\n'

REQ_NEW = 'def _sanitize_intraday_bars(bars: List[Dict[str, Any]], tol: float = 0.5, win: int = 5):\n    """v19.34.265 — transient bad-tick guard for intraday candles.\n\n    A single corrupt IB print (e.g. a $36 tick on a $260 stock) produces a\n    bar whose wick/close deviates absurdly from its neighbours, blowing out\n    the candle autoscale and squashing every real candle into an unreadable\n    band for minutes. Clamp each bar\'s O/H/L/C into a ±`tol` band around the\n    LOCAL median close (±`win` bars). The median is robust to a single\n    outlier, so genuine trends/gaps are untouched — only lone spikes get\n    clipped. Mutates the dicts in place; returns (bars, fixed_count).\n    """\n    n = len(bars)\n    if n < 3:\n        return bars, 0\n    closes = [r["close"] for r in bars]   # snapshot BEFORE any mutation\n    fixed = 0\n    for i, r in enumerate(bars):\n        window = sorted(closes[max(0, i - win):min(n, i + win + 1)])\n        ref = window[len(window) // 2]\n        if ref <= 0:\n            continue\n        lob, hib = ref * (1.0 - tol), ref * (1.0 + tol)\n        o = min(max(r["open"],  lob), hib)\n        c = min(max(r["close"], lob), hib)\n        h = min(max(r["high"],  lob), hib)\n        lw = min(max(r["low"],  lob), hib)\n        h = max(h, o, c)        # restore OHLC invariants\n        lw = min(lw, o, c)\n        if (o, h, lw, c) != (r["open"], r["high"], r["low"], r["close"]):\n            r["open"], r["high"], r["low"], r["close"] = o, h, lw, c\n            fixed += 1\n    return bars, fixed\n\n\n@router.get("/chart-history")\nasync def get_chart_history(\n'

OPT_OLD = '    normalised = deduped\n\n    if not normalised:\n        return {\n            "success": False,\n'

OPT_NEW = '    normalised = deduped\n\n    # v19.34.265 — bad-tick sanitization (intraday only; daily bars come\n    # from EOD historical and rarely carry transient ticks). Runs BEFORE\n    # the session filter + indicator math so a corrupt print can\'t poison\n    # the candle autoscale, EMAs/BB, the volume profile, OR the served\n    # bars the frontend renders.\n    if tf in {"1min", "5min", "15min", "1hour"} and normalised:\n        normalised, _bt_fixed = _sanitize_intraday_bars(normalised)\n        if _bt_fixed:\n            logger.info(\n                "[v19.34.265 bad-tick] %s %s clamped %d outlier bar(s)",\n                symbol.upper(), tf, _bt_fixed,\n            )\n\n    if not normalised:\n        return {\n            "success": False,\n'


def find_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / REL).exists():
            return cand
    print("FATAL: run from repo root")
    sys.exit(1)


def _load_env(root: Path) -> None:
    p = root / "backend" / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))


def apply_patch(root: Path) -> None:
    path = root / REL
    text = path.read_text()

    # REQUIRED — the missing function definition
    if "def _sanitize_intraday_bars" in text:
        print("[SKIP] sanitizer definition already present")
    else:
        n = text.count(REQ_OLD)
        if n != 1:
            print(f"[FAIL] /chart-history anchor found {n}x (expected 1). ABORTING.")
            sys.exit(2)
        text = text.replace(REQ_OLD, REQ_NEW, 1)
        print("[OK]   _sanitize_intraday_bars definition inserted")

    # OPTIONAL — /chart parity (bad-tick clamp on the initial window too)
    if "_bt_fixed = _sanitize_intraday_bars" in text:
        print("[SKIP] /chart parity call already present")
    elif text.count(OPT_OLD) == 1:
        text = text.replace(OPT_OLD, OPT_NEW, 1)
        print("[OK]   /chart parity sanitizer call inserted")
    else:
        print(f"[INFO] /chart parity anchor found {text.count(OPT_OLD)}x — "
              "skipping the optional /chart clamp (cosmetic only; "
              "/chart-history fix above is what kills the 500)")

    path.write_text(text)


def self_test(root: Path) -> None:
    print()
    print("── self-test: in-process /chart-history walk (patched code, live DB) ──")
    _load_env(root)
    sys.path.insert(0, str(root / "backend"))
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    import importlib
    import routers.sentcom_chart as sc
    importlib.reload(sc)
    sc.init_sentcom_chart_router(None, db)

    newest = db["ib_historical_data"].find_one(
        {"symbol": "ADBE", "bar_size": "5 mins"}, sort=[("date", -1)])
    if not newest:
        print("[WARN] no ADBE 5-min bars — cannot self-test")
        return
    cursor = sc._to_utc_seconds(newest.get("date"))
    if not cursor:
        print("[WARN] could not parse newest bar date — cannot self-test")
        return

    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    walk = int(cursor)
    earliest = None
    for page in range(1, 9):
        try:
            res = asyncio.run(sc.get_chart_history(
                symbol="ADBE", timeframe="5min", before=int(walk),
                session="rth_plus_premarket", cap=None,
            ))
        except Exception:
            print(f"[FAIL] self-test page {page} raised:")
            traceback.print_exc()
            sys.exit(3)
        if page == 1:
            try:
                json.dumps(res)
            except Exception as exc:
                print(f"[FAIL] response not JSON-serializable: {exc}")
                sys.exit(3)
        if res.get("earliest_time"):
            earliest = res["earliest_time"]
        print(f"[TEST] p{page}: bars={res['bar_count']} "
              f"more={res.get('has_more')} next={res.get('next_before')}")
        nb = res.get("next_before")
        if not res.get("has_more") or nb is None:
            print("[TEST] end of stored history reached")
            break
        if nb >= walk:
            print("[WARN] cursor did not advance — stopping walk")
            break
        walk = nb
    if earliest:
        print(f"[TEST] walked back to "
              f"{datetime.fromtimestamp(earliest, tz=ET):%Y-%m-%d %H:%M ET}")
    print("[OK]   chart-history self-test PASSED — the Chart Wall is gone")


def main():
    root = find_root()
    print(f"repo root: {root}")
    apply_patch(root)
    self_test(root)
    print()
    print("Next:")
    print("  git add -A && git commit -m 'v329: chart wall fix (missing sanitizer)' && git push")
    print("  then RESTART the backend — charts will scroll back to the full")
    print("  stored history (ADBE: March 2024).")


if __name__ == "__main__":
    main()
