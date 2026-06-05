#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_symbol_trace_v281.py — IDEMPOTENT applier for v19.34.281
"symbol-trace + silent pre-RVOL drop visibility".

WHAT IT DOES (all additive, no gating logic changed):
  1. enhanced_scanner.py
     - adds `_symbols_skipped_no_data` counter + `_symbol_last_eval` dict
     - adds `_record_symbol_eval()` helper
     - makes the SILENT `if not snapshot: return` drop LOUD (counter + trace
       + scanner thought) and traces rvol_skip / in_play_skip / scanned
     - surfaces `symbols_skipped_no_data` in get_in_play_health()
  2. routers/scanner.py
     - adds GET /api/scanner/symbol-trace?symbol=XXX
  3. writes backend/scripts/probe_symbol_day.py

SAFE: read-modify of two files + one new script. Touches no order logic,
no open positions. Re-running is a no-op (idempotent).

RUN ON DGX (from repo root ~/Trading-and-Analysis-Platform):
    .venv/bin/python /tmp/apply_symbol_trace_v281.py            # apply
    .venv/bin/python /tmp/apply_symbol_trace_v281.py --dry-run  # preview
then:
    ./start_backend.sh --force
"""
import argparse
import os
import shutil
import sys
from datetime import datetime

BAK_SUFFIX = ".bak.symtrace0605"

REPO = os.getcwd()
SCANNER = os.path.join(REPO, "backend/services/enhanced_scanner.py")
ROUTER = os.path.join(REPO, "backend/routers/scanner.py")
PROBE = os.path.join(REPO, "backend/scripts/probe_symbol_day.py")

# ───────────────────────── edit definitions ─────────────────────────
# Each: (path, marker, old, new). `marker` present ⇒ already applied (skip).

EDITS = []

# --- enhanced_scanner.py : __init__ state ---
EDITS.append((SCANNER, "self._symbol_last_eval = {}",
'''        self._symbols_skipped_rvol = 0
        self._symbols_skipped_adv = 0  # Skipped due to low volume
        self._symbols_skipped_in_play = 0  # Skipped due to strict in-play gate''',
'''        self._symbols_skipped_rvol = 0
        self._symbols_skipped_adv = 0  # Skipped due to low volume
        self._symbols_skipped_in_play = 0  # Skipped due to strict in-play gate
        # v19.34.281 — per-symbol scan-trace + no-data counter. `no_data` was a
        # SILENT drop pre-v281 (snapshot None -> bare return); now counted +
        # traced + narrated so missing-bars symbols are visible in symbol-trace.
        self._symbols_skipped_no_data = 0
        self._symbol_last_eval = {}'''))

# --- enhanced_scanner.py : counter reset ---
EDITS.append((SCANNER, "self._symbols_skipped_no_data = 0  # v19.34.281",
'''        # Reset counters
        self._symbols_skipped_rvol = 0
        self._symbols_skipped_adv = 0
        self._symbols_skipped_in_play = 0''',
'''        # Reset counters
        self._symbols_skipped_rvol = 0
        self._symbols_skipped_adv = 0
        self._symbols_skipped_in_play = 0
        self._symbols_skipped_no_data = 0  # v19.34.281'''))

# --- enhanced_scanner.py : helper method before get_in_play_health ---
EDITS.append((SCANNER, "def _record_symbol_eval(self, symbol, stage, **fields):",
'''    def get_in_play_health(self, sample: int = 8) -> Dict:''',
'''    def _record_symbol_eval(self, symbol, stage, **fields):
        """v19.34.281 — record the last scan outcome for one symbol so
        `/api/scanner/symbol-trace` can answer why a symbol did/didn't alert.
        One entry per symbol (bounded by universe size). Never raises."""
        try:
            entry = {
                "symbol": str(symbol).upper(),
                "stage": stage,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            entry.update(fields)
            self._symbol_last_eval[str(symbol).upper()] = entry
        except Exception:
            pass

    def get_in_play_health(self, sample: int = 8) -> Dict:'''))

# --- enhanced_scanner.py : in-play-health qualify dict ---
EDITS.append((SCANNER, '"symbols_skipped_no_data": int(getattr(self, "_symbols_skipped_no_data"',
'''            "symbols_skipped_rvol": int(getattr(self, "_symbols_skipped_rvol", 0) or 0),
            "symbols_skipped_adv": int(getattr(self, "_symbols_skipped_adv", 0) or 0),''',
'''            "symbols_skipped_rvol": int(getattr(self, "_symbols_skipped_rvol", 0) or 0),
            "symbols_skipped_no_data": int(getattr(self, "_symbols_skipped_no_data", 0) or 0),  # v19.34.281
            "symbols_skipped_adv": int(getattr(self, "_symbols_skipped_adv", 0) or 0),'''))

# --- enhanced_scanner.py : snapshot-None silent drop + rvol_skip trace ---
EDITS.append((SCANNER, 'self._record_symbol_eval(\n                    symbol, "no_data",',
'''            if not snapshot:
                return
            
            # Skip low RVOL stocks (second filter after ADV)
            if snapshot.rvol < self._min_rvol_filter:
                self._symbols_skipped_rvol += 1
                # v19.34.26 — surface RVOL gating so the operator sees''',
'''            if not snapshot:
                # v19.34.281 — was a SILENT drop. Now counted + traced + narrated
                # so "no intraday bars" symbols stop vanishing without a trace.
                self._symbols_skipped_no_data += 1
                self._record_symbol_eval(
                    symbol, "no_data",
                    reason="get_technical_snapshot returned None (no/insufficient mongo bars)",
                )
                try:
                    await self._emit_scanner_thought(
                        symbol=symbol, kind="skip",
                        text=f"\u26aa {symbol} skipped — no intraday bars (snapshot unavailable)",
                        filter="no_data",
                    )
                except Exception:
                    pass
                return
            
            # Skip low RVOL stocks (second filter after ADV)
            if snapshot.rvol < self._min_rvol_filter:
                self._symbols_skipped_rvol += 1
                self._record_symbol_eval(
                    symbol, "rvol_skip",
                    rvol=round(float(snapshot.rvol), 3), min_rvol=self._min_rvol_filter,
                )
                # v19.34.26 — surface RVOL gating so the operator sees'''))

# --- enhanced_scanner.py : scanned (passed pre-filters) trace ---
EDITS.append((SCANNER, 'symbol, "scanned", rvol=round(float(snapshot.rvol), 3),',
'''            # Update caches with fresh data
            now = datetime.now(timezone.utc)
            self._rvol_cache[symbol] = (snapshot.rvol, now)''',
'''            # Update caches with fresh data
            now = datetime.now(timezone.utc)
            self._rvol_cache[symbol] = (snapshot.rvol, now)
            self._record_symbol_eval(  # v19.34.281 — passed ADV+RVOL pre-filters
                symbol, "scanned", rvol=round(float(snapshot.rvol), 3),
            )'''))

# --- enhanced_scanner.py : in_play strict-gate trace ---
EDITS.append((SCANNER, 'symbol, "in_play_skip",',
'''                    self._symbols_skipped_in_play += 1
                    # v19.34.26 — narrate the strict-gate rejection so''',
'''                    self._symbols_skipped_in_play += 1
                    self._record_symbol_eval(  # v19.34.281
                        symbol, "in_play_skip",
                        score=getattr(in_play_qual, "score", None),
                    )
                    # v19.34.26 — narrate the strict-gate rejection so'''))

# --- routers/scanner.py : new /symbol-trace endpoint ---
EDITS.append((ROUTER, 'def get_symbol_trace(symbol: str):',
'''@router.get("/ev-leaderboard")
def get_ev_leaderboard(days: int = 30):''',
'''@router.get("/symbol-trace")
def get_symbol_trace(symbol: str):
    """v19.34.281 — per-symbol scan forensics. Answers "did the live scanner
    see/scan/skip SYMBOL today, and why didn't it alert" in ONE call.

    Joins the live scanner's in-memory state (universe membership, tier,
    last wave, RVOL cache, last-eval trace) with today's mongo alert/trade
    counts, then emits a plain-language verdict. Read-only — never mutates.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol required")

    try:
        from services.enhanced_scanner import get_enhanced_scanner
        sc = get_enhanced_scanner()
    except Exception:
        sc = None
    if not sc:
        return {"success": True, "symbol": sym, "running": False,
                "verdict": "scanner not initialized",
                "message": "Enhanced scanner not initialized"}

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    # 1) Universe membership (ADV intraday floor) + tier.
    in_universe = None
    tier = None
    try:
        from services.symbol_universe import get_universe
        in_universe = sym in get_universe(sc.db, tier="intraday")
    except Exception:
        pass
    try:
        tier = (getattr(sc, "_tier_cache", {}) or {}).get(sym)
    except Exception:
        pass

    # 2) Last wave membership (was it dispatched this cycle?).
    in_last_wave = None
    try:
        batch = getattr(sc, "_last_wave_batch", None) or {}
        wave_syms = set()
        for k in ("tier1_watchlist", "tier2_high_rvol", "tier3_wave"):
            wave_syms.update(batch.get(k, []) or [])
        in_last_wave = sym in wave_syms
    except Exception:
        pass

    # 3) RVOL cache state.
    rvol_val = rvol_age = rvol_fresh = None
    try:
        rc = (getattr(sc, "_rvol_cache", {}) or {}).get(sym)
        if rc:
            rv, ts = rc
            rvol_val = round(float(rv), 3)
            rvol_age = round((now - ts).total_seconds(), 1)
            rvol_fresh = rvol_age <= float(getattr(sc, "_rvol_cache_ttl", 300) or 300)
    except Exception:
        pass

    # 4) Last per-symbol eval trace (v19.34.281).
    last_eval = None
    try:
        last_eval = (getattr(sc, "_symbol_last_eval", {}) or {}).get(sym)
    except Exception:
        pass

    # 5) Today's alert/trade counts (created_at is ISO string -> lexical >= works).
    today = now.strftime("%Y-%m-%d")
    counts = {}
    try:
        db = sc.db
        for c in ("live_alerts", "alerts", "shadow_decisions", "rejection_events", "bot_trades"):
            counts[c] = int(db[c].count_documents(
                {"symbol": sym, "created_at": {"$gte": today}}))
    except Exception:
        pass

    # 6) Plain-language verdict.
    verdict = "unknown"
    if in_universe is False:
        verdict = (f"NOT IN UNIVERSE — {sym} is below the intraday ADV floor "
                   "($50M/day) in symbol_adv_cache")
    elif last_eval is None:
        verdict = (f"NOT SCANNED — {sym} is in the universe but the wave never "
                   "dispatched it this session (tier rotation / not in wave)")
    else:
        st = last_eval.get("stage")
        if st == "no_data":
            verdict = (f"DROPPED @ no_data — no intraday mongo bars for {sym} "
                       "(turbo-collector gap / cold cache). Setup was invisible.")
        elif st == "rvol_skip":
            verdict = (f"DROPPED @ rvol_skip — RVOL {last_eval.get('rvol')} < floor "
                       f"{last_eval.get('min_rvol')} (liquid by ADV, just not 'in play' today)")
        elif st == "in_play_skip":
            verdict = f"DROPPED @ in_play_strict_gate — score {last_eval.get('score')}"
        elif st == "scanned":
            if counts.get("live_alerts", 0) > 0:
                verdict = (f"SCANNED & ALERTED — {counts.get('live_alerts')} alert(s) today; "
                           "if no trade, check priority/tape/TQS gate or rejection-events")
            else:
                verdict = ("SCANNED, NO ALERT — passed ADV+RVOL pre-filters but no detector "
                           "fired (the setup pattern wasn't present per the bot's read)")

    return {
        "success": True, "symbol": sym, "running": True,
        "verdict": verdict,
        "in_universe": in_universe, "tier": tier, "in_last_wave": in_last_wave,
        "rvol": {"value": rvol_val, "age_seconds": rvol_age, "fresh": rvol_fresh,
                 "min_filter": float(getattr(sc, "_min_rvol_filter", 0) or 0)},
        "last_eval": last_eval,
        "today_counts": counts,
        "timestamp": now.isoformat(),
    }


