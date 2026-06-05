#!/usr/bin/env python3
"""
probe_inplay_health.py  (read-only, best DURING MARKET HOURS)
=============================================================
Shows the live scanner's IN-PLAY HEALTH per scan cycle:

  1. WAVE COMPOSITION — tier1/tier2/tier3 sizes (+ a small symbol sample)
     of the live wave batch, and the wave-rotation progress through the
     universe. Tells you whether the bot is actually rotating coverage
     or stuck on a stale slice.
  2. RVOL FRESHNESS — how stale the per-symbol RVOL cache is (oldest /
     newest entry age, % fresh within TTL, fraction passing the min-RVOL
     gate). A scanner sizing scalps off stale RVOL is a silent edge-killer.
  3. QUALIFY-RATE PER CYCLE — detector evaluations vs hits, diffed across
     successive polls so you see the TRUE per-cycle qualify-rate (not just
     the cumulative average), plus scanned / skipped(rvol/adv/in-play)
     counts and scan cadence.

Polls GET /api/scanner/in-play-health `--samples` times, `--gap` seconds
apart, and prints a per-cycle table + a summary. Read-only HTTP to the
local backend.

Usage:
  python3 probe_inplay_health.py --samples 5 --gap 20
  curl -s <raw-url> | python3 - --base http://localhost:8001 --samples 5 --gap 20
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone


def _c(txt, code):
    return f"\033[{code}m{txt}\033[0m" if sys.stdout.isatty() else str(txt)


def _green(t): return _c(t, "32")
def _red(t):   return _c(t, "31")
def _yellow(t): return _c(t, "33")
def _bold(t):  return _c(t, "1")


def _get(base, path):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=20) as r:
        return json.loads(r.read().decode())


def _fresh_tag(pct):
    if pct is None:
        return "—"
    if pct >= 80:
        return _green(f"{pct:.0f}%")
    if pct >= 50:
        return _yellow(f"{pct:.0f}%")
    return _red(f"{pct:.0f}%")


def _print_cycle(i, h, prev):
    wave = h.get("wave", {}) or {}
    rvol = h.get("rvol", {}) or {}
    q = h.get("qualify", {}) or {}
    up = wave.get("universe_progress", {}) or {}

    # Per-cycle qualify-rate from cumulative deltas (true per-cycle).
    cyc_rate = None
    if prev is not None:
        pe = prev.get("qualify", {}).get("cumulative_evals", 0)
        ph = prev.get("qualify", {}).get("cumulative_hits", 0)
        de = q.get("cumulative_evals", 0) - pe
        dh = q.get("cumulative_hits", 0) - ph
        if de > 0:
            cyc_rate = (dh / de) * 100

    print(f"\n{_bold(f'── cycle {i}  ' + datetime.now(timezone.utc).strftime('%H:%M:%S') + ' UTC ──')}")
    print(f"  WAVE   T1={wave.get('tier1_count', 0):>3} "
          f"T2={wave.get('tier2_count', 0):>3} "
          f"T3={wave.get('tier3_count', 0):>4} "
          f"uniq={wave.get('unique_count', 0):>4}  "
          f"progress={up.get('current_wave', '?')}/{up.get('total_waves', '?')} "
          f"({up.get('progress_pct', '?')}%)  "
          f"batch_age={wave.get('batch_age_seconds', '—')}s")
    if wave.get("tier1_sample"):
        print(f"         T1 {', '.join(wave['tier1_sample'])}")
    if wave.get("tier3_sample"):
        print(f"         T3 {', '.join(wave['tier3_sample'])}")
    print(f"  RVOL   cache={rvol.get('cache_size', 0):>4}  "
          f"fresh={_fresh_tag(rvol.get('fresh_pct'))}  "
          f"pass_gate={rvol.get('passing_gate_pct', 0):.0f}% (min {rvol.get('min_rvol_filter', 0)})  "
          f"oldest={rvol.get('oldest_age_seconds', '—')}s "
          f"newest={rvol.get('newest_age_seconds', '—')}s  ttl={rvol.get('cache_ttl_seconds', '—')}s")
    cyc_txt = f"{cyc_rate:.2f}%" if cyc_rate is not None else "—"
    print(f"  QUAL   scans={q.get('scan_count', 0)}  "
          f"scanned_last={q.get('symbols_scanned_last', 0)}  "
          f"skip(rvol={q.get('symbols_skipped_rvol', 0)},"
          f"adv={q.get('symbols_skipped_adv', 0)},"
          f"inplay={q.get('symbols_skipped_in_play', 0)})")
    print(f"         qualify-rate  cum={q.get('cumulative_qualify_rate_pct', 0):.2f}%  "
          f"last_cycle={q.get('last_cycle_qualify_rate_pct', 0):.2f}%  "
          f"Δper-poll={_bold(cyc_txt)}  "
          f"last_scan_age={q.get('last_scan_age_seconds', '—')}s")


def main():
    ap = argparse.ArgumentParser(description="Live in-play scanner health probe")
    ap.add_argument("--base", default="http://localhost:8001")
    ap.add_argument("--samples", type=int, default=4, help="number of polls")
    ap.add_argument("--gap", type=float, default=15.0, help="seconds between polls")
    args = ap.parse_args()

    print(_bold(f"In-play health probe → {args.base}  "
                f"({args.samples} polls × {args.gap:g}s)"))
    prev = None
    last = None
    for i in range(1, args.samples + 1):
        try:
            h = _get(args.base, "/api/scanner/in-play-health")
        except Exception as e:
            print(_red(f"✖ poll {i} failed: {e}"))
            return 2
        if not h.get("running", False) and not (h.get("wave") or {}).get("unique_count"):
            print(_yellow(f"  poll {i}: scanner not running / no wave batch yet "
                          f"({h.get('message', '')})"))
        _print_cycle(i, h, prev)
        prev = h
        last = h
        if i < args.samples:
            time.sleep(args.gap)

    # Summary verdict
    if last:
        rvol = last.get("rvol", {}) or {}
        q = last.get("qualify", {}) or {}
        print(f"\n{_bold('━' * 60)}")
        warns = []
        if (rvol.get("fresh_pct") or 0) < 50 and rvol.get("cache_size"):
            warns.append(_red("RVOL cache mostly STALE — sizing off old volume"))
        if (q.get("last_scan_age_seconds") or 0) and q["last_scan_age_seconds"] > 120:
            warns.append(_red(f"last scan {q['last_scan_age_seconds']}s ago — scanner may be stalled"))
        if q.get("cumulative_evals", 0) and q.get("cumulative_qualify_rate_pct", 0) == 0:
            warns.append(_yellow("0% cumulative qualify-rate — detectors evaluating but never hitting"))
        if warns:
            for w in warns:
                print(f"  ⚠ {w}")
        else:
            print(_green("  ✓ wave rotating, RVOL fresh, detectors qualifying — healthy"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
