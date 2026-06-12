#!/usr/bin/env python3
"""
apply_v323b.py — Idempotent applier for v323b (daily-bar integrity / RVOL fix)
==============================================================================
ROOT CAUSE (probe r2, 2026-06-12): the DGX boots in the morning, the missed
nightly IB collection catch-up runs AFTER the open, and the collector
persists TODAY'S IN-PROGRESS daily bar as if complete:

    OXY '1 day' date=2026-06-11 vol=589,273  collected=2026-06-11T13:50:14Z
    (= the cumulative volume at 9:50 ET; a full OXY day is ~6-8M)

The scanner's F7 guard correctly treats a prior-day bar as complete
(session-fraction=1.0), so RVOL = 589K / 6.9M avg = 0.09x → EVERY setup
RVOL-blocked for the whole session (the 2026-06-12 "no scalps" incident).
SPY's 06-09 row (collected 12:24 ET that day) is the same poison.

THE FIX (two parts):
  1. PREVENTION — `_is_inprogress_daily_bar()` guard added to ALL THREE
     bar-write sites in ib_historical_collector.py: a daily bar dated
     TODAY (ET) is only persisted after the close (>= 16:15 ET).
     Intraday bar sizes are untouched. Morning catch-up runs become safe.
  2. REPAIR — this patcher scans ib_historical_data '1 day' rows and
     DELETES every partial row (collected_at on the SAME ET day as the
     bar, before 16:15 ET). The next collection run refetches those days
     complete.

Writes backend/tests/test_v323b_daily_bar_integrity.py.
SAFE TO RUN MULTIPLE TIMES (marker-guarded; repair is idempotent).

Run from repo root:  .venv/bin/python /tmp/apply_v323b.py
Then: git add -A && git commit -m "v323b: never persist in-progress daily bars (RVOL fix)" && git push
(commit BEFORE restarting — StartTrading.bat does `git checkout -- .`)
NOTE: backend restart picks up the guard; deleted days refetch on the
next collection run (tonight's catch-up or a manual run after the close).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

MARKER = "_is_inprogress_daily_bar"
REL = "backend/services/ib_historical_collector.py"

HELPER = '''    @staticmethod
    def _is_inprogress_daily_bar(bar_size: str, bar_date) -> bool:
        """v323b — True when this DAILY bar is TODAY'S still-in-progress ET
        session. Persisting it poisons RVOL: a catch-up collection running
        after the open wrote e.g. OXY 2026-06-11 vol=589,273 (the cumulative
        volume at 9:50 ET) as a COMPLETE day; the scanner's F7 prior-day
        guard then computed RVOL = partial/avg = 0.09x and blocked every
        setup for the whole session (2026-06-12 no-scalps incident).
        Today's daily bar is only safe after the close (>= 16:15 ET)."""
        try:
            if "day" not in str(bar_size).lower():
                return False
            s = str(bar_date or "")[:10].replace("/", "-")
            if len(s) >= 8 and s[:8].isdigit():
                s = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo("America/New_York"))
            if s[:10] != now_et.strftime("%Y-%m-%d"):
                return False
            return (now_et.hour, now_et.minute) < (16, 15)
        except Exception:
            return False

'''

CHUNKS = [
    (
        "helper_method",
        '''    async def _collect_symbol_data(
        self, 
        symbol: str, 
        bar_size: str, 
        duration: str
    ) -> int:
''',
        HELPER + '''    async def _collect_symbol_data(
        self, 
        symbol: str, 
        bar_size: str, 
        duration: str
    ) -> int:
''',
    ),
    (
        "guard_store_completed",
        '''            bar_size = item.get("bar_size", job.bar_size)
            bars = item.get("data", [])
            
            if not bars:
                continue
            
            for bar in bars:
                try:
                    self._data_col.update_one(
''',
        '''            bar_size = item.get("bar_size", job.bar_size)
            bars = item.get("data", [])
            
            if not bars:
                continue
            
            for bar in bars:
                try:
                    # v323b — never persist today's in-progress daily bar
                    if self._is_inprogress_daily_bar(bar_size, bar.get("date") or bar.get("time")):
                        continue
                    self._data_col.update_one(
''',
    ),
    (
        "guard_store_all_completed",
        '''            bar_size = item.get("bar_size", "1 day")
            bars = item.get("data", [])
            request_id = item.get("request_id")
            
            if not bars:
                continue
            
            for bar in bars:
                try:
                    self._data_col.update_one(
''',
        '''            bar_size = item.get("bar_size", "1 day")
            bars = item.get("data", [])
            request_id = item.get("request_id")
            
            if not bars:
                continue
            
            for bar in bars:
                try:
                    # v323b — never persist today's in-progress daily bar
                    if self._is_inprogress_daily_bar(bar_size, bar.get("date") or bar.get("time")):
                        continue
                    self._data_col.update_one(
''',
    ),
    (
        "guard_collect_symbol",
        '''                    # Store in database
                    if self._data_col is not None:
                        for bar in bars:
                            try:
                                self._data_col.update_one(
''',
        '''                    # Store in database
                    if self._data_col is not None:
                        for bar in bars:
                            try:
                                # v323b — never persist today's in-progress daily bar
                                if self._is_inprogress_daily_bar(bar_size, bar.get("date") or bar.get("time")):
                                    continue
                                self._data_col.update_one(
''',
    ),
]

TEST_REL = Path("backend") / "tests" / "test_v323b_daily_bar_integrity.py"

TEST_CONTENT = '''"""v323b — never persist today's in-progress daily bar.

A morning catch-up collection wrote partial today-bars (OXY 06-11
vol=589,273 collected 9:50 ET) which the scanner's F7 guard treated as
complete prior days → RVOL 0.09x → every setup blocked all session.
Verifies the guard helper exists and protects ALL THREE bar-write sites.
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "ib_historical_collector.py").exists():
            return c
    raise AssertionError("repo root not found")


SRC = _repo_root() / "backend" / "services" / "ib_historical_collector.py"
TEXT = SRC.read_text()


def test_guard_helper_exists():
    assert "def _is_inprogress_daily_bar(bar_size: str, bar_date) -> bool:" in TEXT
    assert '"day" not in str(bar_size).lower()' in TEXT
    assert "(16, 15)" in TEXT  # only complete after 16:15 ET


def test_all_three_write_sites_guarded():
    # 1 def + 3 call sites
    assert TEXT.count("_is_inprogress_daily_bar(") == 4
    # every update_one on the bar collection is preceded by the guard
    assert TEXT.count("# v323b — never persist today's in-progress daily bar") == 3


def test_intraday_bars_not_affected():
    # the guard short-circuits on bar_size: only '1 day' style sizes match
    i = TEXT.index("def _is_inprogress_daily_bar")
    block = TEXT[i:i + 1600]
    assert "return False" in block.split("ZoneInfo")[0]


def test_file_compiles():
    py_compile.compile(str(SRC), doraise=True)
'''


def _repo_root() -> Path:
    for c in (Path.cwd(), Path.home() / "Trading-and-Analysis-Platform"):
        if (c / REL).exists():
            return c
    print("ERROR: could not locate repo root."); sys.exit(1)


def _load_env(root: Path) -> dict:
    env = {}
    p = root / "backend" / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _repair_partial_daily_rows(root: Path) -> None:
    """DELETE '1 day' rows collected DURING the bar's own ET session
    (before 16:15 ET) — they hold partial volume/OHLC. Next collection
    run refetches them complete."""
    env = _load_env(root)
    if not env.get("MONGO_URL"):
        print("⚠ MONGO_URL not in backend/.env — repair SKIPPED."); return
    from pymongo import MongoClient
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    col = MongoClient(env["MONGO_URL"])[env.get("DB_NAME", "tradecommand")]["ib_historical_data"]

    scanned = 0
    bad = []
    cur = col.find({"bar_size": "1 day"},
                   {"_id": 1, "symbol": 1, "date": 1, "volume": 1, "collected_at": 1},
                   batch_size=5000)
    for r in cur:
        scanned += 1
        if scanned % 250000 == 0:
            print(f"  …scanned {scanned:,} daily rows, {len(bad)} partial so far")
        ca = r.get("collected_at")
        if not ca:
            continue
        try:
            dt = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            et = dt.astimezone(ET)
        except (ValueError, TypeError):
            continue
        d = str(r.get("date") or "")[:10].replace("/", "-")
        if len(d) >= 8 and d[:8].isdigit() and "-" not in d[:8]:
            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if d[:10] == et.strftime("%Y-%m-%d") and (et.hour, et.minute) < (16, 15):
            bad.append(r)

    print(f"✓ repair scan: {scanned:,} '1 day' rows, {len(bad)} PARTIAL rows found")
    if not bad:
        return
    by_sym = {}
    for r in bad:
        by_sym.setdefault(r.get("symbol"), []).append(r)
    for sym in sorted(by_sym, key=lambda s: -len(by_sym[s]))[:15]:
        rows = by_sym[sym]
        days = ", ".join(sorted({str(r.get('date'))[:10] for r in rows})[:4])
        print(f"    {sym}: {len(rows)} partial ({days}) e.g. vol={rows[0].get('volume'):,}")
    if len(by_sym) > 15:
        print(f"    … +{len(by_sym) - 15} more symbols")
    res = col.delete_many({"_id": {"$in": [r["_id"] for r in bad]}})
    print(f"✓ deleted {res.deleted_count} partial daily rows — next collection run "
          f"refetches them complete (run one after today's close, or let the "
          f"morning catch-up do it — it is now safe).")


def main() -> None:
    root = _repo_root()
    path = root / REL
    text = path.read_text()

    if MARKER in text:
        print(f"⏭  {REL} already patched (no-op).")
    else:
        problems = []
        for name, old, _new in CHUNKS:
            n = text.count(old)
            if n != 1:
                problems.append(f"  ✗ chunk {name!r}: anchor matched {n}× (expected 1)")
        if problems:
            print("ANCHOR DRIFT — NO changes made:")
            print("\n".join(problems))
            sys.exit(1)
        for name, old, new in CHUNKS:
            text = text.replace(old, new)
            print(f"✓ applied chunk: {name}")
        path.write_text(text)

    import py_compile
    py_compile.compile(str(path), doraise=True)
    print("✓ ib_historical_collector.py compiles")

    test_path = root / TEST_REL
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST_CONTENT)
    print(f"✓ wrote {TEST_REL}")

    _repair_partial_daily_rows(root)

    print("\nNext:")
    print("  .venv/bin/python -m pytest backend/tests/test_v323b_daily_bar_integrity.py -q")
    print('  git add -A && git commit -m "v323b: never persist in-progress daily bars (RVOL fix)" && git push')
    print("  RESTART the backend. RVOL will read ~1.0x from yesterday-complete bars")
    print("  immediately; full freshness returns after the next collection run.")


if __name__ == "__main__":
    main()