@router.get("/ev-leaderboard")
def get_ev_leaderboard(days: int = 30):'''))


PROBE_SRC = '''#!/usr/bin/env python3
"""
probe_symbol_day.py — one-shot per-symbol scan forensics (v19.34.281).

Answers "did our bot see / scan / skip SYMBOL today, and why didn't it
trade it" in a single command by reading the live scanner's
`/api/scanner/symbol-trace` endpoint (in-memory scanner state joined with
today's mongo alert/trade counts) and printing a verdict chain.

Usage (on the DGX, backend running):
    .venv/bin/python backend/scripts/probe_symbol_day.py TSLA
    .venv/bin/python backend/scripts/probe_symbol_day.py NVDA --base http://localhost:8001

Read-only. Touches no order logic and no open positions.
"""
import argparse
import json
import sys
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", help="ticker, e.g. TSLA")
    ap.add_argument("--base", default="http://localhost:8001",
                    help="backend base URL (default http://localhost:8001)")
    args = ap.parse_args()

    sym = args.symbol.upper()
    url = f"{args.base}/api/scanner/symbol-trace?symbol={sym}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
    except Exception as e:
        print(f"[ERROR] GET {url} failed: {e}")
        sys.exit(1)

    if not data.get("running", False):
        print(f"\\n{sym}: scanner not running / not initialized — "
              f"{data.get('message', 'no detail')}\\n")
        return

    rv = data.get("rvol", {}) or {}
    le = data.get("last_eval")
    tc = data.get("today_counts", {}) or {}

    print(f"\\n=== symbol-trace: {sym} ===")
    print(f"VERDICT : {data.get('verdict')}")
    print("-" * 60)
    print(f"universe: in_universe={data.get('in_universe')}  "
          f"tier={data.get('tier')}  in_last_wave={data.get('in_last_wave')}")
    print(f"rvol    : value={rv.get('value')}  age={rv.get('age_seconds')}s  "
          f"fresh={rv.get('fresh')}  floor={rv.get('min_filter')}")
    if le:
        extra = {k: v for k, v in le.items() if k not in ("symbol", "stage", "ts")}
        print(f"last_eval: stage={le.get('stage')}  at={le.get('ts')}  {extra}")
    else:
        print("last_eval: <none> — symbol never entered _scan_symbol_all_setups this session")
    print(f"today   : live_alerts={tc.get('live_alerts', 0)}  "
          f"alerts={tc.get('alerts', 0)}  shadow={tc.get('shadow_decisions', 0)}  "
          f"rejections={tc.get('rejection_events', 0)}  bot_trades={tc.get('bot_trades', 0)}")
    print()


if __name__ == "__main__":
    main()
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run
    tag = "[DRY-RUN] " if dry else ""

    for p in (SCANNER, ROUTER):
        if not os.path.isfile(p):
            print(f"[FATAL] not found: {p}\n  → run from repo root (~/Trading-and-Analysis-Platform)")
            sys.exit(2)

    backed_up = set()
    errors = 0
    applied = 0
    skipped = 0

    # group edits by file so we read/write once
    by_file = {}
    for path, marker, old, new in EDITS:
        by_file.setdefault(path, []).append((marker, old, new))

    for path, edits in by_file.items():
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        orig = text
        for marker, old, new in edits:
            if marker in text:
                print(f"  [skip] already applied: {os.path.basename(path)} :: {marker[:48]}")
                skipped += 1
                continue
            if old not in text:
                print(f"  [ERROR] anchor not found in {os.path.basename(path)} :: {marker[:48]}")
                errors += 1
                continue
            text = text.replace(old, new, 1)
            print(f"  [apply] {os.path.basename(path)} :: {marker[:48]}")
            applied += 1
        if text != orig and not dry:
            bak = path + BAK_SUFFIX
            if path not in backed_up and not os.path.exists(bak):
                shutil.copy2(path, bak)
                print(f"  [backup] {bak}")
            backed_up.add(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

    # probe script
    if os.path.exists(PROBE):
        print(f"  [skip] probe exists: {PROBE}")
    elif not dry:
        os.makedirs(os.path.dirname(PROBE), exist_ok=True)
        with open(PROBE, "w", encoding="utf-8") as f:
            f.write(PROBE_SRC)
        print(f"  [write] {PROBE}")
    else:
        print(f"  [would-write] {PROBE}")

    print(f"\n{tag}done — applied={applied} skipped={skipped} errors={errors}")
    if errors:
        print("  ⚠ anchors missing — file may already be on a newer/older version; NOTHING written for those.")
        sys.exit(1)
    if not dry:
        print("  → now restart:  ./start_backend.sh --force")
        print("  → then:        .venv/bin/python backend/scripts/probe_symbol_day.py TSLA")


if __name__ == "__main__":
    main()
